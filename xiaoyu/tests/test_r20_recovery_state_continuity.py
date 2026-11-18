from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.core.memory import MemoryControlState
from xiaoyu.core.relationship import (
    RelationshipLifecycle,
    RelationshipService,
)
from xiaoyu.persistence import Database
from xiaoyu.persistence.erasure import ExternalErasureFenceStore
from xiaoyu.persistence.recovery import (
    RecoveryManager,
    RestoreInvariantError,
    RestoreMode,
)
from xiaoyu.runtime.product_controls import (
    MemoryControlService,
    ProductOffboardingService,
)
from xiaoyu.runtime.product_store import CanonicalProductStore


UTC=timezone.utc
T0=datetime(2026,11,18,16,0,tzinfo=UTC)


class R20RecoveryStateContinuityTests(unittest.TestCase):
    def _seed(self, root: Path):
        db=Database(root/"identity.sqlite3")
        store=CanonicalProductStore(db,identity_id="fish-r20-recovery")
        event=store.record_user_turn(
            source_event_key="seed",
            text="记住：我喜欢乌龙茶",
            observed_at=T0,
        )
        item=store.save_memory(
            memory_id="drink",
            mutation_id="seed",
            source_event_id=event.event_id,
            principal_id="owner",
            text="我喜欢乌龙茶",
            category="preference",
            priority=4,
            created_at=T0,
        )
        return db,store,MemoryControlService(store),item

    def _backup(self, db: Database, root: Path, name: str):
        return RecoveryManager.create_backup(
            source_path=db.path,
            backup_path=root/name,
            identity_id="fish-r20-recovery",
            release_version="r20-redteam",
            release_digest="sha256:r20-redteam",
            created_at=T0+timedelta(seconds=1),
        )

    def _assert_restore_rejected(self, db: Database, backup: Path):
        with self.assertRaises(RestoreInvariantError):
            RecoveryManager.restore(
                candidate_path=backup,
                target_path=db.path,
                identity_id="fish-r20-recovery",
                mode=RestoreMode.MANAGED,
                activated_at=T0+timedelta(minutes=10),
            )

    def test_old_snapshot_cannot_undo_pinned_low_or_muted(self):
        for index,state in enumerate((
            MemoryControlState.PINNED,
            MemoryControlState.LOW,
            MemoryControlState.MUTED,
        )):
            with self.subTest(state=state.value):
                with tempfile.TemporaryDirectory() as td:
                    root=Path(td)
                    db,store,controls,item=self._seed(root)
                    backup=self._backup(
                        db,root,"before-%s.sqlite3" % state.value.lower()
                    )
                    changed=controls.set_state(
                        memory_id="drink",
                        expected_revision=item.revision,
                        control_state=state,
                        source_event_key="set-"+state.value.lower(),
                        created_at=T0+timedelta(minutes=index+1),
                    )
                    self.assertEqual(changed.control_state,state)
                    self._assert_restore_rejected(db,backup)
                    current=store.memory.get("drink")
                    self.assertEqual(current.control_state,state)

    def test_old_pinned_snapshot_cannot_undo_newer_normal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,controls,item=self._seed(root)
            pinned=controls.set_state(
                memory_id="drink",
                expected_revision=item.revision,
                control_state=MemoryControlState.PINNED,
                source_event_key="pin",
                created_at=T0+timedelta(minutes=1),
            )
            backup=self._backup(db,root,"pinned.sqlite3")
            normal=controls.set_state(
                memory_id="drink",
                expected_revision=pinned.revision,
                control_state=MemoryControlState.NORMAL,
                source_event_key="normal",
                created_at=T0+timedelta(minutes=2),
            )
            self.assertEqual(normal.control_state,MemoryControlState.NORMAL)
            self._assert_restore_rejected(db,backup)
            self.assertEqual(
                store.memory.get("drink").control_state,
                MemoryControlState.NORMAL,
            )

    def test_old_active_snapshot_cannot_undo_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,controls,item=self._seed(root)
            backup=self._backup(db,root,"active.sqlite3")
            archived=controls.archive(
                memory_id="drink",
                expected_revision=item.revision,
                archived=True,
                source_event_key="archive",
                created_at=T0+timedelta(minutes=1),
            )
            self.assertTrue(archived.archived)
            self._assert_restore_rejected(db,backup)
            self.assertTrue(store.memory.get("drink").archived)

    def test_old_archived_snapshot_cannot_undo_unarchive(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,controls,item=self._seed(root)
            archived=controls.archive(
                memory_id="drink",
                expected_revision=item.revision,
                archived=True,
                source_event_key="archive",
                created_at=T0+timedelta(minutes=1),
            )
            backup=self._backup(db,root,"archived.sqlite3")
            active=controls.archive(
                memory_id="drink",
                expected_revision=archived.revision,
                archived=False,
                source_event_key="unarchive",
                created_at=T0+timedelta(minutes=2),
            )
            self.assertFalse(active.archived)
            self._assert_restore_rejected(db,backup)


    def test_disaster_recovery_old_snapshot_cannot_resurrect_muted_memory_as_normal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,controls,item=self._seed(root)
            backup=self._backup(db,root,"before-muted.sqlite3")

            muted=controls.set_state(
                memory_id="drink",
                expected_revision=item.revision,
                control_state=MemoryControlState.MUTED,
                source_event_key="mute-before-disk-loss",
                created_at=T0+timedelta(minutes=1),
            )
            self.assertEqual(muted.control_state,MemoryControlState.MUTED)

            # Simulate total loss of the active SQLite authority while its
            # independently stored latest fence survives.
            trusted=root/"latest-external-fence.json"
            ExternalErasureFenceStore(db.path).copy_to(
                ExternalErasureFenceStore(
                    root/"lost-active.sqlite3",
                    path=trusted,
                )
            )
            recovered=root/"recovered.sqlite3"
            with self.assertRaisesRegex(
                RestoreInvariantError,
                "owner-control generation does not match",
            ):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=recovered,
                    identity_id="fish-r20-recovery",
                    mode=RestoreMode.DISASTER_RECOVERY,
                    watermark_path=trusted,
                    activated_at=T0+timedelta(minutes=2),
                )
            self.assertFalse(
                recovered.exists(),
                "stale disaster snapshot must not be activated",
            )
            self.assertFalse(store.memory.get("drink").archived)


    def test_disaster_recovery_rejects_pre_archive_and_pre_unarchive_backups(self):
        for mode in ("archive","unarchive"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as td:
                    root=Path(td)
                    db,store,controls,item=self._seed(root)
                    if mode=="unarchive":
                        item=controls.archive(
                            memory_id="drink",
                            expected_revision=item.revision,
                            archived=True,
                            source_event_key="archive-before-backup",
                            created_at=T0+timedelta(minutes=1),
                        )
                    backup=self._backup(
                        db,root,"before-%s.sqlite3" % mode
                    )
                    changed=controls.archive(
                        memory_id="drink",
                        expected_revision=item.revision,
                        archived=(mode=="archive"),
                        source_event_key=mode+"-after-backup",
                        created_at=T0+timedelta(minutes=2),
                    )
                    self.assertEqual(
                        changed.archived,
                        mode=="archive",
                    )
                    trusted=root/"latest-fence.json"
                    ExternalErasureFenceStore(db.path).copy_to(
                        ExternalErasureFenceStore(
                            root/"lost.sqlite3",path=trusted
                        )
                    )
                    recovered=root/"recovered.sqlite3"
                    with self.assertRaisesRegex(
                        RestoreInvariantError,
                        "owner-control generation does not match",
                    ):
                        RecoveryManager.restore(
                            candidate_path=backup,
                            target_path=recovered,
                            identity_id="fish-r20-recovery",
                            mode=RestoreMode.DISASTER_RECOVERY,
                            watermark_path=trusted,
                            activated_at=T0+timedelta(minutes=3),
                        )
                    self.assertFalse(recovered.exists())


    def test_disaster_recovery_rejects_backup_before_r20_relationship_reset(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,controls,item=self._seed(root)
            relationships=RelationshipService(db)
            relation_event=store.record_owner_control(
                source_event_key="relationship-seed",
                event_type="relationship.owner_seed",
                payload={"state":"FAMILIAR"},
                observed_at=T0+timedelta(minutes=1),
            )
            familiar=relationships.transition(
                transition_id="rel-familiar",
                identity_id="fish-r20-recovery",
                principal_id="owner",
                expected_state=RelationshipLifecycle.NEW,
                to_state=RelationshipLifecycle.FAMILIAR,
                source_event_id=relation_event.event_id,
                reason="OWNER_SEED",
                value_patch={
                    "shared_history":["private-shared-history"],
                    "proactivity_policy":{"enabled":True},
                },
                created_at=T0+timedelta(minutes=1),
            )
            self.assertEqual(
                familiar.state,RelationshipLifecycle.FAMILIAR
            )
            backup=self._backup(
                db,root,"before-offboarding-reset.sqlite3"
            )

            report=ProductOffboardingService(store).execute(
                source_event_key="offboard-reset",
                reset_relationship=True,
                created_at=T0+timedelta(minutes=2),
            )
            self.assertEqual(
                report.relationship.state,
                RelationshipLifecycle.PAUSED,
            )
            trusted=root/"latest-offboarding-fence.json"
            ExternalErasureFenceStore(db.path).copy_to(
                ExternalErasureFenceStore(
                    root/"lost.sqlite3",path=trusted
                )
            )
            with self.assertRaisesRegex(
                RestoreInvariantError,
                "owner-control generation does not match",
            ):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=root/"recovered.sqlite3",
                    identity_id="fish-r20-recovery",
                    mode=RestoreMode.DISASTER_RECOVERY,
                    watermark_path=trusted,
                    activated_at=T0+timedelta(minutes=3),
                )


    def test_disaster_backup_cannot_capture_control_event_before_mutation_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db,store,controls,item=self._seed(root)

            # Reproduce the R20 event->mutation transaction gap explicitly:
            # the owner control event is durable, but the memory revision has
            # not committed yet.
            event=store.record_owner_control(
                source_event_key="gap-mute",
                event_type="memory.control_state",
                payload={
                    "memory_id":"drink",
                    "control_state":MemoryControlState.MUTED.value,
                },
                observed_at=T0+timedelta(minutes=1),
            )
            gap_backup=self._backup(
                db,root,"control-gap.sqlite3"
            )
            changed=store.memory.set_control_state(
                memory_id="drink",
                mutation_id="memory-control:gap-mute",
                source_event_id=event.event_id,
                principal_id="owner",
                expected_revision=item.revision,
                control_state=MemoryControlState.MUTED,
                created_at=T0+timedelta(minutes=2),
            )
            self.assertEqual(
                changed.control_state,MemoryControlState.MUTED
            )

            trusted=root/"gap-latest-fence.json"
            ExternalErasureFenceStore(db.path).copy_to(
                ExternalErasureFenceStore(
                    root/"lost.sqlite3",path=trusted
                )
            )
            recovered=root/"gap-recovered.sqlite3"
            with self.assertRaises(
                RestoreInvariantError,
                msg=(
                    "backup captured a control generation before its "
                    "authoritative mutation and was later accepted"
                ),
            ):
                RecoveryManager.restore(
                    candidate_path=gap_backup,
                    target_path=recovered,
                    identity_id="fish-r20-recovery",
                    mode=RestoreMode.DISASTER_RECOVERY,
                    watermark_path=trusted,
                    activated_at=T0+timedelta(minutes=3),
                )


if __name__=="__main__":
    unittest.main()
