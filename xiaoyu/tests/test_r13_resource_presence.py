from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import model_adapter

from xiaoyu.contracts import (
    InputSourceEnvelope,
    ProviderHealth,
    TrustClass,
)
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.runtime import (
    AmbientPresenceEngine,
    PresenceState,
    ResourceBroker,
    ResourceMode,
    ResourceRequest,
    ResourceUnavailable,
    RuntimeHost,
)


NOW = datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc)


def ready_health():
    return ProviderHealth(
        liveness="UP",
        readiness="READY",
        capability_health={"chat.completion": "READY"},
        reason=None,
        since=NOW,
        retry_after_ms=None,
        details={},
    )


def provider_config(name="qwen"):
    spec = model_adapter.PROVIDERS[name]
    result = {
        "provider": name,
        "url": spec["url"],
        "model": spec["model"],
        "key_env": spec.get("key_env", ""),
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


class R13ResourcePresenceTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _seed_core(self, db):
        envelope = InputSourceEnvelope(
            event_id="raw:r13-core",
            surface="test",
            source_type="text",
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            correlation_id="corr:r13",
            observed_at=NOW,
            payload_type="text/plain",
            payload={"text": "identity authority must not change"},
        )
        event = CanonicalEvent.from_envelope(
            identity_id="fish-1",
            event_type="identity.continuity",
            envelope=envelope,
            principal_id="owner",
            recorded_at=NOW,
            source_namespace="r13-test",
            source_event_key="core",
            event_id_override=stable_event_id(
                "fish-1", "r13-test", "core"
            ),
        )
        with db.transaction(immediate=True) as conn:
            CanonicalEventRepository().append_or_get(conn, event)

    def _core_snapshot(self, db):
        with db.transaction() as conn:
            return [
                tuple(row)
                for row in conn.execute(
                    """SELECT event_id,identity_id,event_type,payload_json,
                              semantic_digest
                       FROM canonical_events
                       ORDER BY event_id"""
                ).fetchall()
            ]

    def test_full_accepts_gpu_request_that_game_rejects(self):
        request = ResourceRequest(
            owner_id="vision-heavy",
            ram_mb=2048,
            vram_mb=2048,
            cpu_fraction=0.3,
            gpu_fraction=0.4,
        )
        full = ResourceBroker(mode=ResourceMode.FULL)
        self.assertTrue(full.can_reserve(request))
        full.reserve("lease-heavy", request)

        game = ResourceBroker(mode=ResourceMode.GAME)
        self.assertFalse(game.can_reserve(request))
        with self.assertRaises(ResourceUnavailable):
            game.reserve("lease-heavy", request)

    def test_mode_transition_preempts_low_priority_deterministically(self):
        broker = ResourceBroker(mode=ResourceMode.BALANCED)
        low = ResourceRequest(
            owner_id="background-vision",
            vram_mb=1024,
            priority=10,
        )
        high = ResourceRequest(
            owner_id="foreground-chat",
            vram_mb=1024,
            priority=90,
        )
        broker.reserve("lease-low", low)
        broker.reserve("lease-high", high)

        transition = broker.set_mode(ResourceMode.GAME)
        self.assertEqual(
            transition.revoked_lease_ids,
            ("lease-low",),
        )
        self.assertEqual(
            tuple(lease.lease_id for lease in broker.leases()),
            ("lease-high",),
        )
        self.assertEqual(broker.mode, ResourceMode.GAME)

    def test_non_preemptible_work_blocks_invalid_sleep_transition(self):
        broker = ResourceBroker(mode=ResourceMode.FULL)
        broker.reserve(
            "critical",
            ResourceRequest(
                owner_id="critical-runtime",
                ram_mb=1024,
                cpu_fraction=0.2,
                priority=100,
                preemptible=False,
            ),
        )
        with self.assertRaises(ResourceUnavailable):
            broker.set_mode(ResourceMode.SLEEP)
        self.assertEqual(broker.mode, ResourceMode.FULL)
        self.assertEqual(len(broker.leases()), 1)

    def test_release_restores_capacity(self):
        broker = ResourceBroker(mode=ResourceMode.ECO)
        request = ResourceRequest(
            owner_id="small-provider",
            ram_mb=1800,
            vram_mb=256,
            cpu_fraction=0.2,
            gpu_fraction=0.1,
        )
        broker.reserve("one", request)
        with self.assertRaises(ResourceUnavailable):
            broker.reserve("two", request)
        self.assertTrue(broker.release("one"))
        self.assertFalse(broker.release("one"))
        broker.reserve("two", request)
        self.assertEqual(len(broker.leases()), 1)

    def test_runtime_host_reserves_registered_provider_resource_profile(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            broker = ResourceBroker(mode=ResourceMode.BALANCED)
            host = RuntimeHost(db, resource_broker=broker)
            cfg = provider_config("qwen")
            descriptor = model_adapter.capability_descriptor_for_config(cfg)
            descriptor = replace(
                descriptor,
                resource_profile={
                    "ram_mb": 768,
                    "vram_mb": 256,
                    "cpu_fraction": 0.15,
                    "gpu_fraction": 0.05,
                },
            )
            host.register_provider(descriptor, ready_health())

            lease = host.reserve_provider_resources(
                "qwen",
                lease_id="qwen-runtime",
                priority=70,
            )
            self.assertEqual(lease.request.owner_id, "qwen")
            self.assertEqual(lease.request.ram_mb, 768)
            self.assertEqual(lease.request.vram_mb, 256)
            self.assertTrue(
                host.release_provider_resources("qwen-runtime")
            )
            self.assertEqual(broker.leases(), ())

    def test_invalid_resource_profile_fails_before_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            broker = ResourceBroker()
            host = RuntimeHost(db, resource_broker=broker)
            cfg = provider_config("qwen")
            descriptor = model_adapter.capability_descriptor_for_config(cfg)
            descriptor = replace(
                descriptor,
                resource_profile={
                    "ram_mb": "a lot",
                    "gpu_fraction": 0.1,
                },
            )
            host.register_provider(descriptor, ready_health())
            with self.assertRaisesRegex(
                ValueError, "ram_mb must be numeric"
            ):
                host.reserve_provider_resources(
                    "qwen", lease_id="bad"
                )
            self.assertEqual(broker.leases(), ())

    def test_presence_is_deterministic_without_llm(self):
        engine = AmbientPresenceEngine(
            quiet_after_s=60,
            rest_after_s=300,
        )
        cases = [
            (
                dict(
                    mode=ResourceMode.BALANCED,
                    idle_seconds=0,
                    user_active=True,
                    active_work=False,
                ),
                PresenceState.ATTENTIVE,
            ),
            (
                dict(
                    mode=ResourceMode.BALANCED,
                    idle_seconds=20,
                    user_active=False,
                    active_work=True,
                ),
                PresenceState.BUSY,
            ),
            (
                dict(
                    mode=ResourceMode.BALANCED,
                    idle_seconds=20,
                    user_active=False,
                    active_work=False,
                ),
                PresenceState.IDLE,
            ),
            (
                dict(
                    mode=ResourceMode.BALANCED,
                    idle_seconds=120,
                    user_active=False,
                    active_work=False,
                ),
                PresenceState.QUIET,
            ),
            (
                dict(
                    mode=ResourceMode.BALANCED,
                    idle_seconds=600,
                    user_active=False,
                    active_work=False,
                ),
                PresenceState.RESTING,
            ),
            (
                dict(
                    mode=ResourceMode.SLEEP,
                    idle_seconds=0,
                    user_active=True,
                    active_work=True,
                ),
                PresenceState.SLEEPING,
            ),
        ]
        for kwargs, expected in cases:
            first = engine.frame(**kwargs)
            second = engine.frame(**kwargs)
            self.assertEqual(first, second)
            self.assertEqual(first.state, expected)
            self.assertFalse(first.durable_mutation)
            self.assertIsNone(first.narrative_claim)

    def test_presence_and_resource_runtime_do_not_mutate_semantic_core(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._seed_core(db)
            before = self._core_snapshot(db)

            broker = ResourceBroker(mode=ResourceMode.BALANCED)
            broker.reserve(
                "ambient",
                ResourceRequest(
                    owner_id="ambient-presence",
                    ram_mb=32,
                    cpu_fraction=0.01,
                    priority=5,
                ),
            )
            engine = AmbientPresenceEngine()
            for idle in (0, 30, 120, 900):
                frame = engine.frame(
                    mode=broker.mode,
                    idle_seconds=idle,
                    user_active=False,
                    active_work=False,
                )
                self.assertFalse(frame.durable_mutation)
            broker.release("ambient")
            broker.set_mode(ResourceMode.SLEEP)

            self.assertEqual(self._core_snapshot(db), before)


if __name__ == "__main__":
    unittest.main()
