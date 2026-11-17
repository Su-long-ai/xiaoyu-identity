from __future__ import annotations

import sqlite3


VERSION = 12
NAME = "authority_cutover_writer_fence_v12"

LEGACY_AUTHORITY_TABLES = (
    "events",
    "memories",
    "memory_proposals",
    "persona_versions",
    "settings",
)


def _trigger_name(table: str, operation: str) -> str:
    return "xiaoyu_fence_%s_%s" % (table, operation.lower())


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS authority_cutover_state (
            identity_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL CHECK(mode IN ('SHADOW','CANONICAL')),
            activated_at TEXT,
            activation_digest TEXT,
            legacy_event_high_watermark INTEGER NOT NULL DEFAULT 0,
            legacy_memory_change_seq INTEGER NOT NULL DEFAULT 0,
            forward_only INTEGER NOT NULL DEFAULT 1
        )"""
    )

    for table in LEGACY_AUTHORITY_TABLES:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            name = _trigger_name(table, operation)
            conn.execute(
                """CREATE TRIGGER IF NOT EXISTS %s
                   BEFORE %s ON %s
                   WHEN EXISTS(
                       SELECT 1 FROM authority_cutover_state
                       WHERE mode='CANONICAL'
                   )
                   BEGIN
                       SELECT RAISE(
                           ABORT,
                           'XIAOYU_CANONICAL_AUTHORITY_ACTIVE'
                       );
                   END"""
                % (name, operation, table)
            )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "authority_cutover_state" not in tables:
        raise RuntimeError(
            "migration v12 authority_cutover_state missing"
        )

    triggers = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    for table in LEGACY_AUTHORITY_TABLES:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            required = _trigger_name(table, operation)
            if required not in triggers:
                raise RuntimeError(
                    "migration v12 writer fence missing %s" % required
                )
