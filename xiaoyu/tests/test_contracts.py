from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from xiaoyu.contracts import (
    ActionReceipt,
    ActorContext,
    CapabilityDescriptor,
    Delegation,
    EffectIntent,
    InputSourceEnvelope,
    IsolationMode,
    PrincipalContext,
    ProviderHealth,
    ProviderLifecycle,
    Taint,
    TrustClass,
)
from xiaoyu.contracts.common import canonical_json
from xiaoyu.contracts.errors import ContractFieldError, ContractTimeError


NOW = datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc)


class ContractRoundTripTests(unittest.TestCase):
    def test_envelope_roundtrip_and_deterministic_json(self):
        value = InputSourceEnvelope(
            event_id="evt-1",
            surface="desktop",
            source_type="text",
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(Taint.SENSITIVE,),
            eligible_for_memory=True,
            correlation_id="corr-1",
            observed_at=NOW,
            payload_type="text/plain",
            payload={"text": "你好"},
        )
        restored = InputSourceEnvelope.from_dict(value.to_dict())
        self.assertEqual(restored, value)
        self.assertEqual(canonical_json(value.to_dict()), canonical_json(restored.to_dict()))

    def test_principal_actor_delegation_roundtrip(self):
        principal = PrincipalContext(
            principal_id="owner",
            authentication_level="OWNER_AUTHENTICATED",
            confidence=1.0,
            evidence_classes=("LOCAL_OS_SESSION",),
            viewer_set=("owner",),
            session_scope="desktop-session",
            expires_at=NOW + timedelta(hours=1),
        )
        self.assertEqual(PrincipalContext.from_dict(principal.to_dict()), principal)

        actor = ActorContext(
            actor_id="xiaoyu.runtime",
            actor_type="runtime",
            implementation_digest="sha256:abc",
            provider_id=None,
            device_id="laptop",
            trust_tier="first_party",
        )
        self.assertEqual(ActorContext.from_dict(actor.to_dict()), actor)

        delegation = Delegation(
            delegation_id="del-1",
            issued_by_principal="owner",
            issued_to_actor="xiaoyu.runtime",
            purpose_id="purpose-1",
            action_classes=("message.send",),
            resources=("qq:owner",),
            max_effect={"messages": 1},
            valid_from=NOW,
            expires_at=NOW + timedelta(minutes=10),
            revocable=True,
        )
        self.assertEqual(Delegation.from_dict(delegation.to_dict()), delegation)

    def test_effect_and_receipt_roundtrip(self):
        effect = EffectIntent(
            effect_id="eff-1",
            intent_id="intent-1",
            purpose_id="purpose-1",
            actor_id="tool:qq",
            action_class="message.send",
            request={"text": "done"},
            idempotency_key="idem-1",
            replayable=True,
            created_at=NOW,
        )
        self.assertEqual(EffectIntent.from_dict(effect.to_dict()), effect)

        receipt = ActionReceipt(
            receipt_id="rcpt-1",
            effect_id="eff-1",
            actor_id="tool:qq",
            provider_id="napcat",
            authorization_decision_id="auth-1",
            request_digest="sha256:req",
            result_class="SUCCEEDED",
            result_digest="sha256:res",
            external_ref="msg-123",
            observed_at=NOW,
            metadata={"attempt": 1},
        )
        self.assertEqual(ActionReceipt.from_dict(receipt.to_dict()), receipt)

    def test_capability_and_health_roundtrip(self):
        descriptor = CapabilityDescriptor(
            provider_id="qwen3-tts-local",
            capability="speech.tts",
            implementation_version="0.4.0",
            contract_name="xiaoyu.speech.tts",
            contract_min_version="1.0.0",
            contract_max_exclusive="2.0.0",
            artifact_digest="sha256:model",
            descriptor_digest="sha256:descriptor",
            interface_digest="sha256:wit",
            tool_schema_digest=None,
            isolation=IsolationMode.SIDECAR,
            features={"streaming": True, "cancel": True},
            data_classes=("assistant_text",),
            permissions_required=("audio.output",),
            fallback_group="speech.tts.default",
            lifecycle=ProviderLifecycle.ACTIVE,
            resource_profile={"vram_mb": 1400},
        )
        self.assertEqual(CapabilityDescriptor.from_dict(descriptor.to_dict()), descriptor)

        health = ProviderHealth(
            liveness="ALIVE",
            readiness="READY",
            capability_health={"streaming": "READY"},
            reason=None,
            since=NOW,
            retry_after_ms=None,
            details={},
        )
        self.assertEqual(ProviderHealth.from_dict(health.to_dict()), health)


class ContractValidationTests(unittest.TestCase):
    def test_unknown_authority_field_rejected(self):
        envelope = InputSourceEnvelope(
            event_id="evt-1",
            surface="desktop",
            source_type="text",
            principal_hint=None,
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            correlation_id="corr-1",
            observed_at=NOW,
            payload_type="text/plain",
            payload="hello",
        ).to_dict()
        envelope["surprise_authority"] = True
        with self.assertRaises(ContractFieldError):
            InputSourceEnvelope.from_dict(envelope)

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ContractTimeError):
            InputSourceEnvelope(
                event_id="evt-1",
                surface="desktop",
                source_type="text",
                principal_hint=None,
                audience_scope="PRIVATE",
                context_space="PERSONAL",
                trust_class=TrustClass.OWNER_DIRECT,
                taint=(),
                eligible_for_memory=True,
                correlation_id="corr-1",
                observed_at=datetime(2026, 11, 18, 12, 30),
                payload_type="text/plain",
                payload="hello",
            )

    def test_principal_confidence_range(self):
        with self.assertRaises(ValueError):
            PrincipalContext(
                principal_id="owner",
                authentication_level="UNKNOWN",
                confidence=1.1,
                evidence_classes=(),
                viewer_set=(),
                session_scope="x",
                expires_at=None,
            )


if __name__ == "__main__":
    unittest.main()
