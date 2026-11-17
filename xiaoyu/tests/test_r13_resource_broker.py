from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import (
    AmbientPresenceEngine,
    CompositeResourceSampler,
    NvmlResourceSampler,
    PresenceState,
    PsutilResourceSampler,
    ResourceBroker,
    ResourceMode,
    ResourceRequest,
    ResourceSnapshot,
)


class FakePsutil:
    @staticmethod
    def cpu_percent(interval=None):
        return 24.5

    @staticmethod
    def virtual_memory():
        return SimpleNamespace(
            percent=61.0,
            available=8 * 1024 * 1024 * 1024,
        )

    @staticmethod
    def sensors_battery():
        return SimpleNamespace(
            percent=73.0,
            power_plugged=False,
        )

    @staticmethod
    def Process():
        return SimpleNamespace(
            memory_info=lambda: SimpleNamespace(
                rss=256 * 1024 * 1024
            )
        )


class FakeNvml:
    initialized = 0
    shutdown = 0

    @classmethod
    def nvmlInit(cls):
        cls.initialized += 1

    @staticmethod
    def nvmlDeviceGetHandleByIndex(index):
        return "gpu-%d" % index

    @staticmethod
    def nvmlDeviceGetUtilizationRates(handle):
        return SimpleNamespace(gpu=37)

    @staticmethod
    def nvmlDeviceGetMemoryInfo(handle):
        return SimpleNamespace(
            used=2 * 1024 * 1024 * 1024,
            total=8 * 1024 * 1024 * 1024,
        )

    @staticmethod
    def nvmlDeviceGetPowerUsage(handle):
        return 55000

    @classmethod
    def nvmlShutdown(cls):
        cls.shutdown += 1


class StaticSampler:
    def __init__(self, snapshot):
        self.value = snapshot

    def sample(self):
        return self.value


class R13ResourceBrokerTests(unittest.TestCase):
    def test_external_psutil_and_nvml_adapters_feed_one_snapshot(self):
        FakeNvml.initialized = 0
        FakeNvml.shutdown = 0
        gpu = NvmlResourceSampler(FakeNvml)
        sampler = CompositeResourceSampler(
            PsutilResourceSampler(FakePsutil),
            gpu,
        )
        snapshot = sampler.sample()

        self.assertEqual(snapshot.cpu_percent, 24.5)
        self.assertEqual(snapshot.memory_percent, 61.0)
        self.assertEqual(snapshot.memory_available_mb, 8192.0)
        self.assertEqual(snapshot.process_rss_mb, 256.0)
        self.assertEqual(snapshot.battery_percent, 73.0)
        self.assertFalse(snapshot.power_plugged)
        self.assertEqual(snapshot.gpu_util_percent, 37.0)
        self.assertEqual(snapshot.vram_used_mb, 2048.0)
        self.assertEqual(snapshot.vram_total_mb, 8192.0)
        self.assertEqual(snapshot.gpu_power_w, 55.0)

        gpu.close()
        self.assertEqual(FakeNvml.initialized, 1)
        self.assertEqual(FakeNvml.shutdown, 1)

    def test_game_mode_blocks_background_gpu_without_blocking_light_network(self):
        snapshot = ResourceSnapshot(
            cpu_percent=20,
            memory_percent=50,
            gpu_util_percent=20,
            battery_percent=90,
            power_plugged=True,
        )
        broker = ResourceBroker(
            StaticSampler(snapshot),
            mode=ResourceMode.GAME,
        )
        gpu = broker.admit(
            ResourceRequest(
                "vision.embedding",
                background=True,
                requires_gpu=True,
                estimated_vram_mb=512,
            )
        )
        self.assertFalse(gpu.allowed)
        self.assertIn("gpu_disabled", gpu.reasons)

        network = broker.admit(
            ResourceRequest(
                "status.sync",
                background=True,
                requires_network=True,
                estimated_ram_mb=32,
            )
        )
        self.assertTrue(network.allowed)

    def test_sleep_mode_disables_background_network_and_gpu(self):
        broker = ResourceBroker(
            StaticSampler(ResourceSnapshot()),
            mode=ResourceMode.SLEEP,
        )
        decision = broker.admit(
            ResourceRequest(
                "background.model",
                background=True,
                requires_network=True,
                requires_gpu=True,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertIn("background_disabled", decision.reasons)
        self.assertIn("gpu_disabled", decision.reasons)
        self.assertIn("network_disabled", decision.reasons)

    def test_eco_low_battery_sheds_background_expensive_work(self):
        broker = ResourceBroker(
            StaticSampler(
                ResourceSnapshot(
                    cpu_percent=20,
                    memory_percent=50,
                    gpu_util_percent=10,
                    battery_percent=12,
                    power_plugged=False,
                )
            ),
            mode=ResourceMode.ECO,
        )
        background = broker.admit(
            ResourceRequest(
                "background.retrieval",
                background=True,
                requires_network=True,
                estimated_ram_mb=128,
            )
        )
        self.assertFalse(background.allowed)
        self.assertIn(
            "low_battery_background_work",
            background.reasons,
        )

        foreground = broker.admit(
            ResourceRequest(
                "foreground.chat",
                background=False,
                requires_network=True,
            )
        )
        self.assertTrue(foreground.allowed)

    def test_pressure_is_explicit_not_silent(self):
        broker = ResourceBroker(
            StaticSampler(
                ResourceSnapshot(
                    cpu_percent=96,
                    memory_percent=95,
                    gpu_util_percent=94,
                )
            ),
            mode=ResourceMode.BALANCED,
        )
        decision = broker.admit(
            ResourceRequest(
                "vision",
                background=True,
                requires_gpu=True,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(
            set(decision.reasons),
            {"cpu_pressure", "memory_pressure", "gpu_pressure"},
        )

    def test_presence_remains_alive_without_llm_and_never_needs_llm(self):
        engine = AmbientPresenceEngine()
        idle = engine.tick(
            mode=ResourceMode.BALANCED,
            user_active=False,
            window_visible=True,
            llm_available=False,
        )
        self.assertEqual(idle.state, PresenceState.IDLE)
        self.assertFalse(idle.llm_required)
        self.assertGreater(idle.next_tick_ms, 0)

        active = engine.tick(
            mode=ResourceMode.BALANCED,
            user_active=True,
            window_visible=True,
            llm_available=False,
        )
        self.assertEqual(active.state, PresenceState.ATTENTIVE)
        self.assertFalse(active.llm_required)

        game = engine.tick(
            mode=ResourceMode.GAME,
            user_active=True,
            window_visible=True,
            llm_available=False,
        )
        self.assertEqual(game.state, PresenceState.GAME_MINIMAL)

        sleep = engine.tick(
            mode=ResourceMode.SLEEP,
            user_active=False,
            window_visible=False,
            llm_available=False,
        )
        self.assertEqual(sleep.state, PresenceState.SLEEPING)

    def test_resource_and_presence_layer_cannot_mutate_semantic_core(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO canonical_events(
                           event_id,identity_id,turn_id,event_type,surface,
                           source_type,principal_id,audience_scope,
                           context_space,trust_class,taint_json,
                           eligible_for_memory,payload_type,payload_json,
                           observed_at,recorded_at,correlation_id,
                           schema_version
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "evt-core",
                        "fish-1",
                        None,
                        "identity.marker",
                        "test",
                        "text",
                        "owner",
                        "PRIVATE",
                        "PERSONAL",
                        "OWNER_DIRECT",
                        "[]",
                        0,
                        "application/json",
                        "{}",
                        "2026-11-18T00:00:00+00:00",
                        "2026-11-18T00:00:00+00:00",
                        "corr-core",
                        1,
                    ),
                )

            def snapshot():
                with db.transaction() as conn:
                    return [
                        tuple(row)
                        for row in conn.execute(
                            """SELECT event_id,identity_id,event_type,
                                      payload_json
                               FROM canonical_events ORDER BY event_id"""
                        ).fetchall()
                    ]

            before = snapshot()
            broker = ResourceBroker(
                StaticSampler(
                    ResourceSnapshot(
                        cpu_percent=10,
                        memory_percent=20,
                    )
                )
            )
            broker.admit(
                ResourceRequest(
                    "chat",
                    requires_network=True,
                )
            )
            AmbientPresenceEngine().tick(
                mode=ResourceMode.BALANCED,
                user_active=False,
                window_visible=True,
                llm_available=False,
            )
            self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
