from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from xiaoyu.persistence import Database, apply_migrations, applied_versions
from xiaoyu.persistence.erasure import ExternalErasureFenceStore, ErasureWatermarkError
from xiaoyu.persistence.recovery import (
    MissingErasureWatermark,
    RecoveryManager,
    RestoreMode,
)
from xiaoyu.persistence.repositories.effects import OutboxRepository


NOW = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)
STAMP = NOW.isoformat(timespec="microseconds")


class RecoveryRestoreRegressionTests(unittest.TestCase):
    def _db(self, path: Path) -> Database:
        db = Database(path)
        apply_migrations(db)
        return db

    def _seed_pending_nonreplayable_effect(self, db: Database) -> None:
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO effects(
                       effect_id,identity_id,intent_id,purpose_id,actor_id,action_class,
                       idempotency_key,replayable,dispatch_state,request_json,receipt_id,
                       verifier_state,created_at,updated_at,authorization_decision_id,
                       purpose_revision,purpose_occurrence_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "effect-1", "fish-1", "intent-1", None, "actor-1", "notify",
                    None, 0, "QUEUED", '{"text":"once"}', None, None,
                    STAMP, STAMP, "auth-1", None, None,
                ),
            )
            conn.execute(
                """INSERT INTO outbox(
                       outbox_id,identity_id,effect_id,destination,payload_json,state,
                       attempt_count,next_attempt_at,created_at,updated_at
                   ) VALUES(?,?,?,?,?,'PENDING',0,NULL,?,?)""",
                (
                    "outbox-1", "fish-1", "effect-1", "desktop",
                    '{"text":"once"}', STAMP, STAMP,
                ),
            )

    def _seed_runtime_context(self, db: Database) -> None:
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO canonical_events(
                       event_id,identity_id,turn_id,event_type,surface,source_type,
                       principal_id,audience_scope,context_space,trust_class,taint_json,
                       eligible_for_memory,payload_type,payload_json,observed_at,
                       recorded_at,correlation_id,schema_version,source_namespace,
                       source_event_key,semantic_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "evt-purpose",
                    "fish-1",
                    None,
                    "purpose.created",
                    "desktop",
                    "text",
                    "owner",
                    "PRIVATE",
                    "PERSONAL",
                    "OWNER_DIRECT",
                    "[]",
                    0,
                    "application/json",
                    "{}",
                    STAMP,
                    STAMP,
                    "corr-purpose",
                    1,
                    "test",
                    "purpose-source",
                    "sha256:test",
                ),
            )
            conn.execute(
                """INSERT INTO purposes(
                       purpose_id,identity_id,owner_type,owner_id,state,kind,
                       source_event_id,payload_json,scheduled_wall_time,timezone,
                       resolved_utc_time,miss_policy,created_at,updated_at,
                       last_evaluated_at,quiet_class,duplicate_key,revision
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "purpose-1",
                    "fish-1",
                    "USER",
                    "owner",
                    "SCHEDULED",
                    "REMINDER",
                    "evt-purpose",
                    "{}",
                    "2026-11-18T09:00:00",
                    "UTC",
                    STAMP,
                    "RECONCILE",
                    STAMP,
                    STAMP,
                    None,
                    "NORMAL",
                    "dup-1",
                    1,
                ),
            )
            conn.execute(
                """INSERT INTO delegations(
                       delegation_id,identity_id,principal_id,actor_id,purpose_id,
                       scope_json,valid_from,expires_at,revoked_at,
                       delegation_digest,revocable
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "delegation-1",
                    "fish-1",
                    "owner",
                    "actor-1",
                    "purpose-1",
                    "{}",
                    STAMP,
                    None,
                    None,
                    "sha256:delegation",
                    1,
                ),
            )
            conn.execute(
                """INSERT INTO authorization_decisions(
                       decision_id,identity_id,principal_id,actor_id,purpose_id,
                       action_class,resource_json,decision,reason_code,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    "auth-runtime",
                    "fish-1",
                    "owner",
                    "actor-1",
                    "purpose-1",
                    "notify",
                    "{}",
                    "ALLOW",
                    "TEST",
                    STAMP,
                ),
            )
            conn.execute(
                """INSERT INTO execution_authorizations(
                       authorization_decision_id,identity_id,principal_id,
                       principal_expires_at,actor_id,actor_implementation_digest,
                       actor_authorization_digest,delegation_id,purpose_id,
                       action_class,action_digest,resource_digest,context_digest,
                       request_digest,destination,audience_scope,context_space,
                       created_at,purpose_revision,purpose_occurrence_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "auth-runtime",
                    "fish-1",
                    "owner",
                    None,
                    "actor-1",
                    "sha256:impl",
                    "sha256:auth",
                    "delegation-1",
                    "purpose-1",
                    "notify",
                    "sha256:action",
                    "sha256:resource",
                    "sha256:context",
                    "sha256:request",
                    "desktop",
                    "PRIVATE",
                    "PERSONAL",
                    STAMP,
                    1,
                    "occurrence-1",
                ),
            )
            conn.execute(
                """INSERT INTO purpose_occurrences(
                       occurrence_id,identity_id,purpose_id,purpose_revision,
                       scheduled_for_utc,state,effect_id,activated_at,updated_at
                   ) VALUES(?,?,?,?,?,'READY',NULL,?,?)""",
                (
                    "occurrence-1",
                    "fish-1",
                    "purpose-1",
                    1,
                    STAMP,
                    STAMP,
                    STAMP,
                ),
            )
            conn.execute(
                """INSERT INTO deliveries(
                       delivery_id,identity_id,logical_notification_id,purpose_id,
                       surface,state,attempt_count,external_ref,created_at,updated_at
                   ) VALUES(?,?,?,?,?,'PENDING',0,NULL,?,?)""",
                (
                    "delivery-1",
                    "fish-1",
                    "logical-1",
                    "purpose-1",
                    "desktop",
                    STAMP,
                    STAMP,
                ),
            )

    def _seed_fact(self, db: Database) -> None:
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO claims(
                       claim_id,identity_id,subject,predicate,object_json,trust_class,
                       confidence,status,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "claim-secret", "fish-1", "owner", "secret_pref", '"A"',
                    "OWNER_DIRECT", 1.0, "CONFIRMED", STAMP,
                ),
            )
            conn.execute(
                """INSERT INTO temporal_facts(
                       fact_id,identity_id,claim_id,subject,predicate,value_json,
                       valid_from,valid_to,recorded_at,status,supersedes_fact_id,
                       fact_key,principal_scope,context_space,cardinality,revision,mutation_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "fact-row-1", "fish-1", "claim-secret", "owner", "secret_pref", '"A"',
                    STAMP, None, STAMP, "CURRENT", None, "fact:secret", "owner",
                    "PERSONAL", "SINGLE", 1, "mut-secret-1",
                ),
            )
            conn.execute(
                """INSERT INTO fact_authority_revisions(
                       identity_id,fact_key,current_revision,last_source_ingest_revision,
                       erasure_generation,updated_at
                   ) VALUES(?,?,?,?,?,?)""",
                ("fish-1", "fact:secret", 1, 1, 0, STAMP),
            )

    def test_old_snapshot_pending_nonreplayable_effect_is_quarantined(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            self._seed_pending_nonreplayable_effect(active)
            ExternalErasureFenceStore(active.path).ensure_identity("fish-1")

            snapshot = active.backup_to(root / "old.sqlite3")

            # Original database has already consumed the effect.
            with active.transaction(immediate=True) as conn:
                conn.execute("UPDATE outbox SET state='SUCCEEDED' WHERE outbox_id='outbox-1'")
                conn.execute("UPDATE effects SET dispatch_state='SUCCEEDED' WHERE effect_id='effect-1'")

            RecoveryManager.restore(
                candidate_path=snapshot,
                target_path=active.path,
                identity_id="fish-1",
                mode=RestoreMode.MANAGED,
            )

            restored = Database(active.path)
            with restored.transaction(immediate=True) as conn:
                claimed = OutboxRepository().claim_due(conn, NOW, 20)
                effect_state = conn.execute(
                    "SELECT dispatch_state FROM effects WHERE effect_id='effect-1'"
                ).fetchone()[0]
                outbox_state = conn.execute(
                    "SELECT state FROM outbox WHERE outbox_id='outbox-1'"
                ).fetchone()[0]

            self.assertEqual(claimed, [])
            self.assertEqual(effect_state, "NEEDS_RECONCILIATION")
            self.assertEqual(outbox_state, "NEEDS_RECONCILIATION")

    def test_restore_quarantines_purpose_delivery_delegation_and_auth_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            self._seed_runtime_context(active)
            ExternalErasureFenceStore(active.path).ensure_identity("fish-1")
            snapshot = active.backup_to(root / "old.sqlite3")

            report = RecoveryManager.restore(
                candidate_path=snapshot,
                target_path=active.path,
                identity_id="fish-1",
                mode=RestoreMode.MANAGED,
            )
            self.assertEqual(report.revoked_delegations, 1)
            self.assertEqual(report.invalidated_execution_authorizations, 1)
            self.assertEqual(report.quarantined_purposes, 1)
            self.assertEqual(report.quarantined_occurrences, 1)
            self.assertEqual(report.quarantined_deliveries, 1)

            restored = Database(active.path)
            with restored.transaction() as conn:
                purpose = conn.execute(
                    "SELECT state FROM purposes WHERE purpose_id='purpose-1'"
                ).fetchone()[0]
                occurrence = conn.execute(
                    """SELECT state FROM purpose_occurrences
                       WHERE occurrence_id='occurrence-1'"""
                ).fetchone()[0]
                delivery = conn.execute(
                    "SELECT state FROM deliveries WHERE delivery_id='delivery-1'"
                ).fetchone()[0]
                revoked = conn.execute(
                    """SELECT revoked_at FROM delegations
                       WHERE delegation_id='delegation-1'"""
                ).fetchone()[0]
                auth_count = conn.execute(
                    """SELECT COUNT(*) FROM execution_authorizations
                       WHERE identity_id='fish-1'"""
                ).fetchone()[0]
            self.assertEqual(purpose, "NEEDS_RECONCILIATION")
            self.assertEqual(occurrence, "NEEDS_RECONCILIATION")
            self.assertEqual(delivery, "NEEDS_RECONCILIATION")
            self.assertIsNotNone(revoked)
            self.assertEqual(auth_count, 0)

    def test_old_snapshot_cannot_resurrect_fact_deleted_after_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            self._seed_fact(active)
            fence = ExternalErasureFenceStore(active.path)
            fence.ensure_identity("fish-1")
            snapshot = active.backup_to(root / "old.sqlite3")

            fence.record_fact_delete(
                identity_id="fish-1",
                fact_key="fact:secret",
                generation=1,
                source_event_id="evt-delete",
                source_ingest_revision=2,
                mutation_id="mut-delete",
                requested_at=STAMP,
            )
            with active.transaction(immediate=True) as conn:
                conn.execute(
                    "UPDATE temporal_facts SET status='DELETED' WHERE fact_key='fact:secret'"
                )

            RecoveryManager.restore(
                candidate_path=snapshot,
                target_path=active.path,
                identity_id="fish-1",
                mode=RestoreMode.MANAGED,
            )

            restored = Database(active.path)
            with restored.transaction() as conn:
                row = conn.execute(
                    "SELECT status FROM temporal_facts WHERE fact_key='fact:secret'"
                ).fetchone()
                tombstone = conn.execute(
                    """SELECT erasure_generation FROM erasure_tombstones
                       WHERE identity_id='fish-1' AND target_id='fact:secret'"""
                ).fetchone()
                claim = conn.execute(
                    "SELECT status FROM claims WHERE claim_id='claim-secret'"
                ).fetchone()
            self.assertEqual(row[0], "DELETED")
            self.assertEqual(tombstone[0], 1)
            self.assertEqual(claim[0], "ERASED")

    def test_restore_preserves_fact_reintroduced_after_latest_erasure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            self._seed_fact(active)
            fence = ExternalErasureFenceStore(active.path)
            fence.ensure_identity("fish-1")
            fence.record_fact_delete(
                identity_id="fish-1",
                fact_key="fact:secret",
                generation=1,
                source_event_id="evt-delete",
                source_ingest_revision=2,
                mutation_id="mut-delete",
                requested_at=STAMP,
                result_revision=2,
            )
            with active.transaction(immediate=True) as conn:
                conn.execute(
                    "UPDATE temporal_facts SET status='DELETED' WHERE fact_key='fact:secret'"
                )
                conn.execute(
                    "UPDATE claims SET status='ERASED' WHERE claim_id='claim-secret'"
                )
                conn.execute(
                    """INSERT INTO claims(
                           claim_id,identity_id,subject,predicate,object_json,
                           trust_class,confidence,status,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        "claim-new",
                        "fish-1",
                        "owner",
                        "secret_pref",
                        '"B"',
                        "OWNER_DIRECT",
                        1.0,
                        "CONFIRMED",
                        STAMP,
                    ),
                )
                conn.execute(
                    """INSERT INTO temporal_facts(
                           fact_id,identity_id,claim_id,subject,predicate,value_json,
                           valid_from,valid_to,recorded_at,status,supersedes_fact_id,
                           fact_key,principal_scope,context_space,cardinality,
                           revision,mutation_id
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "fact-row-2",
                        "fish-1",
                        "claim-new",
                        "owner",
                        "secret_pref",
                        '"B"',
                        STAMP,
                        None,
                        STAMP,
                        "CURRENT",
                        "fact-row-1",
                        "fact:secret",
                        "owner",
                        "PERSONAL",
                        "SINGLE",
                        3,
                        "mut-reintroduce",
                    ),
                )
                conn.execute(
                    """UPDATE fact_authority_revisions
                       SET current_revision=3,last_source_ingest_revision=3,
                           erasure_generation=1
                       WHERE identity_id='fish-1' AND fact_key='fact:secret'"""
                )
                conn.execute(
                    """INSERT INTO erasure_tombstones(
                           erasure_id,identity_id,target_type,target_id,
                           erasure_generation,requested_at,applied_at,
                           source_event_id,source_ingest_revision,mutation_id
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "erasure:mut-delete",
                        "fish-1",
                        "fact_key",
                        "fact:secret",
                        1,
                        STAMP,
                        STAMP,
                        "evt-delete",
                        2,
                        "mut-delete",
                    ),
                )

            snapshot = active.backup_to(root / "post-reintroduce.sqlite3")
            RecoveryManager.restore(
                candidate_path=snapshot,
                target_path=active.path,
                identity_id="fish-1",
                mode=RestoreMode.MANAGED,
            )

            restored = Database(active.path)
            with restored.transaction() as conn:
                current = conn.execute(
                    """SELECT value_json,status FROM temporal_facts
                       WHERE identity_id='fish-1' AND fact_key='fact:secret'
                         AND status='CURRENT'"""
                ).fetchone()
                claim = conn.execute(
                    "SELECT status FROM claims WHERE claim_id='claim-new'"
                ).fetchone()
            self.assertEqual(json.loads(current["value_json"]), "B")
            self.assertEqual(current["status"], "CURRENT")
            self.assertEqual(claim[0], "CONFIRMED")

    def test_restore_rebuilds_projection_from_canonical_fact_not_old_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            self._seed_fact(active)
            ExternalErasureFenceStore(active.path).ensure_identity("fish-1")
            with active.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO projections(
                           identity_id,projection_key,projection_type,value_json,
                           source_fact_ids_json,builder_version,built_at,
                           source_revision,erasure_generation
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        "fish-1",
                        "poisoned-summary",
                        "PROFILE_SUMMARY",
                        '{"secret_pref":"WRONG"}',
                        "[]",
                        "old-summary",
                        STAMP,
                        0,
                        0,
                    ),
                )
            snapshot = active.backup_to(root / "old.sqlite3")

            report = RecoveryManager.restore(
                candidate_path=snapshot,
                target_path=active.path,
                identity_id="fish-1",
                mode=RestoreMode.MANAGED,
            )
            self.assertEqual(report.cleared_projections, 1)
            self.assertEqual(report.rebuilt_projections, 1)

            restored = Database(active.path)
            with restored.transaction() as conn:
                rows = conn.execute(
                    """SELECT projection_key,projection_type,value_json,
                              builder_version,source_revision,erasure_generation
                       FROM projections WHERE identity_id='fish-1'"""
                ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["projection_key"], "fact:secret")
            self.assertEqual(rows[0]["projection_type"], "CURRENT_FACT")
            self.assertEqual(rows[0]["builder_version"], "recovery-current-fact-v1")
            self.assertEqual(json.loads(rows[0]["value_json"])["values"], ["A"])

    def test_restore_does_not_mutate_managed_backup_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            ExternalErasureFenceStore(source.path).ensure_identity("fish-1")
            backup = RecoveryManager.create_backup(
                source_path=source.path,
                backup_path=root / "managed.sqlite3",
                identity_id="fish-1",
                release_version="test",
                release_digest="sha256:test",
            )
            before_db = backup.read_bytes()
            before_manifest = Path(
                str(backup) + ".manifest.json"
            ).read_bytes()

            RecoveryManager.restore(
                candidate_path=backup,
                target_path=root / "portable-home.sqlite3",
                identity_id="fish-1",
                mode=RestoreMode.PORTABLE_IMPORT,
            )

            self.assertEqual(backup.read_bytes(), before_db)
            self.assertEqual(
                Path(str(backup) + ".manifest.json").read_bytes(),
                before_manifest,
            )
            self.assertIsNotNone(
                RecoveryManager.validate_backup_manifest(
                    backup, expected_identity_id="fish-1"
                )
            )

    def test_portable_import_migrates_old_v5_snapshot_before_activation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = Database(root / "v5.sqlite3")
            self.assertEqual(
                apply_migrations(candidate, target_version=5),
                [1, 2, 3, 4, 5],
            )
            ExternalErasureFenceStore(candidate.path).ensure_identity("fish-1")
            target = root / "new-home.sqlite3"

            RecoveryManager.restore(
                candidate_path=candidate.path,
                target_path=target,
                identity_id="fish-1",
                mode=RestoreMode.PORTABLE_IMPORT,
            )
            self.assertEqual(
                applied_versions(Database(target)),
                [1, 2, 3, 4, 5, 6, 7],
            )

    def test_managed_restore_with_corrupt_watermark_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            fence = ExternalErasureFenceStore(active.path)
            fence.ensure_identity("fish-1")
            snapshot = active.backup_to(root / "old.sqlite3")
            fence.path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(ErasureWatermarkError):
                RecoveryManager.restore(
                    candidate_path=snapshot,
                    target_path=active.path,
                    identity_id="fish-1",
                    mode=RestoreMode.MANAGED,
                )

    def test_managed_restore_without_trusted_watermark_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = self._db(root / "identity.sqlite3")
            self._seed_fact(active)
            snapshot = active.backup_to(root / "old.sqlite3")

            with self.assertRaises(MissingErasureWatermark):
                RecoveryManager.restore(
                    candidate_path=snapshot,
                    target_path=active.path,
                    identity_id="fish-1",
                    mode=RestoreMode.MANAGED,
                )


if __name__ == "__main__":
    unittest.main()
