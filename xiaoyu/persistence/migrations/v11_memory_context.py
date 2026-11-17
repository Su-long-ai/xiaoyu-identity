from __future__ import annotations

import sqlite3

VERSION = 11
NAME = "memory_context_summary_v11"


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS context_summaries (
            summary_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            principal_scope TEXT NOT NULL,
            context_space TEXT NOT NULL,
            audience_scope TEXT NOT NULL,
            fidelity_class TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            source_event_ids_json TEXT NOT NULL,
            source_digest TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            erasure_generation INTEGER NOT NULL,
            builder_version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_context_summaries_scope
           ON context_summaries(
               identity_id,principal_scope,context_space,
               audience_scope,status,created_at
           )"""
    )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "context_summaries" not in tables:
        raise RuntimeError("migration v11 context_summaries missing")
