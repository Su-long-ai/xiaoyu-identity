from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from xiaoyu.runtime import (
    CompositeTelemetrySampler,
    HostResourceSnapshot,
    MssScreenCapture,
    NvmlTelemetrySampler,
    PsutilTelemetrySampler,
    ResourceBroker,
    ResourceMode,
    ResourceRequest,
    VisionAnalysis,
    VisionSidecar,
)


T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class FakePsutil:
    @staticmethod
    def cpu_percent(interval=None):
        return 20.0

    @staticmethod
    def virtual_memory():
        return SimpleNamespace(
            available=8 * 1024 * 1024 * 1024,
        )

    @staticmethod
    def sensors_battery():
        return SimpleNamespace(
            percent=72.0,
            power_plugged=False,
        )


class FakeNvml:
    init_calls = 0
    shutdown_calls = 0

    @classmethod
    def nvmlInit(cls):
        cls.init_calls += 1

    @staticmethod
    def nvmlDeviceGetHandleByIndex(index):
        return "gpu-%d" % index

    @staticmethod
    def nvmlDeviceGetUtilizationRates(handle):
        return SimpleNamespace(gpu=19)

    @staticmethod
    def nvmlDeviceGetMemoryInfo(handle):
        return SimpleNamespace(
            used=2 * 1024 * 1024 * 1024,
            total=8 * 1024 * 1024 * 1024,
        )

    @staticmethod
    def nvmlDeviceGetPowerUsage(handle):
        return 48000

    @classmethod
    def nvmlShutdown(cls):
        cls.shutdown_calls += 1


class FakeMss:
    instances = []

    def __init__(self):
        self.monitors = ["virtual", "primary"]
        self.grabs = 0
        self.closed = False
        type(self).instances.append(self)

    def grab(self, monitor):
        self.grabs += 1
        return SimpleNamespace(
            rgb=bytes([10, 20, 30] * 4),
            width=2,
            height=2,
        )

    def close(self):
        self.closed = True


class ExternalRuntimeAdapterTests(unittest.TestCase):
    def test_psutil_and_nvml_feed_existing_resource_broker(self):
        FakeNvml.init_calls = 0
        FakeNvml.shutdown_calls = 0
        gpu = NvmlTelemetrySampler(FakeNvml)
        sampler = CompositeTelemetrySampler(
            PsutilTelemetrySampler(FakePsutil),
            gpu,
        )
        snapshot = sampler.sample()

        self.assertEqual(snapshot.cpu_fraction, 0.20)
        self.assertEqual(snapshot.ram_available_mb, 8192.0)
        self.assertEqual(snapshot.battery_percent, 72.0)
        self.assertFalse(snapshot.power_plugged)
        self.assertEqual(snapshot.gpu_fraction, 0.19)
        self.assertEqual(snapshot.vram_available_mb, 6144.0)
        self.assertEqual(snapshot.gpu_power_w, 48.0)

        # GAME has a 0.20 GPU budget. Existing system load is 0.19, so
        # another 0.05 background/runtime GPU share is rejected.
        game = ResourceBroker(
            mode=ResourceMode.GAME,
            telemetry_sampler=sampler,
        )
        request = ResourceRequest(
            owner_id="vision",
            ram_mb=128,
            vram_mb=128,
            cpu_fraction=0.01,
            gpu_fraction=0.05,
        )
        self.assertFalse(game.can_reserve(request))

        # FULL can admit the same request against the same live telemetry.
        full = ResourceBroker(
            mode=ResourceMode.FULL,
            telemetry_sampler=sampler,
        )
        self.assertTrue(full.can_reserve(request))

        gpu.close()
        self.assertEqual(FakeNvml.init_calls, 1)
        self.assertEqual(FakeNvml.shutdown_calls, 1)

    def test_live_free_memory_is_respected(self):
        class Sampler:
            def sample(self):
                return HostResourceSnapshot(
                    cpu_fraction=0.05,
                    ram_available_mb=64.0,
                    gpu_fraction=0.0,
                    vram_available_mb=32.0,
                )

        broker = ResourceBroker(
            mode=ResourceMode.FULL,
            telemetry_sampler=Sampler(),
        )
        self.assertFalse(
            broker.can_reserve(
                ResourceRequest(
                    owner_id="too-large",
                    ram_mb=128,
                    vram_mb=0,
                )
            )
        )
        self.assertFalse(
            broker.can_reserve(
                ResourceRequest(
                    owner_id="too-much-vram",
                    ram_mb=16,
                    vram_mb=64,
                )
            )
        )

    def test_mss_capture_is_lazy_transient_and_released_when_vision_off(self):
        FakeMss.instances = []
        capture = MssScreenCapture(
            monitor_index=1,
            mss_factory=FakeMss,
        )
        analyzed = []

        sidecar = VisionSidecar(
            capture,
            lambda raw, frame: (
                analyzed.append(
                    (bytes(raw), frame.width, frame.height, frame.pixel_format)
                )
                or VisionAnalysis("screen visible", 0.8, {})
            ),
            min_capture_interval_s=0,
        )

        # OFF means MSS is not even instantiated.
        self.assertIsNone(sidecar.poll(T0))
        self.assertEqual(FakeMss.instances, [])

        sidecar.enable()
        observation = sidecar.poll(T0)
        self.assertIsNotNone(observation)
        self.assertEqual(len(FakeMss.instances), 1)
        instance = FakeMss.instances[0]
        self.assertEqual(instance.grabs, 1)
        self.assertEqual(
            analyzed,
            [(bytes([10, 20, 30] * 4), 2, 2, "RGB")],
        )

        encoded = str(observation.envelope.to_dict())
        self.assertNotIn(str(bytes([10, 20, 30] * 4)), encoded)

        sidecar.disable()
        self.assertTrue(instance.closed)
        self.assertIsNone(sidecar.poll(T0))
        self.assertEqual(instance.grabs, 1)

    def test_mss_capture_reopens_cleanly_after_off_on_cycle(self):
        FakeMss.instances = []
        capture = MssScreenCapture(
            monitor_index=1,
            mss_factory=FakeMss,
        )
        sidecar = VisionSidecar(
            capture,
            lambda raw, frame: VisionAnalysis("screen", 1.0, {}),
            min_capture_interval_s=0,
        )
        sidecar.enable()
        self.assertIsNotNone(sidecar.poll(T0))
        first = FakeMss.instances[-1]
        sidecar.disable()
        self.assertTrue(first.closed)

        sidecar.enable()
        self.assertIsNotNone(sidecar.poll(T0))
        second = FakeMss.instances[-1]
        self.assertIsNot(first, second)
        self.assertFalse(second.closed)


if __name__ == "__main__":
    unittest.main()
