from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.core.memory import CanonicalMemoryService
from xiaoyu.persistence import Database
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


if __name__=="__main__":
    unittest.main()
