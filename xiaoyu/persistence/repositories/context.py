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
        principal_id: str,
        context_space: str,
        allowed_audiences: tuple[str, ...],
        private_scope: bool,
    ):
        if not allowed_audiences:
            return []
        placeholders = ",".join("?" for _ in allowed_audiences)
        principal_clause = (
            " AND ce.principal_id=?"
            if private_scope
            else ""
        )
        params = [
            identity_id,
            context_space,
            *allowed_audiences,
        ]
        if private_scope:
            params.append(principal_id)
        return conn.execute(
            """SELECT p.purpose_id,p.owner_type,p.owner_id,p.state,p.kind,
                      p.payload_json,p.revision,p.source_event_id,
                      p.resolved_utc_time,p.timezone,
                      ce.principal_id AS source_principal_id,
                      ce.audience_scope AS source_audience_scope,
                      ce.context_space AS source_context_space
               FROM purposes p
               JOIN canonical_events ce
                 ON ce.event_id=p.source_event_id
               WHERE p.identity_id=?
                 AND p.state IN (
                     'CONFIRMED','SCHEDULED','ACTIVE','WAITING',
                     'NEEDS_RECONCILIATION'
                 )
                 AND ce.context_space=?
                 AND ce.audience_scope IN (%s)%s
               ORDER BY p.updated_at,p.purpose_id"""
            % (placeholders, principal_clause),
            tuple(params),
        ).fetchall()

    def active_delegations(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_id: str,
        context_space: str,
        allowed_audiences: tuple[str, ...],
        private_scope: bool,
        now: datetime,
    ):
        if not allowed_audiences:
            return []
        stamp = datetime_to_text(
            now.astimezone(timezone.utc), "now"
        )
        if private_scope:
            placeholders = ",".join("?" for _ in allowed_audiences)
            return conn.execute(
                """SELECT d.delegation_id,d.principal_id,d.actor_id,
                          d.purpose_id,d.scope_json,d.valid_from,d.expires_at,
                          d.revoked_at,d.delegation_digest,d.revocable
                   FROM delegations d
                   WHERE d.identity_id=? AND d.principal_id=?
                     AND d.revoked_at IS NULL
                     AND d.valid_from<=?
                     AND (d.expires_at IS NULL OR d.expires_at>?)
                     AND (
                         NOT EXISTS(
                             SELECT 1 FROM execution_authorizations any_ea
                             WHERE any_ea.delegation_id=d.delegation_id
                         )
                         OR EXISTS(
                             SELECT 1 FROM execution_authorizations ea
                             WHERE ea.delegation_id=d.delegation_id
                               AND ea.identity_id=d.identity_id
                               AND ea.principal_id=d.principal_id
                               AND ea.context_space=?
                               AND ea.audience_scope IN (%s)
                         )
                     )
                   ORDER BY d.delegation_id"""
                % placeholders,
                (
                    identity_id,
                    principal_id,
                    stamp,
                    stamp,
                    context_space,
                    *allowed_audiences,
                ),
            ).fetchall()

        # A standing delegation has no audience field. In non-private contexts
        # expose it only if a durable execution authorization proves that the
        # same delegation was admitted for this audience/context.
        placeholders = ",".join("?" for _ in allowed_audiences)
        return conn.execute(
            """SELECT DISTINCT d.delegation_id,d.principal_id,d.actor_id,
                      d.purpose_id,d.scope_json,d.valid_from,d.expires_at,
                      d.revoked_at,d.delegation_digest,d.revocable
               FROM delegations d
               JOIN execution_authorizations ea
                 ON ea.delegation_id=d.delegation_id
                AND ea.identity_id=d.identity_id
                AND ea.principal_id=d.principal_id
               WHERE d.identity_id=? AND d.principal_id=?
                 AND d.revoked_at IS NULL
                 AND d.valid_from<=?
                 AND (d.expires_at IS NULL OR d.expires_at>?)
                 AND ea.context_space=?
                 AND ea.audience_scope IN (%s)
               ORDER BY d.delegation_id"""
            % placeholders,
            (
                identity_id,
                principal_id,
                stamp,
                stamp,
                context_space,
                *allowed_audiences,
            ),
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
        principal_id: str,
        context_space: str,
        allowed_audiences: tuple[str, ...],
        private_scope: bool,
    ):
        if not allowed_audiences:
            return []
        placeholders = ",".join("?" for _ in allowed_audiences)

        if private_scope:
            # Preserve legacy unresolved work that predates durable execution
            # authorization snapshots, but never import an effect that is
            # explicitly bound to a different audience/context.
            return conn.execute(
                """SELECT e.effect_id,e.purpose_id,e.actor_id,e.action_class,
                          e.dispatch_state,e.request_json,e.updated_at,
                          ea.principal_id AS authorized_principal_id,
                          ea.audience_scope AS authorized_audience_scope,
                          ea.context_space AS authorized_context_space
                   FROM effects e
                   LEFT JOIN execution_authorizations ea
                     ON ea.authorization_decision_id=
                        e.authorization_decision_id
                   WHERE e.identity_id=?
                     AND e.dispatch_state IN (
                         'QUEUED','CLAIMED','DISPATCHING',
                         'NEEDS_RECONCILIATION'
                     )
                     AND (
                         ea.authorization_decision_id IS NULL
                         OR (
                             ea.principal_id=?
                             AND ea.context_space=?
                             AND ea.audience_scope IN (%s)
                         )
                     )
                   ORDER BY e.updated_at,e.effect_id"""
                % placeholders,
                (
                    identity_id,
                    principal_id,
                    context_space,
                    *allowed_audiences,
                ),
            ).fetchall()

        # Non-private context is fail-closed: unresolved external work is
        # visible only when its durable authorization snapshot proves the
        # same audience and context-space binding.
        return conn.execute(
            """SELECT e.effect_id,e.purpose_id,e.actor_id,e.action_class,
                      e.dispatch_state,e.request_json,e.updated_at,
                      ea.principal_id AS authorized_principal_id,
                      ea.audience_scope AS authorized_audience_scope,
                      ea.context_space AS authorized_context_space
               FROM effects e
               JOIN execution_authorizations ea
                 ON ea.authorization_decision_id=
                    e.authorization_decision_id
               WHERE e.identity_id=?
                 AND e.dispatch_state IN (
                     'QUEUED','CLAIMED','DISPATCHING',
                     'NEEDS_RECONCILIATION'
                 )
                 AND ea.context_space=?
                 AND ea.audience_scope IN (%s)
               ORDER BY e.updated_at,e.effect_id"""
            % placeholders,
            (
                identity_id,
                context_space,
                *allowed_audiences,
            ),
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
