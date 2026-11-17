from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import model_adapter
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from send_guard import (
    FreshnessChanged,
    capture_expectations,
    dual_guarded_chat,
)
from xiaoyu.runtime.provider_registry import (
    PrivacyClass,
    ProviderAttemptContext,
    ProviderDescriptor,
    ProviderHealth,
    evaluate_provider,
    provider_session_namespace,
)


NOW=datetime(2026,11,18,12,0,tzinfo=timezone.utc)


def descriptor(
    provider_id="p",
    capability="chat.completion",
    privacy=(PrivacyClass.PUBLIC,PrivacyClass.OWNER_PRIVATE),
    endpoint_scope="REMOTE",
    descriptor_digest="desc-v1",
    capability_digest="cap-v1",
    implementation_digest="impl-v1",
):
    return ProviderDescriptor(
        provider_id=provider_id,
        capability=capability,
        descriptor_digest=descriptor_digest,
        capability_digest=capability_digest,
        implementation_digest=implementation_digest,
        endpoint_scope=endpoint_scope,
        privacy_classes=tuple(privacy),
    )


def attempt_context(
    d,
    *,
    principal_id="owner",
    audience_scope="PRIVATE",
    context_space="PERSONAL",
    context_generation="gen-1",
    privacy=PrivacyClass.OWNER_PRIVATE,
    required_capability=None,
    expected_descriptor_digest=None,
    expected_capability_digest=None,
    private_tool=False,
    authorization_digest="auth-v1",
    tool_result_digest=None,
    tool_implementation_digest=None,
    tool_schema_digest=None,
):
    return ProviderAttemptContext(
        identity_id="identity-1",
        principal_id=principal_id,
        audience_scope=audience_scope,
        context_space=context_space,
        context_generation=context_generation,
        provider_id=d.provider_id,
        required_capability=required_capability or d.capability,
        required_privacy_class=privacy,
        provider_descriptor_digest=d.descriptor_digest,
        provider_capability_digest=d.capability_digest,
        provider_implementation_digest=d.implementation_digest,
        expected_descriptor_digest=expected_descriptor_digest,
        expected_capability_digest=expected_capability_digest,
        authorization_digest=authorization_digest,
        tool_result_digest=tool_result_digest,
        tool_implementation_digest=tool_implementation_digest,
        tool_schema_digest=tool_schema_digest,
        source_contains_private_tool_result=private_tool,
    )


class ProviderPrivacyRuntimeTests(unittest.TestCase):
    def test_private_context_rejects_privacy_ineligible_provider(self):
        d=descriptor(privacy=(PrivacyClass.PUBLIC,))
        result=evaluate_provider(d,attempt_context(d))
        self.assertFalse(result.allowed)
        self.assertIn("privacy_class_ineligible",result.reasons)

    def test_local_only_rejects_remote_provider(self):
        d=descriptor(
            privacy=(PrivacyClass.PUBLIC,PrivacyClass.LOCAL_ONLY),
            endpoint_scope="REMOTE",
        )
        result=evaluate_provider(
            d,attempt_context(d,privacy=PrivacyClass.LOCAL_ONLY)
        )
        self.assertFalse(result.allowed)
        self.assertIn("local_only_requires_local_provider",result.reasons)

    def test_owner_private_rejects_group_guest_and_shared(self):
        d=descriptor()
        group=evaluate_provider(
            d,attempt_context(d,audience_scope="GROUP")
        )
        guest=evaluate_provider(
            d,attempt_context(d,principal_id="guest")
        )
        shared=evaluate_provider(
            d,attempt_context(d,context_space="SHARED")
        )
        self.assertIn("owner_private_audience_mismatch",group.reasons)
        self.assertIn("owner_private_principal_mismatch",guest.reasons)
        self.assertIn("owner_private_context_space_mismatch",shared.reasons)

    def test_private_tool_result_upgrades_public_request_to_private(self):
        d=descriptor(privacy=(PrivacyClass.PUBLIC,))
        result=evaluate_provider(
            d,
            attempt_context(
                d,privacy=PrivacyClass.PUBLIC,private_tool=True,
                tool_result_digest="tool-result-v1",
            ),
        )
        self.assertFalse(result.allowed)
        self.assertIn("privacy_class_ineligible",result.reasons)

    def test_capability_and_digest_changes_invalidate_eligibility(self):
        d=descriptor()
        wrong_cap=evaluate_provider(
            d,attempt_context(d,required_capability="vision.infer")
        )
        wrong_desc=evaluate_provider(
            d,attempt_context(d,expected_descriptor_digest="desc-old")
        )
        wrong_digest=evaluate_provider(
            d,attempt_context(d,expected_capability_digest="cap-old")
        )
        self.assertIn("capability_mismatch",wrong_cap.reasons)
        self.assertIn("descriptor_digest_changed",wrong_desc.reasons)
        self.assertIn("capability_digest_changed",wrong_digest.reasons)

    def test_provider_health_transition_blocks_new_attempt(self):
        d=descriptor()
        health=ProviderHealth(
            liveness="ALIVE",
            readiness="DEGRADED",
            capability_health={"chat.completion":"DEGRADED"},
            reason="circuit-open",
            since=NOW,
            retry_after_ms=1000,
            details={},
        )
        result=evaluate_provider(d,attempt_context(d),health)
        self.assertFalse(result.allowed)
        self.assertIn("provider_not_ready",result.reasons)

    def test_session_namespace_isolates_every_required_boundary(self):
        d=descriptor()
        base=attempt_context(d)
        baseline=provider_session_namespace(base)
        variants=[
            attempt_context(d,principal_id="guest",privacy=PrivacyClass.PUBLIC),
            attempt_context(d,audience_scope="GROUP",privacy=PrivacyClass.PUBLIC),
            attempt_context(d,context_space="SHARED",privacy=PrivacyClass.PUBLIC),
            attempt_context(d,context_generation="gen-2"),
            attempt_context(
                descriptor(provider_id="other"),
                privacy=PrivacyClass.OWNER_PRIVATE,
            ),
            attempt_context(
                descriptor(descriptor_digest="desc-v2"),
            ),
            attempt_context(d,tool_schema_digest="schema-v2"),
            attempt_context(d,tool_implementation_digest="tool-impl-v2"),
        ]
        self.assertEqual(len({baseline,*map(provider_session_namespace,variants)}),9)

    def test_voice_and_vision_can_reuse_same_privacy_contract(self):
        for capability in ("vision.infer","speech.asr"):
            d=descriptor(capability=capability)
            result=evaluate_provider(
                d,attempt_context(d,required_capability=capability)
            )
            self.assertTrue(result.allowed,capability)


class ProviderFallbackIntegrationTests(unittest.TestCase):
    def _fixture(self, td):
        store=IdentityStore(Path(td))
        mid=store.add_memory("SYNTHETIC_PROVIDER_PRIVACY_SECRET")
        bridge=ProductMemoryBridge(Path(td),store)
        rows=[
            row for row in store.list_memories()
            if int(row["memory_id"])==int(mid)
        ]
        generation=store.memory_generation()
        expectations=capture_expectations(bridge,rows)
        config=model_adapter._fallback_config("deepseek_web")
        config["fallbacks"]=["deepseek"]
        messages=[{"role":"system","content":rows[0]["text"]}]
        return store,bridge,generation,expectations,config,messages

    def test_provider_digest_change_between_attempts_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,generation,expectations,config,messages=self._fixture(td)
            fallback_before=model_adapter._fallback_config("deepseek")
            approved=model_adapter._provider_descriptor(fallback_before)
            old_model=model_adapter.PROVIDERS["deepseek"]["model"]
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                model_adapter.PROVIDERS["deepseek"]["model"]=old_model+"-changed"
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(RuntimeError):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            approved_provider_digests={
                                "deepseek":{
                                    "descriptor_digest":approved.descriptor_digest,
                                    "capability_digest":approved.capability_digest,
                                }
                            },
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                model_adapter.PROVIDERS["deepseek"]["model"]=old_model
                bridge.close()
                store.close()

    def test_tool_result_invalidation_between_attempts_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,generation,expectations,config,messages=self._fixture(td)
            state={
                "identity_id":"identity-1",
                "principal_id":"owner",
                "audience_scope":"PRIVATE",
                "context_space":"PERSONAL",
                "authorization_digest":"auth-v1",
                "tool_result_digest":"tool-result-v1",
                "tool_implementation_digest":"tool-impl-v1",
                "tool_schema_digest":"tool-schema-v1",
            }
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                state["tool_result_digest"]="tool-result-v2"
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            identity_id="identity-1",
                            authorization_digest="auth-v1",
                            tool_result_digest="tool-result-v1",
                            tool_implementation_digest="tool-impl-v1",
                            tool_schema_digest="tool-schema-v1",
                            source_contains_private_tool_result=True,
                            context_state_provider=lambda:dict(state),
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()

    def test_public_three_provider_chain_still_falls_back(self):
        config=model_adapter._fallback_config("deepseek_web")
        config["fallbacks"]=["qwen","deepseek"]
        calls=[]
        def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
            calls.append(candidate["provider"])
            if len(calls)<3:
                raise RuntimeError("transient")
            return "ok",{}
        with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
            answer,_=model_adapter.chat(
                config,[{"role":"user","content":"public"}],
                required_data_class="PUBLIC",
            )
        self.assertEqual(answer,"ok")
        self.assertEqual(calls,["deepseek_web","qwen","deepseek"])


if __name__=="__main__":
    unittest.main()
