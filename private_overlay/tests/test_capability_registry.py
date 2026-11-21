import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capabilities import (  # noqa: E402
    CapabilityProvider,
    CapabilityRegistrationError,
    CapabilityRegistry,
    CapabilityUnavailable,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_highest_priority_healthy_provider_wins(self):
        registry = CapabilityRegistry()
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "native",
                lambda payload: {"allow": True, "source": "native"},
                priority=10,
            )
        )
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "hybrid",
                lambda payload: {"allow": False, "source": "hybrid"},
                priority=100,
            )
        )

        result = asyncio.run(
            registry.dispatch("interruptibility.v1", {"kind": "entertainment"})
        )

        self.assertEqual(result.provider_id, "hybrid")
        self.assertFalse(result.value["allow"])

    def test_unhealthy_provider_is_skipped(self):
        registry = CapabilityRegistry()
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "primary",
                lambda payload: "bad",
                priority=100,
                health=lambda: False,
            )
        )
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "fallback",
                lambda payload: "ok",
                priority=10,
            )
        )

        result = asyncio.run(registry.dispatch("interruptibility.v1", {}))

        self.assertEqual(result.provider_id, "fallback")
        self.assertEqual(
            [(item.provider_id, item.status) for item in result.attempts],
            [("primary", "unhealthy"), ("fallback", "selected")],
        )

    def test_failed_provider_falls_back(self):
        registry = CapabilityRegistry()

        def fail(_payload):
            raise RuntimeError("boom")

        registry.register(
            CapabilityProvider(
                "interruptibility.v1", "primary", fail, priority=100
            )
        )
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "fallback",
                lambda payload: {"allow": True},
                priority=10,
            )
        )

        result = asyncio.run(registry.dispatch("interruptibility.v1", {}))

        self.assertEqual(result.provider_id, "fallback")
        self.assertEqual(result.attempts[0].status, "failed")
        self.assertIn("RuntimeError: boom", result.attempts[0].error)

    def test_shadow_is_observed_but_cannot_take_control(self):
        registry = CapabilityRegistry()
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "stable",
                lambda payload: {"allow": False},
                priority=10,
            )
        )
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "candidate",
                lambda payload: {"allow": True},
                priority=999,
                shadow=True,
            )
        )

        result = asyncio.run(registry.dispatch("interruptibility.v1", {}))

        self.assertEqual(result.provider_id, "stable")
        self.assertEqual(len(result.shadows), 1)
        self.assertEqual(result.shadows[0].provider_id, "candidate")
        self.assertEqual(result.shadows[0].status, "observed")
        self.assertTrue(result.shadows[0].value["allow"])

    def test_major_versions_are_separate_capabilities(self):
        registry = CapabilityRegistry()
        registry.register(
            CapabilityProvider(
                "interruptibility.v1", "v1", lambda payload: 1
            )
        )
        registry.register(
            CapabilityProvider(
                "interruptibility.v2", "v2", lambda payload: 2
            )
        )

        v1 = asyncio.run(registry.dispatch("interruptibility.v1", {}))
        v2 = asyncio.run(registry.dispatch("interruptibility.v2", {}))

        self.assertEqual(v1.value, 1)
        self.assertEqual(v2.value, 2)

    def test_duplicate_provider_is_rejected(self):
        registry = CapabilityRegistry()
        provider = CapabilityProvider(
            "interruptibility.v1", "native", lambda payload: True
        )
        registry.register(provider)

        with self.assertRaises(CapabilityRegistrationError):
            registry.register(provider)

    def test_invalid_unversioned_capability_is_rejected(self):
        with self.assertRaises(CapabilityRegistrationError):
            CapabilityProvider(
                "interruptibility", "native", lambda payload: True
            )

    def test_all_unavailable_reports_attempts(self):
        registry = CapabilityRegistry()
        registry.register(
            CapabilityProvider(
                "interruptibility.v1",
                "offline",
                lambda payload: True,
                health=lambda: False,
            )
        )

        with self.assertRaises(CapabilityUnavailable) as caught:
            asyncio.run(registry.dispatch("interruptibility.v1", {}))

        self.assertEqual(caught.exception.capability, "interruptibility.v1")
        self.assertEqual(caught.exception.attempts[0].status, "unhealthy")


if __name__ == "__main__":
    unittest.main()
