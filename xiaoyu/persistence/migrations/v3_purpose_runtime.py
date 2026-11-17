from __future__ import annotations

import sqlite3

VERSION = 3
NAME = "purpose_runtime_fields_v3"


def apply(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(purposes)").fetchall()}
    if "last_evaluated_at" not in columns:
        conn.execute("ALTER TABLE purposes ADD COLUMN last_evaluated_at TEXT")
    if "quiet_class" not in columns:
        conn.execute(
            "ALTER TABLE purposes ADD COLUMN quiet_class TEXT NOT NULL DEFAULT 'NORMAL'"
        )
    if "duplicate_key" not in columns:
        conn.execute("ALTER TABLE purposes ADD COLUMN duplicate_key TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_purposes_due "
        "ON purposes(identity_id,state,resolved_utc_time)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_purposes_duplicate "
        "ON purposes(identity_id,duplicate_key,state)"
    )


def verify(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(purposes)").fetchall()}
    for required in ("last_evaluated_at", "quiet_class", "duplicate_key"):
        if required not in columns:
            raise RuntimeError("migration v3 purposes missing %s" % required)
