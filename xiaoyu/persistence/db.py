from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Union


PathLike = Union[str, Path]


class Database:
    """Small SQLite boundary with no XiaoYu business semantics."""

    def __init__(self, path: PathLike, timeout_s: float = 15.0) -> None:
        self.path = Path(path)
        self.timeout_s = timeout_s

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=self.timeout_s)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=%d" % int(self.timeout_s * 1000))
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        except Exception:
            conn.close()
            raise

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def integrity_check(self) -> List[str]:
        conn = self.connect()
        try:
            return [str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall()]
        finally:
            conn.close()

    def is_healthy(self) -> bool:
        return self.integrity_check() == ["ok"]

    def backup_to(self, target: PathLike) -> Path:
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        destination = sqlite3.connect(str(target_path), timeout=self.timeout_s)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()
        return target_path
