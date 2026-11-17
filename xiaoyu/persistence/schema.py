from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .db import Database
from .migrations import v1_authority


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable
    verify: Callable


MIGRATIONS = (
    Migration(v1_authority.VERSION, v1_authority.NAME, v1_authority.apply, v1_authority.verify),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _ensure_migration_table(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )


def applied_versions(db: Database) -> List[int]:
    with db.transaction() as conn:
        _ensure_migration_table(conn)
        return [int(row[0]) for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()]


def apply_migrations(db: Database, target_version: Optional[int] = None) -> List[int]:
    applied_now: List[int] = []
    for migration in MIGRATIONS:
        if target_version is not None and migration.version > target_version:
            break
        with db.transaction(immediate=True) as conn:
            _ensure_migration_table(conn)
            present = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?", (migration.version,)
            ).fetchone()
            if present is not None:
                migration.verify(conn)
                continue
            migration.apply(conn)
            migration.verify(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (migration.version, migration.name, _now()),
            )
            applied_now.append(migration.version)
    return applied_now


def verify_schema(db: Database) -> None:
    with db.transaction() as conn:
        _ensure_migration_table(conn)
        versions = {
            int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in MIGRATIONS:
            if migration.version in versions:
                migration.verify(conn)
