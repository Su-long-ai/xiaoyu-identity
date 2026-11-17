from __future__ import annotations

import sqlite3

VERSION = 7
NAME = "purpose_occurrence_revision_v7"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(%s)" % table
        ).fetchall()
    }


def apply(conn: sqlite3.Connection) -> None:
    purpose_columns = _columns(conn, "purposes")
    if "revision" not in purpose_columns:
        conn.execute(
            "ALTER TABLE purposes "
            "ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
        )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS purpose_occurrences (
            occurrence_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            purpose_id TEXT NOT NULL,
            purpose_revision INTEGER NOT NULL,
            scheduled_for_utc TEXT NOT NULL,
            state TEXT NOT NULL,
            effect_id TEXT,
            activated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(purpose_id,purpose_revision),
            FOREIGN KEY (purpose_id) REFERENCES purposes(purpose_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_purpose_occurrence_ready
           ON purpose_occurrences(identity_id,state,scheduled_for_utc)"""
    )

    effect_columns = _columns(conn, "effects")
    if "purpose_revision" not in effect_columns:
        conn.execute(
            "ALTER TABLE effects ADD COLUMN purpose_revision INTEGER"
        )
    if "purpose_occurrence_id" not in effect_columns:
        conn.execute(
            "ALTER TABLE effects ADD COLUMN purpose_occurrence_id TEXT"
        )

    auth_columns = _columns(conn, "execution_authorizations")
    if "purpose_revision" not in auth_columns:
        conn.execute(
            "ALTER TABLE execution_authorizations "
            "ADD COLUMN purpose_revision INTEGER"
        )
    if "purpose_occurrence_id" not in auth_columns:
        conn.execute(
            "ALTER TABLE execution_authorizations "
            "ADD COLUMN purpose_occurrence_id TEXT"
        )


def verify(conn: sqlite3.Connection) -> None:
    if "revision" not in _columns(conn, "purposes"):
        raise RuntimeError("migration v7 purpose revision missing")
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "purpose_occurrences" not in tables:
        raise RuntimeError("migration v7 purpose_occurrences missing")
    for required in ("purpose_revision", "purpose_occurrence_id"):
        if required not in _columns(conn, "effects"):
            raise RuntimeError(
                "migration v7 effects missing %s" % required
            )
        if required not in _columns(conn, "execution_authorizations"):
            raise RuntimeError(
                "migration v7 execution authorization missing %s"
                % required
            )
