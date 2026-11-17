from __future__ import annotations

import sqlite3


VERSION = 13
NAME = "self_identity_persona_authority_v13"


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS self_identity (
            identity_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            current_persona_revision INTEGER NOT NULL,
            authority_digest TEXT NOT NULL,
            namespace TEXT NOT NULL DEFAULT 'xiaoyu'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS self_persona_versions (
            identity_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            persona_json TEXT NOT NULL,
            persona_digest TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_event_ids_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            legacy_persona_version INTEGER,
            PRIMARY KEY(identity_id,revision),
            FOREIGN KEY(identity_id)
                REFERENCES self_identity(identity_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_self_persona_created
           ON self_persona_versions(identity_id,created_at,revision)"""
    )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for required in ("self_identity", "self_persona_versions"):
        if required not in tables:
            raise RuntimeError(
                "migration v13 missing table %s" % required
            )
    identity_columns = {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(self_identity)"
        ).fetchall()
    }
    for required in (
        "identity_id",
        "created_at",
        "current_persona_revision",
        "authority_digest",
        "namespace",
    ):
        if required not in identity_columns:
            raise RuntimeError(
                "migration v13 self_identity missing %s" % required
            )
