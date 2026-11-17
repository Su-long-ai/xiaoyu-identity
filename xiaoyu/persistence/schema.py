from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .db import Database
from .migrations import v1_authority, v2_receipts_delivery, v3_purpose_runtime, v4_delivery_attempts, v5_temporal_shadow, v6_execution_authorization


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable
    verify: Callable


MIGRATIONS = (
    Migration(v1_authority.VERSION, v1_authority.NAME, v1_authority.apply, v1_authority.verify),
    Migration(v2_receipts_delivery.VERSION, v2_receipts_delivery.NAME, v2_receipts_delivery.apply, v2_receipts_delivery.verify),
    Migration(v3_purpose_runtime.VERSION, v3_purpose_runtime.NAME, v3_purpose_runtime.apply, v3_purpose_runtime.verify),
    Migration(v4_delivery_attempts.VERSION, v4_delivery_attempts.NAME, v4_delivery_attempts.apply, v4_delivery_attempts.verify),
    Migration(v5_temporal_shadow.VERSION, v5_temporal_shadow.NAME, v5_temporal_shadow.apply, v5_temporal_shadow.verify),
    Migration(v6_execution_authorization.VERSION, v6_execution_authorization.NAME, v6_execution_authorization.apply, v6_execution_authorization.verify),
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
