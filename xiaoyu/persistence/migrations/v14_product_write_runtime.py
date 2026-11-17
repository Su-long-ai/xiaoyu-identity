from __future__ import annotations

import sqlite3


VERSION = 14
NAME = "product_write_runtime_v14"


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS presentation_state (
            identity_id TEXT PRIMARY KEY,
            mood INTEGER NOT NULL,
            hunger INTEGER NOT NULL,
            energy INTEGER NOT NULL,
            bond INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_proposal_decisions (
            claim_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(
                state IN ('PENDING','APPROVED','REJECTED')
            ),
            memory_id TEXT,
            decision_event_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(claim_id) REFERENCES claims(claim_id),
            FOREIGN KEY(decision_event_id)
                REFERENCES canonical_events(event_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_memory_proposal_state
           ON memory_proposal_decisions(identity_id,state,created_at)"""
    )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for required in (
        "presentation_state",
        "memory_proposal_decisions",
    ):
        if required not in tables:
            raise RuntimeError(
                "migration v14 missing table %s" % required
            )
