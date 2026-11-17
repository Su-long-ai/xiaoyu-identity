from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from identity_core import IdentityStore
from xiaoyu.core.authorization import AuthorizationResult
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus, EffectCoordinator
from xiaoyu.contracts import AuthorizationDecision
from xiaoyu.persistence import Database
from xiaoyu.release.restore import ManagedRestoreError, managed_restore
from xiaoyu.runtime import OutboxDispatcher
from xiaoyu.tests.test_effect_outbox import (
    NOW,
    action,
    actor,
    context,
    delegation,
    effect,
    principal,
    resource,
)


class ManagedRestoreRedTeamTests(unittest.TestCase):
    def _enqueue_pending(self, store):
        db=Database(store.db_path)
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-restore",
            outbox_id="outbox-restore",
            identity_id=store.persona()["id"],
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=action(),
            resource=resource(),
            context=context(),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                "del-1",
            ),
            effect=effect(),
            destination="qq",
            payload=effect().request,
            created_at=NOW,
        )
        return db

    def test_restore_of_pre_send_snapshot_does_not_replay_pending_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            live=IdentityStore(
                root/"live",
                enable_v1_shadow=True,
            )
            try:
                db=self._enqueue_pending(live)
                archive=live.export(root/"pending.zip")
                calls=[]

                def send(payload,key):
                    calls.append("sent")
                    return DispatchOutcome(
                        DispatchStatus.SUCCEEDED,
                        external_ref=str(len(calls)),
                    )

                self.assertEqual(
                    OutboxDispatcher(
                        db,{"qq":send}
                    ).dispatch_once(now=NOW),
                    1,
                )
                self.assertEqual(calls,["sent"])

                report=managed_restore(
                    archive,
                    root/"live",
                    root/"restored",
                )
                restored_db=Database(
                    Path(report["home"])/"identity.sqlite3"
                )
                self.assertEqual(
                    OutboxDispatcher(
                        restored_db,{"qq":send}
                    ).dispatch_once(now=NOW),
                    0,
                )
                self.assertEqual(calls,["sent"])
                conn=restored_db.connect()
                try:
                    self.assertEqual(
                        conn.execute(
                            "SELECT dispatch_state FROM effects"
                        ).fetchone()[0],
                        "NEEDS_RECONCILIATION",
                    )
                    self.assertEqual(
                        conn.execute(
                            "SELECT state FROM outbox"
                        ).fetchone()[0],
                        "NEEDS_RECONCILIATION",
                    )
                finally:
                    conn.close()
            finally:
                live.close()

    def test_newer_live_erasure_fence_prevents_memory_resurrection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            live=IdentityStore(
                root/"live",
                enable_v1_shadow=True,
            )
            try:
                memory_id=live.add_memory(
                    "SYNTHETIC_ERASE_ME"
                )
                archive=live.export(
                    root/"before-delete.zip"
                )
                source=live.conn.execute(
                    "SELECT source_event FROM memories WHERE memory_id=?",
                    (memory_id,),
                ).fetchone()[0]
                identity_id=live.persona()["id"]
                at=datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                )
                with live.conn:
                    live.conn.execute(
                        "DELETE FROM memories WHERE memory_id=?",
                        (memory_id,),
                    )
                    live.conn.execute(
                        """INSERT INTO erasure_tombstones(
                               erasure_id,identity_id,target_type,target_id,
                               erasure_generation,requested_at,applied_at,
                               source_event_id,source_ingest_revision,mutation_id
                           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            "erase-memory-1",
                            identity_id,
                            "memory",
                            str(memory_id),
                            1,
                            at,
                            at,
                            "legacy:%s" % source,
                            None,
                            "managed-memory-delete",
                        ),
                    )

                report=managed_restore(
                    archive,
                    root/"live",
                    root/"restored",
                )
                self.assertEqual(
                    report["erasure_fences_applied"],
                    1,
                )
                restored=IdentityStore(
                    Path(report["home"])
                )
                try:
                    texts=[
                        row["text"]
                        for row in restored.list_memories()
                    ]
                    self.assertNotIn(
                        "SYNTHETIC_ERASE_ME",
                        texts,
                    )
                finally:
                    restored.close()
            finally:
                live.close()

    def test_managed_restore_refuses_missing_current_erasure_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            live=IdentityStore(root/"live")
            try:
                archive=live.export(root/"archive.zip")
                with self.assertRaises(ManagedRestoreError):
                    managed_restore(
                        archive,
                        root/"live",
                        root/"restored",
                    )
                self.assertFalse(
                    (root/"restored").exists()
                )
            finally:
                live.close()


if __name__=="__main__":
    unittest.main()
