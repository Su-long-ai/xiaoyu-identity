from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import model_adapter

from xiaoyu.contracts import (
    InputSourceEnvelope,
    ProviderHealth,
    ProviderLifecycle,
    TrustClass,
)
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.provider_execution import (
    ProviderExecutionRegistry,
)
from xiaoyu.runtime import RuntimeHost
from xiaoyu.runtime.provider_registry import (
    PrivacyClass,
    ProviderDescriptor,
)


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def config(provider: str, *, fallbacks=()):
    spec = model_adapter.PROVIDERS[provider]
    result = {
        "provider": provider,
        "url": spec["url"],
        "model": spec["model"],
        "key_env": spec.get("key_env", ""),
        "fallbacks": list(fallbacks),
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


def health(*, ready=True):
    return ProviderHealth(
        liveness="UP",
        readiness="READY" if ready else "NOT_READY",
        capability_health={
            "chat.completion": "READY" if ready else "DEGRADED"
        },
        reason=None if ready else "synthetic degradation",
        since=NOW,
        retry_after_ms=None,
        details={},
    )


class R12RuntimeHostTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _register(self, host, cfg, *, ready=True):
        descriptor = model_adapter.capability_descriptor_for_config(cfg)
        host.register_provider(descriptor, health=health(ready=ready))
        return descriptor

    def _seed_identity_state(self, db):
        envelope = InputSourceEnvelope(
            event_id="raw:identity-state",
            surface="test",
            source_type="text",
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            correlation_id="corr:identity-state",
            observed_at=NOW,
            payload_type="text/plain",
            payload={"text": "canonical identity continuity marker"},
        )
        event = CanonicalEvent.from_envelope(
            identity_id="fish-1",
            event_type="identity.continuity",
            envelope=envelope,
            principal_id="owner",
            recorded_at=NOW,
            source_namespace="r12-test",
            source_event_key="identity-state",
            event_id_override=stable_event_id(
                "fish-1", "r12-test", "identity-state"
            ),
        )
        with db.transaction(immediate=True) as conn:
            CanonicalEventRepository().append_or_get(conn, event)
        return event.event_id

    def _canonical_snapshot(self, db):
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

    def test_registered_ready_provider_is_admitted(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            cfg = config("qwen")
            stored = self._register(host, cfg)
            runtime = model_adapter._provider_descriptor(cfg)

            admission = host.admit_provider(
                runtime,
                required_data_class="OWNER_PRIVATE",
                required_features=("fallback_capable",),
            )
            self.assertTrue(admission.allowed)
            self.assertEqual(admission.reasons, ())
            self.assertEqual(
                admission.descriptor.descriptor_digest,
                stored.descriptor_digest,
            )
            self.assertEqual(admission.health.readiness, "READY")

    def test_lifecycle_and_health_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            cfg = config("qwen")
            self._register(host, cfg)
            runtime = model_adapter._provider_descriptor(cfg)

            self.assertTrue(
                ProviderExecutionRegistry(db).set_lifecycle(
                    "qwen", ProviderLifecycle.DEPRECATED, NOW
                )
            )
            admission = host.admit_provider(runtime)
            self.assertFalse(admission.allowed)
            self.assertIn(
                "provider_lifecycle_not_active",
                admission.reasons,
            )

            self.assertTrue(
                ProviderExecutionRegistry(db).set_lifecycle(
                    "qwen", ProviderLifecycle.ACTIVE, NOW
                )
            )
            self.assertTrue(
                ProviderExecutionRegistry(db).update_health(
                    "qwen", health(ready=False), NOW
                )
            )
            admission = host.admit_provider(runtime)
            self.assertFalse(admission.allowed)
            self.assertIn(
                "stored_provider_not_ready",
                admission.reasons,
            )

    def test_descriptor_capability_and_implementation_drift_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            cfg = config("qwen")
            self._register(host, cfg)

            changed = dict(cfg)
            changed["model"] = "qwen-different"
            runtime = model_adapter._provider_descriptor(changed)
            admission = host.admit_provider(runtime)
            self.assertFalse(admission.allowed)
            self.assertIn(
                "descriptor_digest_changed",
                admission.reasons,
            )
            self.assertIn(
                "capability_digest_changed",
                admission.reasons,
            )

            original = model_adapter._provider_descriptor(cfg)
            forged = replace(
                original,
                implementation_digest="sha256:" + "1" * 64,
            )
            admission = host.admit_provider(forged)
            self.assertFalse(admission.allowed)
            self.assertIn(
                "implementation_digest_changed",
                admission.reasons,
            )

    def test_data_class_and_features_are_part_of_admission(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            cfg = config("custom")
            stored = model_adapter.capability_descriptor_for_config(cfg)
            stored = replace(
                stored,
                features={
                    **stored.features,
                    "fallback_capable": False,
                },
            )
            host.register_provider(stored, health())

            runtime = model_adapter._provider_descriptor(cfg)
            admission = host.admit_provider(
                runtime,
                required_data_class="OWNER_PRIVATE",
                required_features=("fallback_capable",),
            )
            self.assertFalse(admission.allowed)
            self.assertIn(
                "required_data_class_not_registered",
                admission.reasons,
            )
            self.assertIn(
                "feature_missing:fallback_capable",
                admission.reasons,
            )

    def test_incompatible_contract_is_rejected_at_registration(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            cfg = config("qwen")
            descriptor = model_adapter.capability_descriptor_for_config(cfg)
            incompatible = replace(
                descriptor,
                contract_min_version="2.0",
                contract_max_exclusive="3.0",
            )
            with self.assertRaisesRegex(
                ValueError, "contract_version_incompatible"
            ):
                host.register_provider(incompatible, health())

    def test_model_adapter_skips_unhealthy_primary_and_uses_registered_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            primary = config("deepseek", fallbacks=("qwen",))
            fallback = config("qwen")
            self._register(host, primary, ready=False)
            self._register(host, fallback, ready=True)
            calls = []

            def fake_once(cfg, messages, max_tokens, timeout, callback):
                calls.append(cfg["provider"])
                return "fallback-ok", {"provider": cfg["provider"]}

            with patch.object(
                model_adapter, "_chat_once", side_effect=fake_once
            ):
                answer, usage = model_adapter.chat(
                    primary,
                    [{"role": "user", "content": "hello"}],
                    runtime_host=host,
                    required_data_class="PUBLIC",
                )

            self.assertEqual(answer, "fallback-ok")
            self.assertEqual(usage["provider"], "qwen")
            self.assertEqual(calls, ["qwen"])

    def test_provider_failure_falls_back_without_mutating_core_state(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            identity_event = self._seed_identity_state(db)
            before = self._canonical_snapshot(db)

            host = RuntimeHost(db)
            primary = config("deepseek", fallbacks=("qwen",))
            fallback = config("qwen")
            self._register(host, primary)
            self._register(host, fallback)
            calls = []

            def fake_once(cfg, messages, max_tokens, timeout, callback):
                calls.append(cfg["provider"])
                if cfg["provider"] == "deepseek":
                    raise RuntimeError("synthetic provider failure")
                return "qwen-ok", {}

            with patch.object(
                model_adapter, "_chat_once", side_effect=fake_once
            ):
                answer, _ = model_adapter.chat(
                    primary,
                    [{"role": "user", "content": "continue"}],
                    runtime_host=host,
                    required_data_class="PUBLIC",
                )

            after = self._canonical_snapshot(db)
            self.assertEqual(answer, "qwen-ok")
            self.assertEqual(calls, ["deepseek", "qwen"])
            self.assertEqual(after, before)
            self.assertEqual(before[0][0], identity_event)

    def test_provider_swap_preserves_identity_authority(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._seed_identity_state(db)
            before = self._canonical_snapshot(db)

            host = RuntimeHost(db)
            for name in ("deepseek", "qwen"):
                cfg = config(name)
                self._register(host, cfg)
                admission = host.admit_provider(
                    model_adapter._provider_descriptor(cfg),
                    required_data_class="PUBLIC",
                )
                self.assertTrue(admission.allowed)

            self.assertEqual(self._canonical_snapshot(db), before)

    def test_live_health_can_fail_attempt_even_when_stored_health_is_ready(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            cfg = config("qwen")
            self._register(host, cfg, ready=True)
            admission = host.admit_provider(
                model_adapter._provider_descriptor(cfg),
                live_health=health(ready=False),
            )
            self.assertFalse(admission.allowed)
            self.assertIn("live_provider_not_ready", admission.reasons)


if __name__ == "__main__":
    unittest.main()
