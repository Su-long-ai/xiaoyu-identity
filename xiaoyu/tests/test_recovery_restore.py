from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.erasure import ExternalErasureFenceStore
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
            self.assertEqual(row[0], "DELETED")
            self.assertEqual(tombstone[0], 1)

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
