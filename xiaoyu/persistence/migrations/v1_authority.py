from __future__ import annotations

import sqlite3


VERSION = 1
NAME = "authority_skeleton_v1"


STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS canonical_events (
        event_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        turn_id TEXT,
        event_type TEXT NOT NULL,
        surface TEXT NOT NULL,
        source_type TEXT NOT NULL,
        principal_id TEXT,
        audience_scope TEXT NOT NULL,
        context_space TEXT NOT NULL,
        trust_class TEXT NOT NULL,
        taint_json TEXT NOT NULL,
        eligible_for_memory INTEGER NOT NULL,
        payload_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_canonical_events_identity_recorded ON canonical_events(identity_id, recorded_at)",
    "CREATE INDEX IF NOT EXISTS idx_canonical_events_turn ON canonical_events(turn_id, recorded_at)",
    """CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object_json TEXT NOT NULL,
        trust_class TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS claim_sources (
        claim_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        PRIMARY KEY (claim_id, event_id),
        FOREIGN KEY (claim_id) REFERENCES claims(claim_id),
        FOREIGN KEY (event_id) REFERENCES canonical_events(event_id)
    )""",
    """CREATE TABLE IF NOT EXISTS temporal_facts (
        fact_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        value_json TEXT NOT NULL,
        valid_from TEXT,
        valid_to TEXT,
        recorded_at TEXT NOT NULL,
        status TEXT NOT NULL,
        supersedes_fact_id TEXT,
        FOREIGN KEY (claim_id) REFERENCES claims(claim_id),
        FOREIGN KEY (supersedes_fact_id) REFERENCES temporal_facts(fact_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_temporal_facts_lookup ON temporal_facts(identity_id, subject, predicate, status)",
    """CREATE TABLE IF NOT EXISTS projections (
        identity_id TEXT NOT NULL,
        projection_key TEXT NOT NULL,
        projection_type TEXT NOT NULL,
        value_json TEXT NOT NULL,
        source_fact_ids_json TEXT NOT NULL,
        builder_version TEXT NOT NULL,
        built_at TEXT NOT NULL,
        PRIMARY KEY (identity_id, projection_key, projection_type)
    )""",
    """CREATE TABLE IF NOT EXISTS relationship_state (
        identity_id TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        state TEXT NOT NULL,
        value_json TEXT NOT NULL,
        source_fact_ids_json TEXT NOT NULL,
        effective_from TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (identity_id, principal_id)
    )""",
    """CREATE TABLE IF NOT EXISTS promises (
        promise_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        speaker_actor TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        commitment_text TEXT NOT NULL,
        due_window_json TEXT,
        state TEXT NOT NULL,
        linked_purpose_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_event_id) REFERENCES canonical_events(event_id)
    )""",
    """CREATE TABLE IF NOT EXISTS purposes (
        purpose_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        owner_type TEXT NOT NULL,
        owner_id TEXT,
        state TEXT NOT NULL,
        kind TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        scheduled_wall_time TEXT,
        timezone TEXT,
        resolved_utc_time TEXT,
        miss_policy TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_event_id) REFERENCES canonical_events(event_id)
    )""",
    """CREATE TABLE IF NOT EXISTS activities (
        activity_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        participants_json TEXT NOT NULL,
        context_space TEXT NOT NULL,
        subject_ref TEXT,
        state_json TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        source_event_ids_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS delegations (
        delegation_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        purpose_id TEXT,
        scope_json TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        expires_at TEXT,
        revoked_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS authorization_decisions (
        decision_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        purpose_id TEXT,
        action_class TEXT NOT NULL,
        resource_json TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS effects (
        effect_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        intent_id TEXT NOT NULL,
        purpose_id TEXT,
        actor_id TEXT NOT NULL,
        action_class TEXT NOT NULL,
        idempotency_key TEXT,
        replayable INTEGER NOT NULL,
        dispatch_state TEXT NOT NULL,
        request_json TEXT NOT NULL,
        receipt_id TEXT,
        verifier_state TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_effects_idempotency ON effects(identity_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS outbox (
        outbox_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        effect_id TEXT NOT NULL,
        destination TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        state TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (effect_id) REFERENCES effects(effect_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox(state, next_attempt_at, created_at)",
    """CREATE TABLE IF NOT EXISTS action_receipts (
        receipt_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        effect_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        provider_id TEXT,
        authorization_decision_id TEXT NOT NULL,
        result_class TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        result_digest TEXT,
        external_ref TEXT,
        observed_at TEXT NOT NULL,
        receipt_json TEXT NOT NULL,
        FOREIGN KEY (effect_id) REFERENCES effects(effect_id),
        FOREIGN KEY (authorization_decision_id) REFERENCES authorization_decisions(decision_id)
    )""",
    """CREATE TABLE IF NOT EXISTS deliveries (
        delivery_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        logical_notification_id TEXT NOT NULL,
        purpose_id TEXT,
        surface TEXT NOT NULL,
        state TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        external_ref TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_deliveries_logical ON deliveries(identity_id, logical_notification_id, state)",
    """CREATE TABLE IF NOT EXISTS erasure_tombstones (
        erasure_id TEXT PRIMARY KEY,
        identity_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        erasure_generation INTEGER NOT NULL,
        requested_at TEXT NOT NULL,
        applied_at TEXT,
        source_event_id TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_erasure_generation ON erasure_tombstones(identity_id, erasure_generation)",
    """CREATE TABLE IF NOT EXISTS provider_registry (
        provider_id TEXT PRIMARY KEY,
        capability TEXT NOT NULL,
        descriptor_json TEXT NOT NULL,
        artifact_digest TEXT,
        descriptor_digest TEXT NOT NULL,
        interface_digest TEXT NOT NULL,
        tool_schema_digest TEXT,
        lifecycle_state TEXT NOT NULL,
        health_state_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
)


REQUIRED_TABLES = {
    "canonical_events", "claims", "claim_sources", "temporal_facts", "projections",
    "relationship_state", "promises", "purposes", "activities", "delegations",
    "authorization_decisions", "effects", "outbox", "action_receipts", "deliveries",
    "erasure_tombstones", "provider_registry",
}


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = REQUIRED_TABLES - existing
    if missing:
        raise RuntimeError("migration v1 missing tables: %s" % ", ".join(sorted(missing)))

    event_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(canonical_events)").fetchall()
    }
    for required in (
        "event_id", "identity_id", "source_type", "trust_class",
        "eligible_for_memory", "payload_type", "payload_json",
        "correlation_id", "schema_version",
    ):
        if required not in event_columns:
            raise RuntimeError("migration v1 canonical_events missing column: %s" % required)
