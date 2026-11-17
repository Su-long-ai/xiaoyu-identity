from __future__ import annotations

import sqlite3


VERSION = 9
NAME = "execution_principal_validity_v9"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(%s)" % table
        ).fetchall()
    }


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS execution_principals (
            identity_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            session_scope TEXT NOT NULL,
            authentication_level TEXT NOT NULL,
            context_digest TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(identity_id,principal_id,session_scope)
        )"""
    )
    columns = _columns(conn, "execution_authorizations")
    if "principal_session_scope" not in columns:
        conn.execute(
            "ALTER TABLE execution_authorizations "
            "ADD COLUMN principal_session_scope TEXT"
        )
    if "principal_context_digest" not in columns:
        conn.execute(
            "ALTER TABLE execution_authorizations "
            "ADD COLUMN principal_context_digest TEXT"
        )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "execution_principals" not in tables:
        raise RuntimeError("migration v9 execution_principals missing")
    columns = _columns(conn, "execution_authorizations")
    for required in (
        "principal_session_scope",
        "principal_context_digest",
    ):
        if required not in columns:
            raise RuntimeError(
                "migration v9 execution authorization missing %s"
                % required
            )
