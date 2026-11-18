from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from xiaoyu.core.memory import CanonicalMemoryService
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.erasure import ExternalErasureFenceStore
from xiaoyu.persistence.recovery import (
    BackupError,
    RecoveryManager,
    RecoveryQuarantineStore,
    RestoreInvariantError,
    RestoreMode,
)
from xiaoyu.release.migration import (
    AuthorityCutoverController,
    AuthorityCutoverEvidence,
    AuthorityMode,
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


    def test_restore_cannot_lose_self_revision_committed_after_backup_with_preexisting_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            store=CanonicalProductStore(db,identity_id="fish-self")
            initial=store.self_authority.initialize(
                identity_id="fish-self",
                persona={
                    "name":"小鱼",
                    "identity_commitments":["诚实"],
                    "style":{"tone":"warm"},
                    "growth_notes":[],
                    "bond_description":"start",
                },
                created_at=T0,
                reason="bootstrap",
            )
            evidence=store.record_user_turn(
                source_event_key="self-revise-evidence",
                text="以后表达更直接一点",
                observed_at=T0+timedelta(minutes=1),
            )
            backup=RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=root/"self-gap-old.sqlite3",
                identity_id="fish-self",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0+timedelta(minutes=1,seconds=1),
            )
            revised=store.revise_persona(
                expected_revision=initial.persona_revision,
                persona={
                    **initial.persona,
                    "style":{"tone":"direct"},
                },
                reason="owner-approved",
                source_event_ids=(evidence.event_id,),
                principal_id="owner",
                created_at=T0+timedelta(minutes=2),
            )
            self.assertEqual(revised.persona_revision,2)
            self.assertEqual(revised.persona["style"]["tone"],"direct")

            with self.assertRaisesRegex(
                RestoreInvariantError,
                "conflicts with current canonical authority",
            ):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=db.path,
                    identity_id="fish-self",
                    mode=RestoreMode.MANAGED,
                    activated_at=T0+timedelta(minutes=3),
                )
            current=CanonicalProductStore(
                Database(db.path),identity_id="fish-self"
            ).self_authority.get("fish-self")
            self.assertEqual(
                current.persona_revision,
                2,
                "restore rolled SELF authority back across a preexisting-evidence transaction gap",
            )
            self.assertEqual(current.persona["style"]["tone"],"direct")


    def test_old_snapshot_cannot_roll_canonical_cutover_back_to_shadow(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            apply_migrations(db)
            backup=RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=root/"pre-cutover.sqlite3",
                identity_id="fish-cutover",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0,
            )
            controller=AuthorityCutoverController(db)
            ready=AuthorityCutoverEvidence(
                shadow_caught_up=True,
                rebuild_equal=True,
                unresolved_conflicts=0,
                erasure_generation_source=0,
                erasure_generation_shadow=0,
                source_order_ok=True,
                old_writer_fenced=False,
                canonical_read_path_ready=True,
                canonical_write_path_ready=True,
            )
            activated=controller.activate(
                identity_id="fish-cutover",
                evidence=ready,
                activated_at=T0+timedelta(minutes=1),
            )
            self.assertEqual(activated.mode,AuthorityMode.CANONICAL)

            with self.assertRaisesRegex(
                RestoreInvariantError,
                "conflicts with current canonical authority",
            ):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=db.path,
                    identity_id="fish-cutover",
                    mode=RestoreMode.MANAGED,
                    activated_at=T0+timedelta(minutes=2),
                )
            current=AuthorityCutoverController(
                Database(db.path)
            ).state("fish-cutover")
            self.assertEqual(
                current.mode,
                AuthorityMode.CANONICAL,
                "restore crossed the forward-only cutover boundary back to SHADOW",
            )


    def test_higher_event_watermark_does_not_authorize_divergent_backup_over_current_truth(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            active=Database(root/"active.sqlite3")
            store=CanonicalProductStore(active,identity_id="fish-diverge")
            initial=store.self_authority.initialize(
                identity_id="fish-diverge",
                persona={
                    "name":"小鱼",
                    "identity_commitments":["诚实"],
                    "style":{"tone":"warm"},
                    "growth_notes":[],
                    "bond_description":"start",
                },
                created_at=T0,
                reason="bootstrap",
            )
            evidence=store.record_user_turn(
                source_event_key="diverge-persona-evidence",
                text="以后更直接一点",
                observed_at=T0+timedelta(minutes=1),
            )
            ExternalErasureFenceStore(active.path).ensure_identity(
                "fish-diverge"
            )

            # Fork candidate before the persona mutation commits.
            candidate_db=Database(
                active.backup_to(root/"candidate-branch.sqlite3")
            )
            ExternalErasureFenceStore(candidate_db.path).ensure_identity(
                "fish-diverge"
            )
            candidate_store=CanonicalProductStore(
                candidate_db,identity_id="fish-diverge"
            )

            # Active truth advances without a new event.
            revised=store.revise_persona(
                expected_revision=initial.persona_revision,
                persona={
                    **initial.persona,
                    "style":{"tone":"direct"},
                },
                reason="owner-approved",
                source_event_ids=(evidence.event_id,),
                principal_id="owner",
                created_at=T0+timedelta(minutes=2),
            )
            self.assertEqual(revised.persona_revision,2)

            # Candidate branch gets a newer unrelated event, so its event
            # watermark is numerically higher despite missing the persona edit.
            candidate_store.record_user_turn(
                source_event_key="candidate-unrelated-newer-event",
                text="无关的新事件",
                observed_at=T0+timedelta(minutes=3),
            )
            backup=RecoveryManager.create_backup(
                source_path=candidate_db.path,
                backup_path=root/"divergent-newer.sqlite3",
                identity_id="fish-diverge",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0+timedelta(minutes=4),
            )

            with self.assertRaisesRegex(
                RestoreInvariantError,
                "conflicts with current canonical authority",
            ):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=active.path,
                    identity_id="fish-diverge",
                    mode=RestoreMode.MANAGED,
                    activated_at=T0+timedelta(minutes=5),
                )
            current=CanonicalProductStore(
                Database(active.path),identity_id="fish-diverge"
            ).self_authority.get("fish-diverge")
            self.assertEqual(
                current.persona_revision,
                2,
                "a higher event watermark overwrote divergent current authority",
            )
            self.assertEqual(current.persona["style"]["tone"],"direct")


    def test_backup_manifest_describes_snapshot_not_live_source_that_advances_after_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            store=CanonicalProductStore(db,identity_id="fish-backup-race")
            first=store.record_user_turn(
                source_event_key="backup-race-first",
                text="first",
                observed_at=T0,
            )
            store.save_memory(
                memory_id="race-memory",
                mutation_id="backup-race-save",
                source_event_id=first.event_id,
                principal_id="owner",
                text="first",
                category="other",
                priority=3,
                created_at=T0,
            )
            original=Database.backup_to
            injected={"done":False}

            def backup_then_advance(instance,destination):
                result=original(instance,destination)
                if (
                    not injected["done"]
                    and Path(instance.path)==Path(db.path)
                ):
                    injected["done"]=True
                    store.record_user_turn(
                        source_event_key="backup-race-late",
                        text="late live write",
                        observed_at=T0+timedelta(minutes=1),
                    )
                return result

            with mock.patch.object(
                Database,"backup_to",backup_then_advance
            ):
                backup=RecoveryManager.create_backup(
                    source_path=db.path,
                    backup_path=root/"race.sqlite3",
                    identity_id="fish-backup-race",
                    release_version="r20-redteam",
                    release_digest="sha256:r20-redteam",
                    created_at=T0+timedelta(minutes=2),
                )
            self.assertTrue(injected["done"])
            manifest=RecoveryManager.validate_backup_manifest(
                backup,expected_identity_id="fish-backup-race"
            )
            backup_db=Database(backup)
            with backup_db.transaction() as conn:
                snap_revision=int(
                    conn.execute(
                        """SELECT COALESCE(MAX(ingest_revision),0)
                           FROM canonical_event_ingest
                           WHERE identity_id='fish-backup-race'"""
                    ).fetchone()[0]
                )
            with db.transaction() as conn:
                live_revision=int(
                    conn.execute(
                        """SELECT COALESCE(MAX(ingest_revision),0)
                           FROM canonical_event_ingest
                           WHERE identity_id='fish-backup-race'"""
                    ).fetchone()[0]
                )
            self.assertGreater(live_revision,snap_revision)
            self.assertEqual(
                int(manifest["source_revision_watermark"]),
                snap_revision,
            )
            self.assertEqual(
                manifest["canonical_authority_digest"],
                RecoveryManager._canonical_authority_digest(
                    backup_db,"fish-backup-race"
                ),
            )


    def test_restore_discards_private_context_summary_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=Database(root/"identity.sqlite3")
            apply_migrations(db)
            ExternalErasureFenceStore(db.path).ensure_identity(
                "fish-derived"
            )
            stamp=T0.isoformat(timespec="microseconds")
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO context_summaries(
                           summary_id,identity_id,principal_scope,context_space,
                           audience_scope,fidelity_class,summary_text,
                           source_event_ids_json,source_digest,source_revision,
                           erasure_generation,builder_version,status,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "summary-private",
                        "fish-derived",
                        "owner",
                        "PERSONAL",
                        "PRIVATE",
                        "LOSSY_ALLOWED",
                        "DERIVED_PRIVATE_SECRET_MUST_NOT_SURVIVE_RESTORE",
                        "[]",
                        "sha256:derived-summary",
                        0,
                        0,
                        "r11.summary.v1",
                        "ACTIVE",
                        stamp,
                    ),
                )

            backup=RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=root/"derived-cache.sqlite3",
                identity_id="fish-derived",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0+timedelta(seconds=1),
            )
            RecoveryManager.restore(
                candidate_path=backup,
                target_path=db.path,
                identity_id="fish-derived",
                mode=RestoreMode.MANAGED,
                activated_at=T0+timedelta(minutes=1),
            )

            restored=Database(db.path)
            with restored.transaction() as conn:
                rows=conn.execute(
                    """SELECT summary_text FROM context_summaries
                       WHERE identity_id='fish-derived'"""
                ).fetchall()
            self.assertEqual(
                rows,
                [],
                "restore retained a rebuildable private-derived summary cache",
            )


    def test_restore_quarantines_legacy_unknown_effect_and_outbox_states(self):
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
                        "effect-unknown","fish-unknown","intent-unknown",None,
                        "actor-1","notify",None,0,"UNKNOWN",
                        '{"text":"maybe-sent"}',None,None,stamp,stamp,
                        "auth-unknown",None,None,
                    ),
                )
                conn.execute(
                    """INSERT INTO outbox(
                           outbox_id,identity_id,effect_id,destination,
                           payload_json,state,attempt_count,next_attempt_at,
                           created_at,updated_at
                       ) VALUES(?,?,?,?,?,'UNKNOWN',1,NULL,?,?)""",
                    (
                        "outbox-unknown","fish-unknown","effect-unknown",
                        "desktop",'{"text":"maybe-sent"}',stamp,stamp,
                    ),
                )
            ExternalErasureFenceStore(db.path).ensure_identity(
                "fish-unknown"
            )
            backup=RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=root/"unknown.sqlite3",
                identity_id="fish-unknown",
                release_version="r20-redteam",
                release_digest="sha256:r20-redteam",
                created_at=T0+timedelta(seconds=1),
            )
            report=RecoveryManager.restore(
                candidate_path=backup,
                target_path=db.path,
                identity_id="fish-unknown",
                mode=RestoreMode.MANAGED,
                activated_at=T0+timedelta(minutes=1),
            )
            restored=Database(db.path)
            with restored.transaction() as conn:
                effect=conn.execute(
                    """SELECT dispatch_state FROM effects
                       WHERE effect_id='effect-unknown'"""
                ).fetchone()[0]
                outbox=conn.execute(
                    """SELECT state FROM outbox
                       WHERE outbox_id='outbox-unknown'"""
                ).fetchone()[0]
            self.assertEqual(
                effect,
                "NEEDS_RECONCILIATION",
                "legacy UNKNOWN effect bypassed restore quarantine",
            )
            self.assertEqual(
                outbox,
                "NEEDS_RECONCILIATION",
                "legacy UNKNOWN outbox bypassed restore quarantine",
            )
            self.assertEqual(report.quarantined_effects,1)
            self.assertEqual(report.quarantined_outbox,1)


    def test_restore_sidecar_write_failure_cannot_partially_activate_new_db(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=Database(root/"candidate.sqlite3")
            active=Database(root/"active.sqlite3")
            apply_migrations(source)
            apply_migrations(active)
            with source.transaction(immediate=True) as conn:
                conn.execute(
                    "CREATE TABLE recovery_probe(value TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO recovery_probe(value) VALUES('candidate')"
                )
            with active.transaction(immediate=True) as conn:
                conn.execute(
                    "CREATE TABLE recovery_probe(value TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO recovery_probe(value) VALUES('active')"
                )

            source_fence=ExternalErasureFenceStore(source.path)
            source_fence.ensure_identity("fish-power")
            trusted=root/"trusted-erasure.json"
            source_fence.copy_to(
                ExternalErasureFenceStore(active.path,path=trusted)
            )
            raw=source.backup_to(root/"candidate-raw.sqlite3")

            original_write=ExternalErasureFenceStore._write
            def fail_target_write(store,payload):
                if Path(store.path)==Path(str(active.path)+".erasure-watermark.json"):
                    raise OSError("synthetic fence write failure")
                return original_write(store,payload)

            with mock.patch.object(
                ExternalErasureFenceStore,
                "_write",
                fail_target_write,
            ):
                with self.assertRaises(OSError):
                    RecoveryManager.restore(
                        candidate_path=raw,
                        target_path=active.path,
                        identity_id="fish-power",
                        mode=RestoreMode.DISASTER_RECOVERY,
                        watermark_path=trusted,
                        activated_at=T0+timedelta(minutes=20),
                    )

            after=Database(active.path)
            with after.transaction() as conn:
                value=str(
                    conn.execute(
                        "SELECT value FROM recovery_probe"
                    ).fetchone()[0]
                )
            self.assertEqual(
                value,
                "active",
                "restore reported failure after already replacing the active DB",
            )
            self.assertTrue(
                RecoveryQuarantineStore(active.path).is_active(),
                "failed restore must leave execution quarantine fail-closed",
            )


if __name__=="__main__":
    unittest.main()
