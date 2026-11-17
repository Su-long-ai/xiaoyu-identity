from __future__ import annotations

import sqlite3

VERSION = 6
NAME = "execution_authorization_snapshot_v6"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(%s)" % table
        ).fetchall()
    }


def apply(conn: sqlite3.Connection) -> None:
    delegation_columns = _columns(conn, "delegations")
    if "delegation_digest" not in delegation_columns:
        conn.execute(
            "ALTER TABLE delegations ADD COLUMN delegation_digest TEXT"
        )
    if "revocable" not in delegation_columns:
        conn.execute(
            "ALTER TABLE delegations "
            "ADD COLUMN revocable INTEGER NOT NULL DEFAULT 1"
        )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS actor_registry (
            actor_id TEXT PRIMARY KEY,
            implementation_digest TEXT,
            authorization_digest TEXT,
            provider_id TEXT,
            updated_at TEXT NOT NULL
        )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS execution_authorizations (
            authorization_decision_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            principal_expires_at TEXT,
            actor_id TEXT NOT NULL,
            actor_implementation_digest TEXT,
            actor_authorization_digest TEXT,
            delegation_id TEXT,
            purpose_id TEXT,
            action_class TEXT NOT NULL,
            action_digest TEXT NOT NULL,
            resource_digest TEXT NOT NULL,
            context_digest TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            destination TEXT NOT NULL,
            audience_scope TEXT NOT NULL,
            context_space TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (authorization_decision_id)
                REFERENCES authorization_decisions(decision_id),
            FOREIGN KEY (delegation_id)
                REFERENCES delegations(delegation_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_execution_auth_actor
           ON execution_authorizations(actor_id,created_at)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_execution_auth_delegation
           ON execution_authorizations(delegation_id,created_at)"""
    )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for required in (
        "actor_registry",
        "execution_authorizations",
    ):
        if required not in tables:
            raise RuntimeError(
                "migration v6 missing table: %s" % required
            )
    columns = _columns(conn, "delegations")
    for required in ("delegation_digest", "revocable"):
        if required not in columns:
            raise RuntimeError(
                "migration v6 delegations missing %s" % required
            )
