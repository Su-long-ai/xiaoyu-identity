from __future__ import annotations

import sqlite3

VERSION = 10
NAME = "profile_relationship_promise_v10"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    }


def apply(conn: sqlite3.Connection) -> None:
    relationship_columns = _columns(conn, "relationship_state")
    if "revision" not in relationship_columns:
        conn.execute(
            "ALTER TABLE relationship_state "
            "ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
        )
    if "builder_version" not in relationship_columns:
        conn.execute(
            "ALTER TABLE relationship_state "
            "ADD COLUMN builder_version TEXT NOT NULL DEFAULT 'r10.relationship.v1'"
        )
    if "source_event_ids_json" not in relationship_columns:
        conn.execute(
            "ALTER TABLE relationship_state "
            "ADD COLUMN source_event_ids_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "last_transition_id" not in relationship_columns:
        conn.execute(
            "ALTER TABLE relationship_state ADD COLUMN last_transition_id TEXT"
        )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS relationship_transitions (
            transition_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            transition_id TEXT NOT NULL UNIQUE,
            identity_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            source_ingest_revision INTEGER NOT NULL,
            value_patch_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_event_id) REFERENCES canonical_events(event_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_relationship_transition_principal
           ON relationship_transitions(
               identity_id,principal_id,transition_sequence
           )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS promise_candidates (
            candidate_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            source_ingest_revision INTEGER NOT NULL,
            speaker_actor TEXT NOT NULL,
            commitment_text TEXT NOT NULL,
            due_window_json TEXT,
            explicit_commitment INTEGER NOT NULL,
            state TEXT NOT NULL,
            promoted_promise_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_event_id) REFERENCES canonical_events(event_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_promise_candidate_identity_state
           ON promise_candidates(identity_id,state,created_at)"""
    )

    promise_columns = _columns(conn, "promises")
    if "candidate_id" not in promise_columns:
        conn.execute("ALTER TABLE promises ADD COLUMN candidate_id TEXT")
    if "revision" not in promise_columns:
        conn.execute(
            "ALTER TABLE promises ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
        )
    if "source_ingest_revision" not in promise_columns:
        conn.execute(
            "ALTER TABLE promises ADD COLUMN source_ingest_revision INTEGER"
        )
    if "last_transition_id" not in promise_columns:
        conn.execute(
            "ALTER TABLE promises ADD COLUMN last_transition_id TEXT"
        )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS promise_transitions (
            transition_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            transition_id TEXT NOT NULL UNIQUE,
            promise_id TEXT NOT NULL,
            identity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            linked_purpose_id TEXT,
            source_event_id TEXT NOT NULL,
            source_ingest_revision INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (promise_id) REFERENCES promises(promise_id),
            FOREIGN KEY (source_event_id) REFERENCES canonical_events(event_id),
            FOREIGN KEY (linked_purpose_id) REFERENCES purposes(purpose_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_promise_transition_order
           ON promise_transitions(
               identity_id,promise_id,transition_sequence
           )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_projections_type_key
           ON projections(identity_id,projection_type,projection_key)"""
    )


def verify(conn: sqlite3.Connection) -> None:
    relationship_columns = _columns(conn, "relationship_state")
    for required in (
        "revision",
        "builder_version",
        "source_event_ids_json",
        "last_transition_id",
    ):
        if required not in relationship_columns:
            raise RuntimeError(
                "migration v10 relationship_state missing %s" % required
            )

    promise_columns = _columns(conn, "promises")
    for required in (
        "candidate_id",
        "revision",
        "source_ingest_revision",
        "last_transition_id",
    ):
        if required not in promise_columns:
            raise RuntimeError(
                "migration v10 promises missing %s" % required
            )

    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for required in (
        "relationship_transitions",
        "promise_candidates",
        "promise_transitions",
    ):
        if required not in tables:
            raise RuntimeError("migration v10 missing table %s" % required)
