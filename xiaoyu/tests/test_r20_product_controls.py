from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import model_adapter

from xiaoyu.contracts import ProviderHealth
from xiaoyu.core.identity import SelfAuthorityService
from xiaoyu.core.memory import MemoryControlState, MemoryRetriever
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.core.relationship import (
    RelationshipLifecycle,
    RelationshipService,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.recovery import RecoveryManager
from xiaoyu.runtime.host import RuntimeHost
from xiaoyu.runtime.product_controls import (
    MemoryControlService,
    ProductOffboardingService,
    ProductOnboardingVerifier,
)
from xiaoyu.runtime.product_store import CanonicalProductStore
from xiaoyu.runtime.resource_broker import ResourceBroker, ResourceMode


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)


def _provider_config(name: str = "qwen") -> dict:
    spec = model_adapter.PROVIDERS[name]
    result = {
        "provider": name,
        "url": spec["url"],
        "model": spec["model"],
        "key_env": spec.get("key_env", ""),
        "fallbacks": [],
    }
    for key in (
        "key_file",
        "enable_thinking",
        "reasoning_effort",
        "data_boundary",
    ):
        if key in spec:
            result[key] = spec[key]
    return result


def _healthy() -> ProviderHealth:
    return ProviderHealth(
        liveness="UP",
        readiness="READY",
        capability_health={"chat.completion": "READY"},
        reason=None,
        since=T0,
        retry_after_ms=None,
        details={},
    )


class R20ProductControlsTests(unittest.TestCase):
    def _product(self, root: Path):
        db = Database(root / "identity.sqlite3")
        apply_migrations(db)
        SelfAuthorityService(db).initialize(
            identity_id="fish-r20",
            persona={
                "name": "小鱼",
                "identity_commitments": ["诚实", "保持身份连续"],
                "style": {"language": "zh-CN"},
                "growth_notes": [],
                "bond_description": "长期伙伴",
            },
            created_at=T0,
            reason="r20-test",
        )
        return db, CanonicalProductStore(db, identity_id="fish-r20")

    @staticmethod
    def _save_memory(
        store: CanonicalProductStore,
        *,
        key: str,
        memory_id: str,
        text: str,
        at: datetime,
    ):
        source = store.record_user_turn(
            source_event_key=key,
            text=text,
            observed_at=at,
        )
        return store.save_memory(
            memory_id=memory_id,
            mutation_id="save:" + key,
            source_event_id=source.event_id,
            principal_id="owner",
            text=text,
            category="preference",
            priority=4,
            created_at=at,
        )

    def test_memory_control_is_revisioned_and_muted_or_archived_is_not_retrieved(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._product(Path(td))
            first = self._save_memory(
                store,
                key="memory-coffee",
                memory_id="coffee",
                text="我更喜欢浅烘咖啡",
                at=T0,
            )
            controls = MemoryControlService(store)
            view = controls.inspect()[0]
            self.assertEqual(view.memory_id, "coffee")
            self.assertEqual(view.revision, first.revision)
            self.assertEqual(view.source_event_id, first.source_event_id)
            self.assertEqual(view.control_state, MemoryControlState.NORMAL)
            self.assertFalse(view.archived)

            muted = controls.set_state(
                memory_id="coffee",
                expected_revision=view.revision,
                control_state=MemoryControlState.MUTED,
                source_event_key="mute-coffee",
                created_at=T0 + timedelta(minutes=1),
            )
            self.assertEqual(muted.control_state, MemoryControlState.MUTED)
            self.assertEqual(muted.revision, 2)

            retrieved = MemoryRetriever(db).retrieve(
                identity_id="fish-r20",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="浅烘咖啡",
            )
            self.assertFalse(
                any(item.subject == "memory:coffee" for item in retrieved)
            )

            corrected = controls.correct(
                memory_id="coffee",
                expected_revision=muted.revision,
                text="我现在更喜欢中浅烘咖啡",
                category="preference",
                priority=5,
                source_event_key="correct-coffee",
                created_at=T0 + timedelta(minutes=2),
            )
            self.assertEqual(corrected.control_state, MemoryControlState.MUTED)
            self.assertFalse(corrected.archived)

            normal = controls.set_state(
                memory_id="coffee",
                expected_revision=corrected.revision,
                control_state=MemoryControlState.NORMAL,
                source_event_key="unmute-coffee",
                created_at=T0 + timedelta(minutes=3),
            )
            archived = controls.archive(
                memory_id="coffee",
                expected_revision=normal.revision,
                archived=True,
                source_event_key="archive-coffee",
                created_at=T0 + timedelta(minutes=4),
            )
            self.assertTrue(archived.archived)
            retrieved = MemoryRetriever(db).retrieve(
                identity_id="fish-r20",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="中浅烘咖啡",
            )
            self.assertFalse(
                any(item.subject == "memory:coffee" for item in retrieved)
            )

            restored = controls.archive(
                memory_id="coffee",
                expected_revision=archived.revision,
                archived=False,
                source_event_key="unarchive-coffee",
                created_at=T0 + timedelta(minutes=5),
            )
            self.assertFalse(restored.archived)
            controls.delete(
                memory_id="coffee",
                expected_revision=restored.revision,
                source_event_key="delete-coffee",
                created_at=T0 + timedelta(minutes=6),
            )
            with self.assertRaises(KeyError):
                store.memory.get("coffee")
            with db.transaction() as conn:
                tombstones = int(
                    conn.execute(
                        """SELECT COUNT(*) FROM erasure_tombstones
                           WHERE identity_id=?""",
                        ("fish-r20",),
                    ).fetchone()[0]
                )
            self.assertGreaterEqual(tombstones, 1)

    def test_onboarding_is_evidence_based_and_never_claims_missing_steps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db, store = self._product(root)
            host = RuntimeHost(db)
            cfg = _provider_config()
            host.register_provider(
                model_adapter.capability_descriptor_for_config(cfg),
                _healthy(),
            )
            runtime_descriptor = model_adapter._provider_descriptor(cfg)

            missing = ProductOnboardingVerifier(
                db,
                identity_id="fish-r20",
                runtime_host=host,
                runtime_descriptor=runtime_descriptor,
            ).verify()
            self.assertFalse(missing.ready)
            self.assertTrue(
                any("first canonical user turn" in item for item in missing.blockers)
            )
            self.assertTrue(
                any("backup/status" in item for item in missing.blockers)
            )

            self._save_memory(
                store,
                key="first-turn-and-memory",
                memory_id="first-memory",
                text="我喜欢乌龙茶",
                at=T0,
            )
            backup = root / "managed-backup.sqlite3"
            RecoveryManager.create_backup(
                source_path=db.path,
                backup_path=backup,
                identity_id="fish-r20",
                release_version="r20-test",
                release_digest="sha256:" + ("a" * 64),
                created_at=T0 + timedelta(minutes=1),
            )

            ready = ProductOnboardingVerifier(
                db,
                identity_id="fish-r20",
                runtime_host=host,
                runtime_descriptor=runtime_descriptor,
                backup_path=backup,
            ).verify()
            self.assertTrue(ready.ready, ready.blockers)
            self.assertEqual(
                {item.name for item in ready.checks},
                {
                    "provider_connectivity",
                    "identity_loaded",
                    "first_turn",
                    "memory_control",
                    "backup_status",
                },
            )

    def test_offboarding_pauses_real_runtime_resets_relationship_exports_and_deletes_all_memory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db, store = self._product(root)
            first = self._save_memory(
                store,
                key="memory-one",
                memory_id="one",
                text="长期项目代号 Bluefin",
                at=T0,
            )
            self._save_memory(
                store,
                key="memory-two",
                memory_id="two",
                text="偏好安静环境",
                at=T0 + timedelta(seconds=1),
            )

            relationship_source = store.record_owner_control(
                source_event_key="relationship-familiar",
                event_type="relationship.owner",
                payload={"state": "FAMILIAR"},
                observed_at=T0 + timedelta(minutes=1),
            )
            relationships = RelationshipService(db)
            relationships.transition(
                transition_id="rel-familiar",
                identity_id="fish-r20",
                principal_id="owner",
                expected_state=RelationshipLifecycle.NEW,
                to_state=RelationshipLifecycle.FAMILIAR,
                source_event_id=relationship_source.event_id,
                reason="OWNER_CONFIRMED",
                value_patch={
                    "shared_history": {"project": "Bluefin"},
                    "proactivity_policy": {"enabled": True},
                },
                created_at=T0 + timedelta(minutes=1),
            )

            purpose_source = store.record_user_turn(
                source_event_key="purpose-source",
                text="十分钟后提醒我",
                observed_at=T0 + timedelta(minutes=2),
            )
            store.create_purpose(
                Purpose(
                    purpose_id="purpose-r20",
                    identity_id="fish-r20",
                    owner_type=PurposeOwner.USER,
                    owner_id="owner",
                    state=PurposeState.SCHEDULED,
                    kind=PurposeKind.REMINDER,
                    source_event_id=purpose_source.event_id,
                    payload={"text": "提醒"},
                    scheduled_wall_time="2026-11-18T14:20:00+00:00",
                    timezone_name="UTC",
                    resolved_utc_time=T0 + timedelta(minutes=20),
                    miss_policy=MissPolicy.DELIVER_LATE,
                ),
                created_at=T0 + timedelta(minutes=2),
            )

            # A secret outside canonical authority must never enter native export.
            (root / "provider.json").write_text(
                json.dumps({"api_key": "R20-SECRET-DO-NOT-EXPORT"}),
                encoding="utf-8",
            )
            broker = ResourceBroker(mode=ResourceMode.BALANCED)
            export_path = root / "offboarding-export.json"
            report = ProductOffboardingService(
                store,
                resource_broker=broker,
            ).execute(
                source_event_key="offboard-all",
                export_path=export_path,
                reset_relationship=True,
                delete_all_memories=True,
                created_at=T0 + timedelta(minutes=3),
            )
            self.assertTrue(report.ok, report.blockers)
            self.assertTrue(report.paused)
            self.assertEqual(broker.mode, ResourceMode.SLEEP)
            self.assertIn("purpose-r20", report.cancelled_purpose_ids)
            self.assertEqual(set(report.deleted_memory_ids), {"one", "two"})
            self.assertEqual(report.relationship.state, RelationshipLifecycle.PAUSED)
            self.assertEqual(
                report.relationship.value.get("proactivity_policy"),
                {"enabled": False},
            )
            self.assertNotIn("shared_history", report.relationship.value)

            rebuilt = relationships.rebuild(
                identity_id="fish-r20",
                principal_id="owner",
            )
            self.assertEqual(rebuilt.state, RelationshipLifecycle.PAUSED)
            self.assertNotIn("shared_history", rebuilt.value)
            self.assertEqual(
                rebuilt.value.get("proactivity_policy"),
                {"enabled": False},
            )
            with db.transaction() as conn:
                purpose_state = str(
                    conn.execute(
                        "SELECT state FROM purposes WHERE purpose_id='purpose-r20'"
                    ).fetchone()[0]
                )
            self.assertEqual(purpose_state, "CANCELLED")
            with self.assertRaises(KeyError):
                store.memory.get(first.memory_id)
            self.assertTrue(export_path.exists())
            exported = export_path.read_text(encoding="utf-8")
            self.assertNotIn("R20-SECRET-DO-NOT-EXPORT", exported)
            self.assertNotIn("presentation_state", exported)

    def test_offboarding_without_runtime_binding_reports_blocker_instead_of_fake_success(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._product(Path(td))
            report = ProductOffboardingService(store).execute(
                source_event_key="offboard-no-runtime",
                created_at=T0,
            )
            self.assertFalse(report.ok)
            self.assertFalse(report.paused)
            self.assertIn(
                "background runtime broker is not bound",
                report.blockers,
            )


if __name__ == "__main__":
    unittest.main()
