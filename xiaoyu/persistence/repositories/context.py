from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from xiaoyu.contracts.common import canonical_json, datetime_to_text


class MemoryContextRepository:
    def current_fact_candidates(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        allowed_audiences: tuple[str, ...],
    ):
        if not allowed_audiences:
            return []
        placeholders = ",".join("?" for _ in allowed_audiences)
        return conn.execute(
            """SELECT tf.fact_id,tf.fact_key,tf.subject,tf.predicate,
                      tf.value_json,tf.revision,tf.cardinality,
                      c.audience_scope,c.eligible_for_memory
               FROM temporal_facts tf
               JOIN claims c ON c.claim_id=tf.claim_id
               WHERE tf.identity_id=?
                 AND tf.principal_scope=?
                 AND tf.context_space=?
                 AND tf.status='CURRENT'
                 AND c.eligible_for_memory=1
                 AND c.audience_scope IN (%s)
               ORDER BY tf.revision DESC,tf.fact_id"""
            % placeholders,
            (
                identity_id,
                principal_scope,
                context_space,
                *allowed_audiences,
            ),
        ).fetchall()

    def active_purposes(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT purpose_id,owner_type,owner_id,state,kind,payload_json,
                      revision,source_event_id,resolved_utc_time,timezone
               FROM purposes
               WHERE identity_id=?
                 AND state IN (
                     'CONFIRMED','SCHEDULED','ACTIVE','WAITING',
                     'NEEDS_RECONCILIATION'
                 )
               ORDER BY updated_at,purpose_id""",
            (identity_id,),
        ).fetchall()

    def active_delegations(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_id: str,
        now: datetime,
    ):
        stamp = datetime_to_text(now.astimezone(timezone.utc), "now")
        return conn.execute(
            """SELECT delegation_id,principal_id,actor_id,purpose_id,
                      scope_json,valid_from,expires_at,revoked_at,
                      delegation_digest,revocable
               FROM delegations
               WHERE identity_id=? AND principal_id=?
                 AND revoked_at IS NULL
                 AND valid_from<=?
                 AND (expires_at IS NULL OR expires_at>?)
               ORDER BY delegation_id""",
            (identity_id, principal_id, stamp, stamp),
        ).fetchall()

    def current_corrections(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        allowed_audiences: tuple[str, ...],
    ):
        if not allowed_audiences:
            return []
        placeholders = ",".join("?" for _ in allowed_audiences)
        return conn.execute(
            """SELECT tf.fact_id,tf.fact_key,tf.subject,tf.predicate,
                      tf.value_json,tf.revision,fm.mutation_id,
                      c.audience_scope
               FROM temporal_facts tf
               JOIN fact_mutations fm
                 ON fm.mutation_id=tf.mutation_id
               JOIN claims c ON c.claim_id=tf.claim_id
               WHERE tf.identity_id=?
                 AND tf.principal_scope=?
                 AND tf.context_space=?
                 AND tf.status='CURRENT'
                 AND fm.operation='CORRECT'
                 AND c.audience_scope IN (%s)
               ORDER BY tf.revision DESC,tf.fact_id"""
            % placeholders,
            (
                identity_id,
                principal_scope,
                context_space,
                *allowed_audiences,
            ),
        ).fetchall()

    def unresolved_effects(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT effect_id,purpose_id,actor_id,action_class,
                      dispatch_state,request_json,updated_at
               FROM effects
               WHERE identity_id=?
                 AND dispatch_state IN (
                     'QUEUED','CLAIMED','DISPATCHING',
                     'NEEDS_RECONCILIATION'
                 )
               ORDER BY updated_at,effect_id""",
            (identity_id,),
        ).fetchall()

    def authority_freshness(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
    ) -> tuple[int, int]:
        mutation = conn.execute(
            """SELECT COALESCE(MAX(fmo.mutation_sequence),0)
               FROM fact_mutation_order fmo
               JOIN fact_mutations fm
                 ON fm.mutation_id=fmo.mutation_id
               WHERE fm.identity_id=?""",
            (identity_id,),
        ).fetchone()
        erasure = conn.execute(
            """SELECT COALESCE(MAX(erasure_generation),0)
               FROM erasure_tombstones WHERE identity_id=?""",
            (identity_id,),
        ).fetchone()
        return int(mutation[0]), int(erasure[0])

    def insert_summary(
        self,
        conn: sqlite3.Connection,
        *,
        summary_id: str,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        audience_scope: str,
        fidelity_class: str,
        summary_text: str,
        source_event_ids: list[str],
        source_digest: str,
        source_revision: int,
        erasure_generation: int,
        builder_version: str,
        created_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO context_summaries(
                   summary_id,identity_id,principal_scope,context_space,
                   audience_scope,fidelity_class,summary_text,
                   source_event_ids_json,source_digest,source_revision,
                   erasure_generation,builder_version,status,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?)""",
            (
                summary_id,
                identity_id,
                principal_scope,
                context_space,
                audience_scope,
                fidelity_class,
                summary_text,
                canonical_json(source_event_ids),
                source_digest,
                source_revision,
                erasure_generation,
                builder_version,
                datetime_to_text(created_at, "created_at"),
            ),
        )

    def summaries_for_scope(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        audience_scope: str,
        limit: int = 20,
    ):
        return conn.execute(
            """SELECT * FROM context_summaries
               WHERE identity_id=? AND principal_scope=?
                 AND context_space=? AND audience_scope=?
                 AND status='ACTIVE'
               ORDER BY created_at DESC,summary_id
               LIMIT ?""",
            (
                identity_id,
                principal_scope,
                context_space,
                audience_scope,
                max(1, min(int(limit), 100)),
            ),
        ).fetchall()

    def source_events(
        self,
        conn: sqlite3.Connection,
        event_ids: Iterable[str],
    ):
        ids = list(event_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            """SELECT event_id,identity_id,principal_id,context_space,
                      audience_scope,semantic_digest,recorded_at
               FROM canonical_events
               WHERE event_id IN (%s)"""
            % placeholders,
            tuple(ids),
        ).fetchall()
        by_id = {str(row["event_id"]): row for row in rows}
        return [by_id[event_id] for event_id in ids if event_id in by_id]
