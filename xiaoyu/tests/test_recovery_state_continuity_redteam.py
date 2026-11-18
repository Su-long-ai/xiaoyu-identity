from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.core.memory import CanonicalMemoryService
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.erasure import ExternalErasureFenceStore
from xiaoyu.persistence.recovery import (
    BackupError,
    RecoveryManager,
    RestoreInvariantError,
    RestoreMode,
)
from xiaoyu.runtime.product_store import CanonicalProductStore


UTC=timezone.utc
T0=datetime(2026,11,18,15,0,tzinfo=UTC)


class RecoveryStateContinuityRedTeamTests(unittest.TestCase):
    def _seed_memory(self, root: Path):
        db=Database(root/"identity.sqlite3")
        store=CanonicalProductStore(db,identity_id="fish-state")
        source=store.record_user_turn(
            source_event_key="memory-save",
            text="记住：我喜欢乌龙茶",
            observed_at=T0,
        )
        item=store.save_memory(
            memory_id="drink",
            mutation_id="memory-save",
            source_event_id=source.event_id,
            principal_id="owner",
            text="我喜欢乌龙茶",
            category="preference",
            priority=5,
            created_at=T0,
        )
        backup=root/"managed-old.sqlite3"
        RecoveryManager.create_backup(
            source_path=db.path,
            backup_path=backup,
            identity_id="fish-state",
            release_version="r20-redteam",
            release_digest="sha256:r20-redteam",
            created_at=T0+timedelta(seconds=1),
        )
        return db,store,item,backup

    def _reject_old_restore(self, db: Database, backup: Path):
        with self.assertRaisesRegex(
            RestoreInvariantError,
            "predates active authority",
        ):
            RecoveryManager.restore(
                candidate_path=backup,
                target_path=db.path,
                identity_id="fish-state",
                mode=RestoreMode.MANAGED,
                activated_at=T0+timedelta(minutes=10),
            )
        return CanonicalMemoryService(Database(db.path))

    def test_old_managed_snapshot_cannot_overwrite_newer_correction(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,item,backup=self._seed_memory(root)
            correction=store.record_user_turn(
                source_event_key="memory-correct",
                text="更正：我现在喜欢咖啡",
                observed_at=T0+timedelta(minutes=1),
            )
            corrected=store.correct_memory(
                memory_id="drink",
                mutation_id="memory-correct",
                source_event_id=correction.event_id,
                principal_id="owner",
                expected_revision=item.revision,
                text="我现在喜欢咖啡",
                category="preference",
                priority=5,
                created_at=T0+timedelta(minutes=1),
            )
            self.assertEqual(corrected.text,"我现在喜欢咖啡")

            restored=self._reject_old_restore(db,backup)
            current=restored.get("drink")
            self.assertEqual(
                current.text,
                "我现在喜欢咖啡",
                "restore rolled canonical truth back to pre-correction snapshot",
            )
            self.assertGreaterEqual(current.revision,corrected.revision)

    def test_old_managed_snapshot_cannot_reactivate_retracted_memory(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,item,backup=self._seed_memory(root)
            retract=store.record_user_turn(
                source_event_key="memory-retract",
                text="撤回这条记忆",
                observed_at=T0+timedelta(minutes=1),
            )
            store.retract_memory(
                memory_id="drink",
                mutation_id="memory-retract",
                source_event_id=retract.event_id,
                principal_id="owner",
                expected_revision=item.revision,
                created_at=T0+timedelta(minutes=1),
            )
            with self.assertRaises(KeyError):
                store.memory.get("drink")

            restored=self._reject_old_restore(db,backup)
            with self.assertRaises(
                KeyError,
                msg="restore reactivated memory that had been retracted after snapshot",
            ):
                restored.get("drink")

    def test_old_managed_snapshot_cannot_undo_newer_priority_control(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,item,backup=self._seed_memory(root)
            control=store.record_user_turn(
                source_event_key="memory-priority",
                text="把这条记忆降为低优先级",
                observed_at=T0+timedelta(minutes=1),
            )
            changed=store.correct_memory(
                memory_id="drink",
                mutation_id="memory-priority",
                source_event_id=control.event_id,
                principal_id="owner",
                expected_revision=item.revision,
                text=item.text,
                category=item.category,
                priority=1,
                created_at=T0+timedelta(minutes=1),
            )
            self.assertEqual(changed.priority,1)

            restored=self._reject_old_restore(db,backup)
            current=restored.get("drink")
            self.assertEqual(
                current.priority,
                1,
                "restore rolled newer memory-control priority back to old snapshot",
            )


    def test_managed_restore_rejects_manifestless_raw_sqlite_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            store=CanonicalProductStore(db,identity_id="fish-state")
            source=store.record_user_turn(
                source_event_key="raw-save",
                text="记住裸快照测试",
                observed_at=T0,
            )
            store.save_memory(
                memory_id="raw",
                mutation_id="raw-save",
                source_event_id=source.event_id,
                principal_id="owner",
                text="裸快照不能直接恢复",
                category="other",
                priority=3,
                created_at=T0,
            )
            ExternalErasureFenceStore(db.path).ensure_identity("fish-state")
            raw=db.backup_to(root/"legacy-raw.sqlite3")
            self.assertFalse(
                Path(str(raw)+".manifest.json").exists()
            )

            with self.assertRaises(
                BackupError,
                msg=(
                    "managed restore accepted a raw SQLite snapshot "
                    "without backup provenance/migration metadata"
                ),
            ):
                RecoveryManager.restore(
                    candidate_path=raw,
                    target_path=db.path,
                    identity_id="fish-state",
                    mode=RestoreMode.MANAGED,
                    activated_at=T0+timedelta(minutes=1),
                )


    def test_restore_quarantines_attempting_delivery_parent_and_dispatching_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            apply_migrations(db)
            stamp=T0.isoformat(timespec="microseconds")
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO effects(
                           effect_id,identity_id,intent_id,purpose_id,actor_id,
                           action_class,idempotency_key,replayable,dispatch_state,
                           request_json,receipt_id,verifier_state,created_at,
                           updated_at,authorization_decision_id,purpose_revision,
                           purpose_occurrence_id
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "effect-delivery","fish-exec","intent-delivery",None,
                        "actor-1","notify",None,0,"DISPATCHING",
                        '{"text":"once"}',None,None,stamp,stamp,
                        "auth-delivery",None,None,
                    ),
                )
                conn.execute(
                    """INSERT INTO outbox(
                           outbox_id,identity_id,effect_id,destination,
                           payload_json,state,attempt_count,next_attempt_at,
                           created_at,updated_at
                       ) VALUES(?,?,?,?,?,'DISPATCHING',1,NULL,?,?)""",
                    (
                        "outbox-delivery","fish-exec","effect-delivery",
                        "desktop",'{"text":"once"}',stamp,stamp,
                    ),
                )
                conn.execute(
                    """INSERT INTO deliveries(
                           delivery_id,identity_id,logical_notification_id,
                           purpose_id,surface,state,attempt_count,external_ref,
                           created_at,updated_at
                       ) VALUES(?,?,?,?,?,'ATTEMPTING',1,NULL,?,?)""",
                    (
                        "delivery-1","fish-exec","logical-1",None,
                        "desktop",stamp,stamp,
                    ),
                )
                conn.execute(
                    """INSERT INTO delivery_attempts(
                           attempt_id,identity_id,delivery_id,
                           logical_notification_id,effect_id,surface,state,
                           external_ref,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,'DISPATCHING',NULL,?,?)""",
                    (
                        "attempt-1","fish-exec","delivery-1","logical-1",
                        "effect-delivery","desktop",stamp,stamp,
                    ),
                )

            backup=RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=root/"pending-work.sqlite3",
                identity_id="fish-exec",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0+timedelta(seconds=1),
            )
            report=RecoveryManager.restore(
                candidate_path=backup,
                target_path=db.path,
                identity_id="fish-exec",
                mode=RestoreMode.MANAGED,
                activated_at=T0+timedelta(minutes=1),
            )
            restored=Database(db.path)
            with restored.transaction() as conn:
                delivery=conn.execute(
                    "SELECT state FROM deliveries WHERE delivery_id='delivery-1'"
                ).fetchone()[0]
                attempt=conn.execute(
                    "SELECT state FROM delivery_attempts WHERE attempt_id='attempt-1'"
                ).fetchone()[0]
                effect=conn.execute(
                    "SELECT dispatch_state FROM effects WHERE effect_id='effect-delivery'"
                ).fetchone()[0]
                outbox=conn.execute(
                    "SELECT state FROM outbox WHERE outbox_id='outbox-delivery'"
                ).fetchone()[0]
            self.assertEqual(attempt,"NEEDS_RECONCILIATION")
            self.assertEqual(effect,"NEEDS_RECONCILIATION")
            self.assertEqual(outbox,"NEEDS_RECONCILIATION")
            self.assertEqual(
                delivery,
                "NEEDS_RECONCILIATION",
                "restore left a non-terminal delivery parent in ATTEMPTING",
            )
            self.assertEqual(report.quarantined_deliveries,1)


    def test_restore_cannot_lose_mutation_committed_after_backup_with_preexisting_source_event(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            store=CanonicalProductStore(db,identity_id="fish-state")
            save_event=store.record_user_turn(
                source_event_key="txn-gap-save",
                text="记住我喜欢乌龙茶",
                observed_at=T0,
            )
            saved=store.save_memory(
                memory_id="txn-gap",
                mutation_id="txn-gap-save",
                source_event_id=save_event.event_id,
                principal_id="owner",
                text="我喜欢乌龙茶",
                category="preference",
                priority=5,
                created_at=T0,
            )
            # The owner edit event is durable before its authoritative mutation.
            # A crash/backup may land exactly in this transaction gap.
            correction_event=store.record_user_turn(
                source_event_key="txn-gap-correct-event",
                text="更正：我喜欢咖啡",
                observed_at=T0+timedelta(minutes=1),
            )
            backup=RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=root/"txn-gap-old.sqlite3",
                identity_id="fish-state",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0+timedelta(minutes=1,seconds=1),
            )
            manifest=RecoveryManager.validate_backup_manifest(
                backup,expected_identity_id="fish-state"
            )
            candidate_source_revision=int(
                manifest["source_revision_watermark"]
            )

            corrected=store.correct_memory(
                memory_id="txn-gap",
                mutation_id="txn-gap-correct",
                source_event_id=correction_event.event_id,
                principal_id="owner",
                expected_revision=saved.revision,
                text="我喜欢咖啡",
                category="preference",
                priority=5,
                created_at=T0+timedelta(minutes=2),
            )
            self.assertEqual(corrected.text,"我喜欢咖啡")
            with db.transaction() as conn:
                active_source_revision=int(
                    conn.execute(
                        """SELECT COALESCE(MAX(ingest_revision),0)
                           FROM canonical_event_ingest
                           WHERE identity_id='fish-state'"""
                    ).fetchone()[0]
                )
            self.assertEqual(
                active_source_revision,
                candidate_source_revision,
                "test requires mutation to advance without a new source event",
            )

            with self.assertRaisesRegex(
                RestoreInvariantError,
                "predates active fact authority",
            ):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=db.path,
                    identity_id="fish-state",
                    mode=RestoreMode.MANAGED,
                    activated_at=T0+timedelta(minutes=3),
                )
            current=CanonicalMemoryService(Database(db.path)).get("txn-gap")
            self.assertEqual(
                current.text,
                "我喜欢咖啡",
                "restore lost a committed authority mutation hidden behind an unchanged source watermark",
            )


if __name__=="__main__":
    unittest.main()
