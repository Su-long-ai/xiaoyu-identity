from __future__ import annotations

import sqlite3


VERSION = 8
NAME = "execution_dispatch_binding_v8"


_COLUMNS = (
    ("delegation_digest", "TEXT"),
    ("actor_provider_id", "TEXT"),
    ("provider_artifact_digest", "TEXT"),
    ("provider_descriptor_digest", "TEXT"),
    ("provider_interface_digest", "TEXT"),
    ("provider_tool_schema_digest", "TEXT"),
    ("provider_capability", "TEXT"),
    ("provider_lifecycle_state", "TEXT"),
    ("authorized_request_digest", "TEXT"),
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(%s)" % table
        ).fetchall()
    }


def apply(conn: sqlite3.Connection) -> None:
    columns = _columns(conn, "execution_authorizations")
    for name, sql_type in _COLUMNS:
        if name not in columns:
            conn.execute(
                "ALTER TABLE execution_authorizations ADD COLUMN %s %s"
                % (name, sql_type)
            )


def verify(conn: sqlite3.Connection) -> None:
    columns = _columns(conn, "execution_authorizations")
    for name, _ in _COLUMNS:
        if name not in columns:
            raise RuntimeError(
                "migration v8 execution authorization missing %s" % name
            )
