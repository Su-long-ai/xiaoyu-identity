from __future__ import annotations

import sqlite3

VERSION = 5
NAME = "temporal_shadow_invariants_v5"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(
        "PRAGMA table_info(%s)" % table
    ).fetchall()}


def apply(conn: sqlite3.Connection) -> None:
    event_columns = _columns(conn, "canonical_events")
    if "source_namespace" not in event_columns:
        conn.execute(
            "ALTER TABLE canonical_events "
            "ADD COLUMN source_namespace TEXT NOT NULL DEFAULT 'legacy'"
        )
    if "source_event_key" not in event_columns:
        conn.execute(
            "ALTER TABLE canonical_events ADD COLUMN source_event_key TEXT"
        )
    if "semantic_digest" not in event_columns:
        conn.execute(
            "ALTER TABLE canonical_events ADD COLUMN semantic_digest TEXT"
        )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_source_key
           ON canonical_events(identity_id,source_namespace,source_event_key)
           WHERE source_event_key IS NOT NULL"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS canonical_event_ingest (
            ingest_revision INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            identity_id TEXT NOT NULL,
            inserted_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES canonical_events(event_id)
        )"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO canonical_event_ingest(
               event_id,identity_id,inserted_at
           )
           SELECT event_id,identity_id,recorded_at
           FROM canonical_events
           ORDER BY recorded_at,event_id"""
    )

    claim_columns = _columns(conn, "claims")
    for ddl in (
        ("mutation_id", "ALTER TABLE claims ADD COLUMN mutation_id TEXT"),
        ("principal_scope", "ALTER TABLE claims ADD COLUMN principal_scope TEXT"),
        ("context_space", "ALTER TABLE claims ADD COLUMN context_space TEXT"),
        ("audience_scope", "ALTER TABLE claims ADD COLUMN audience_scope TEXT"),
        ("taint_json", "ALTER TABLE claims ADD COLUMN taint_json TEXT"),
        (
            "eligible_for_memory",
            "ALTER TABLE claims ADD COLUMN eligible_for_memory INTEGER NOT NULL DEFAULT 0",
        ),
        ("decision_reason", "ALTER TABLE claims ADD COLUMN decision_reason TEXT"),
    ):
        if ddl[0] not in claim_columns:
            conn.execute(ddl[1])

    fact_columns = _columns(conn, "temporal_facts")
    for ddl in (
        ("fact_key", "ALTER TABLE temporal_facts ADD COLUMN fact_key TEXT"),
        ("principal_scope", "ALTER TABLE temporal_facts ADD COLUMN principal_scope TEXT"),
        ("context_space", "ALTER TABLE temporal_facts ADD COLUMN context_space TEXT"),
        (
            "cardinality",
            "ALTER TABLE temporal_facts ADD COLUMN cardinality TEXT NOT NULL DEFAULT 'SINGLE'",
        ),
        (
            "revision",
            "ALTER TABLE temporal_facts ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
        ),
        ("mutation_id", "ALTER TABLE temporal_facts ADD COLUMN mutation_id TEXT"),
    ):
        if ddl[0] not in fact_columns:
            conn.execute(ddl[1])

    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_temporal_fact_key
           ON temporal_facts(identity_id,fact_key,status,valid_from,valid_to)"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS fact_authority_revisions (
            identity_id TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            current_revision INTEGER NOT NULL,
            last_source_ingest_revision INTEGER NOT NULL,
            erasure_generation INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(identity_id,fact_key)
        )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS fact_mutations (
            mutation_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            source_ingest_revision INTEGER NOT NULL,
            claim_id TEXT,
            fact_key TEXT NOT NULL,
            operation TEXT NOT NULL,
            mutation_digest TEXT NOT NULL,
            expected_revision INTEGER NOT NULL,
            result_revision INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_event_id) REFERENCES canonical_events(event_id)
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_fact_mutations_key_revision
           ON fact_mutations(identity_id,fact_key,result_revision)"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS projection_invalidations (
            identity_id TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            erasure_generation INTEGER NOT NULL,
            mutation_id TEXT NOT NULL,
            invalidated_at TEXT NOT NULL,
            PRIMARY KEY(identity_id,fact_key,source_revision)
        )"""
    )

    projection_columns = _columns(conn, "projections")
    if "source_revision" not in projection_columns:
        conn.execute(
            "ALTER TABLE projections "
            "ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 0"
        )
    if "erasure_generation" not in projection_columns:
        conn.execute(
            "ALTER TABLE projections "
            "ADD COLUMN erasure_generation INTEGER NOT NULL DEFAULT 0"
        )

    erasure_columns = _columns(conn, "erasure_tombstones")
    if "source_ingest_revision" not in erasure_columns:
        conn.execute(
            "ALTER TABLE erasure_tombstones "
            "ADD COLUMN source_ingest_revision INTEGER"
        )
    if "mutation_id" not in erasure_columns:
        conn.execute(
            "ALTER TABLE erasure_tombstones ADD COLUMN mutation_id TEXT"
        )


def verify(conn: sqlite3.Connection) -> None:
    required_event = {
        "source_namespace", "source_event_key", "semantic_digest"
    }
    if not required_event.issubset(_columns(conn, "canonical_events")):
        raise RuntimeError("migration v5 canonical event identity fields missing")

    required_fact = {
        "fact_key", "principal_scope", "context_space",
        "cardinality", "revision", "mutation_id",
    }
    if not required_fact.issubset(_columns(conn, "temporal_facts")):
        raise RuntimeError("migration v5 temporal fact fields missing")

    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for required in (
        "canonical_event_ingest",
        "fact_authority_revisions",
        "fact_mutations",
        "projection_invalidations",
    ):
        if required not in tables:
            raise RuntimeError("migration v5 missing table: %s" % required)
