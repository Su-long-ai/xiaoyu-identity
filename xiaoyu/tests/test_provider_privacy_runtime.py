from __future__ import annotations

import http.client
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
    capture_context_fence,
    capture_expectations,
    dual_guarded_chat,
)
from xiaoyu.runtime.provider_registry import (
    AUDIENCE_RESET_COMPONENTS,
    PrivacyClass,
    ProviderAttemptContext,
    ProviderDescriptor,
    ProviderHealth,
    apply_audience_reset,
    audience_reset_decision,
    evaluate_provider,
    provider_session_namespace,
    standing_approval_binding_digest,
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
    owner_principal_id="owner",
    audience_scope="PRIVATE",
    context_space="PERSONAL",
    context_generation="gen-1",
    privacy=PrivacyClass.OWNER_PRIVATE,
    required_capability=None,
    expected_descriptor_digest=None,
    expected_capability_digest=None,
    expected_approval_binding_digest=None,
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
        owner_principal_id=owner_principal_id,
        expected_descriptor_digest=expected_descriptor_digest,
        expected_capability_digest=expected_capability_digest,
        expected_approval_binding_digest=expected_approval_binding_digest,
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

    def test_ollama_is_local_only_eligible_but_local_proxy_is_not_assumed_local(self):
        ollama=model_adapter._provider_descriptor(
            model_adapter._fallback_config("ollama")
        )
        self.assertEqual(ollama.endpoint_scope,"LOCAL")
        self.assertIn(PrivacyClass.LOCAL_ONLY,ollama.privacy_classes)
        result=evaluate_provider(
            ollama,
            attempt_context(ollama,privacy=PrivacyClass.LOCAL_ONLY),
        )
        self.assertTrue(result.allowed)

        web_proxy=model_adapter._provider_descriptor(
            model_adapter._fallback_config("deepseek_web")
        )
        self.assertEqual(web_proxy.endpoint_scope,"REMOTE")
        self.assertNotIn(PrivacyClass.LOCAL_ONLY,web_proxy.privacy_classes)

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

    def test_local_only_private_tool_result_keeps_local_boundary_and_owner_scope(self):
        remote=descriptor(
            privacy=(PrivacyClass.PUBLIC,PrivacyClass.OWNER_PRIVATE),
            endpoint_scope="REMOTE",
        )
        remote_result=evaluate_provider(
            remote,
            attempt_context(
                remote,
                privacy=PrivacyClass.LOCAL_ONLY,
                private_tool=True,
                tool_result_digest="tool-result-v1",
            ),
        )
        self.assertFalse(remote_result.allowed)
        self.assertIn("privacy_class_ineligible",remote_result.reasons)
        self.assertIn("local_only_requires_local_provider",remote_result.reasons)

        local=descriptor(
            privacy=(PrivacyClass.PUBLIC,PrivacyClass.LOCAL_ONLY),
            endpoint_scope="LOCAL",
        )
        guest_result=evaluate_provider(
            local,
            attempt_context(
                local,
                principal_id="guest",
                owner_principal_id="owner",
                privacy=PrivacyClass.LOCAL_ONLY,
                private_tool=True,
                tool_result_digest="tool-result-v1",
            ),
        )
        self.assertFalse(guest_result.allowed)
        self.assertIn("owner_private_principal_mismatch",guest_result.reasons)

    def test_owner_private_uses_positive_owner_binding_not_principal_denylist(self):
        d=descriptor()
        member=evaluate_provider(
            d,
            attempt_context(
                d,
                principal_id="member-42",
                owner_principal_id="owner",
            ),
        )
        self.assertFalse(member.allowed)
        self.assertIn("owner_private_principal_mismatch",member.reasons)

        canonical_owner=evaluate_provider(
            d,
            attempt_context(
                d,
                principal_id="principal-abc",
                owner_principal_id="principal-abc",
            ),
        )
        self.assertTrue(canonical_owner.allowed)

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

    def test_standing_approval_is_bound_to_provider_and_tool_digests(self):
        d=descriptor()
        baseline=attempt_context(
            d,
            tool_implementation_digest="tool-impl-v1",
            tool_schema_digest="tool-schema-v1",
        )
        approval=standing_approval_binding_digest(d,baseline)
        approved=attempt_context(
            d,
            tool_implementation_digest="tool-impl-v1",
            tool_schema_digest="tool-schema-v1",
            expected_approval_binding_digest=approval,
        )
        self.assertTrue(evaluate_provider(d,approved).allowed)

        changed_tool=attempt_context(
            d,
            tool_implementation_digest="tool-impl-v1",
            tool_schema_digest="tool-schema-v2",
            expected_approval_binding_digest=approval,
        )
        self.assertIn(
            "approval_binding_changed",
            evaluate_provider(d,changed_tool).reasons,
        )

        changed_provider=descriptor(implementation_digest="impl-v2")
        changed_provider_context=attempt_context(
            changed_provider,
            tool_implementation_digest="tool-impl-v1",
            tool_schema_digest="tool-schema-v1",
            expected_approval_binding_digest=approval,
        )
        self.assertIn(
            "approval_binding_changed",
            evaluate_provider(
                changed_provider,changed_provider_context
            ).reasons,
        )

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

    def test_stale_session_namespace_fuzz(self):
        namespaces=set()
        for principal in ("owner","guest"):
            for audience in ("PRIVATE","GROUP"):
                for space in ("PERSONAL","SHARED"):
                    for generation in ("gen-1","gen-2"):
                        for provider in ("provider-a","provider-b"):
                            d=descriptor(provider_id=provider)
                            ctx=attempt_context(
                                d,
                                principal_id=principal,
                                audience_scope=audience,
                                context_space=space,
                                context_generation=generation,
                                privacy=PrivacyClass.PUBLIC,
                            )
                            namespaces.add(provider_session_namespace(ctx))
        self.assertEqual(len(namespaces),32)


    def test_owner_to_group_guest_and_shared_require_full_context_reset(self):
        d=descriptor()
        owner=attempt_context(d)
        targets=[
            attempt_context(d,audience_scope="GROUP",privacy=PrivacyClass.PUBLIC),
            attempt_context(d,principal_id="guest",privacy=PrivacyClass.PUBLIC),
            attempt_context(d,context_space="SHARED",privacy=PrivacyClass.PUBLIC),
        ]
        for target in targets:
            decision=audience_reset_decision(owner,target)
            self.assertTrue(decision.required)
            self.assertEqual(
                set(decision.clear_components),
                set(AUDIENCE_RESET_COMPONENTS),
            )
        self.assertFalse(audience_reset_decision(owner,owner).required)

    def test_audience_reset_actually_removes_private_derived_behavior_state(self):
        d=descriptor()
        owner=attempt_context(d)
        guest=attempt_context(
            d,
            principal_id="guest",
            audience_scope="GUEST",
            context_space="GUEST",
            privacy=PrivacyClass.PUBLIC,
        )
        state={
            "private_retrieval":{"facts":["favorite-private-topic"]},
            "private_profile":{"tone":"owner-derived-style"},
            "cached_context":{"recommendation_bias":"owner-history-derived"},
            "provider_session_kv":{"hidden_state":"owner-private-derived"},
            "tool_delegations":{"calendar":"owner-grant"},
            "retained_messages":[{"role":"system","content":"owner-private"}],
            "surface_state":{"last_private_surface":"desktop"},
            "public_health":{"provider-a":"READY"},
        }
        decision=apply_audience_reset(state,owner,guest)
        self.assertTrue(decision.required)
        for key in AUDIENCE_RESET_COMPONENTS:
            self.assertNotIn(key,state)
        self.assertEqual(
            state,
            {"public_health":{"provider-a":"READY"}},
        )

    def test_same_scope_does_not_destroy_runtime_state(self):
        d=descriptor()
        owner=attempt_context(d)
        state={
            "cached_context":{"safe":"same-scope"},
            "public_health":{"provider-a":"READY"},
        }
        before=dict(state)
        decision=apply_audience_reset(state,owner,owner)
        self.assertFalse(decision.required)
        self.assertEqual(state,before)

    def test_model_switch_preserves_authority_but_never_session_namespace(self):
        first=descriptor(provider_id="provider-a")
        second=descriptor(provider_id="provider-b")
        first_context=attempt_context(first)
        second_context=attempt_context(second)
        self.assertTrue(evaluate_provider(first,first_context).allowed)
        self.assertTrue(evaluate_provider(second,second_context).allowed)
        self.assertEqual(first_context.identity_id,second_context.identity_id)
        self.assertEqual(first_context.principal_id,second_context.principal_id)
        self.assertNotEqual(
            provider_session_namespace(first_context),
            provider_session_namespace(second_context),
        )


    def test_dispatch_callback_fires_before_socket_output_failure(self):
        events=[]
        conn=model_adapter._DispatchHTTPConnection(
            "127.0.0.1",
            on_dispatched=lambda:events.append("dispatched"),
        )
        with patch.object(
            http.client.HTTPConnection,
            "_send_output",
            side_effect=TimeoutError("partial-send-timeout"),
        ):
            with self.assertRaises(TimeoutError):
                conn._send_output(b"PRIVATE_BODY")
        self.assertEqual(events,["dispatched"])
        with patch.object(
            http.client.HTTPConnection,
            "_send_output",
            side_effect=TimeoutError("retry"),
        ):
            with self.assertRaises(TimeoutError):
                conn._send_output(b"PRIVATE_BODY")
        self.assertEqual(events,["dispatched"])


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
        return store,bridge,mid,generation,expectations,config,messages

    def test_provider_digest_change_between_attempts_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
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
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
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

    def test_unclassified_direct_chat_never_crosses_provider_boundary(self):
        config=model_adapter._fallback_config("deepseek_web")
        config["fallbacks"]=["qwen","deepseek"]
        calls=[]
        def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
            calls.append(candidate["provider"])
            raise RuntimeError("primary failed")
        with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
            with self.assertRaises(RuntimeError):
                model_adapter.chat(
                    config,[{"role":"user","content":"unclassified"}]
                )
        self.assertEqual(calls,["deepseek_web"])

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


    def test_memory_correction_between_attempts_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                store.correct_memory(mid,"CORRECTED_PRIVATE_CONTEXT")
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                        )
                self.assertEqual(calls,["deepseek_web"])
                self.assertNotEqual(store.memory_generation(),generation)
            finally:
                bridge.close()
                store.close()

    def test_physical_memory_delete_between_attempts_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                with store.conn:
                    store.conn.execute(
                        "DELETE FROM memories WHERE memory_id=?",(int(mid),)
                    )
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()

    def test_incomplete_live_scope_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                calls.append(candidate["provider"])
                return "must-not-run",{}
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            identity_id="identity-1",
                            context_state_provider=lambda:{
                                "audience_scope":"PRIVATE",
                                "context_space":"PERSONAL",
                            },
                        )
                self.assertEqual(calls,[])
            finally:
                bridge.close()
                store.close()


    def test_private_three_provider_chain_still_falls_back_when_scope_is_stable(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            config["fallbacks"]=["qwen","deepseek"]
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                if len(calls)<3:
                    raise RuntimeError("transient")
                return "ok",{}
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    answer,_=dual_guarded_chat(
                        model_adapter.chat,config,messages,
                        store.db_path,bridge.db_path,generation,expectations,
                    )
                self.assertEqual(answer,"ok")
                self.assertEqual(calls,["deepseek_web","qwen","deepseek"])
            finally:
                bridge.close()
                store.close()

    def test_authorization_change_between_attempts_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            state={
                "identity_id":"identity-1",
                "principal_id":"owner",
                "audience_scope":"PRIVATE",
                "context_space":"PERSONAL",
                "authorization_digest":"auth-v1",
                "tool_result_digest":None,
                "tool_implementation_digest":None,
                "tool_schema_digest":None,
            }
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                state["authorization_digest"]="auth-v2"
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            identity_id="identity-1",
                            authorization_digest="auth-v1",
                            context_state_provider=lambda:dict(state),
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()

    def test_fallback_privacy_eligibility_change_is_recomputed(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            old=model_adapter.DEFAULT_ALLOWED_DATA_CLASSES["deepseek"]
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                model_adapter.DEFAULT_ALLOWED_DATA_CLASSES["deepseek"]=("PUBLIC",)
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(RuntimeError):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                model_adapter.DEFAULT_ALLOWED_DATA_CLASSES["deepseek"]=old
                bridge.close()
                store.close()

    def test_response_after_physical_delete_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                with store.conn:
                    store.conn.execute(
                        "DELETE FROM memories WHERE memory_id=?",(int(mid),)
                    )
                return "stale-success",{}
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()

    def test_unselected_physical_delete_invalidates_full_prompt_fence(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            unselected=store.add_memory("UNSELECTED_PRIVATE_MEMORY")
            fence=capture_context_fence(store)
            generation_after_add=store.memory_generation()
            with store.conn:
                store.conn.execute(
                    "DELETE FROM memories WHERE memory_id=?",(int(unselected),)
                )
            # Direct erasure can predate bridge tombstone reconciliation and
            # need not advance the legacy generation setting; the full prompt
            # fence must still notice it.
            self.assertEqual(
                store.memory_generation(),
                generation_after_add,
            )
            self.assertNotEqual(capture_context_fence(store),fence)
            try:
                with self.assertRaises(FreshnessChanged):
                    dual_guarded_chat(
                        model_adapter.chat,config,messages,
                        store.db_path,bridge.db_path,
                        generation_after_add,[],
                        expected_context_fence=fence,
                    )
            finally:
                bridge.close()
                store.close()


    def test_provider_health_transition_during_chain_skips_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            readiness={"deepseek_web":"READY","deepseek":"READY"}
            calls=[]
            def health(descriptor):
                state=readiness.get(descriptor.provider_id,"READY")
                return ProviderHealth(
                    liveness="ALIVE",
                    readiness=state,
                    capability_health={"chat.completion":state},
                    reason=None if state=="READY" else "degraded-during-chain",
                    since=NOW,
                    retry_after_ms=None,
                    details={},
                )
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                readiness["deepseek"]="DEGRADED"
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(RuntimeError):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            provider_health=health,
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()


    def test_fallback_audit_records_every_allowed_and_denied_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            store,bridge,mid,generation,expectations,config,messages=self._fixture(td)
            config["fallbacks"]=["custom"]
            audits=[]
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(RuntimeError):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            attempt_audit=audits.append,
                        )
                self.assertEqual(calls,["deepseek_web"])
                self.assertEqual(
                    [item.provider_id for item in audits],
                    ["deepseek_web","custom"],
                )
                self.assertTrue(audits[0].allowed)
                self.assertFalse(audits[1].allowed)
                self.assertIn("privacy_class_ineligible",audits[1].reasons)
                self.assertNotEqual(
                    audits[0].session_namespace,
                    audits[1].session_namespace,
                )
            finally:
                bridge.close()
                store.close()

    def test_scope_switch_matrix_blocks_second_private_attempt(self):
        cases=[
            ("principal_id","guest"),
            ("audience_scope","GROUP"),
            ("context_space","SHARED"),
            ("identity_id","identity-2"),
        ]
        for field,new_value in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as td:
                    (
                        store,bridge,mid,generation,
                        expectations,config,messages,
                    )=self._fixture(td)
                    state={
                        "identity_id":"identity-1",
                        "principal_id":"owner",
                        "audience_scope":"PRIVATE",
                        "context_space":"PERSONAL",
                        "authorization_digest":"auth-v1",
                        "tool_result_digest":None,
                        "tool_implementation_digest":None,
                        "tool_schema_digest":None,
                    }
                    calls=[]
                    def fake_once(
                        candidate,attempt_messages,max_tokens,timeout,on_dispatched
                    ):
                        if on_dispatched:
                            on_dispatched()
                        calls.append(candidate["provider"])
                        state[field]=new_value
                        raise RuntimeError("primary failed")
                    try:
                        with patch.object(
                            model_adapter,"_chat_once",side_effect=fake_once
                        ):
                            with self.assertRaises(FreshnessChanged):
                                dual_guarded_chat(
                                    model_adapter.chat,config,messages,
                                    store.db_path,bridge.db_path,
                                    generation,expectations,
                                    identity_id="identity-1",
                                    principal_id="owner",
                                    audience_scope="PRIVATE",
                                    context_space="PERSONAL",
                                    authorization_digest="auth-v1",
                                    context_state_provider=lambda:dict(state),
                                )
                        self.assertEqual(calls,["deepseek_web"])
                    finally:
                        bridge.close()
                        store.close()

    def test_private_tool_invalidation_matrix_blocks_second_attempt(self):
        for field in (
            "tool_result_digest",
            "tool_implementation_digest",
            "tool_schema_digest",
        ):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as td:
                    (
                        store,bridge,mid,generation,
                        expectations,config,messages,
                    )=self._fixture(td)
                    state={
                        "identity_id":"identity-1",
                        "principal_id":"owner",
                        "audience_scope":"PRIVATE",
                        "context_space":"PERSONAL",
                        "authorization_digest":"auth-v1",
                        "tool_result_digest":"result-v1",
                        "tool_implementation_digest":"impl-v1",
                        "tool_schema_digest":"schema-v1",
                    }
                    calls=[]
                    def fake_once(
                        candidate,attempt_messages,max_tokens,timeout,on_dispatched
                    ):
                        if on_dispatched:
                            on_dispatched()
                        calls.append(candidate["provider"])
                        state[field]=state[field]+"-changed"
                        raise RuntimeError("primary failed")
                    try:
                        with patch.object(
                            model_adapter,"_chat_once",side_effect=fake_once
                        ):
                            with self.assertRaises(FreshnessChanged):
                                dual_guarded_chat(
                                    model_adapter.chat,config,messages,
                                    store.db_path,bridge.db_path,
                                    generation,expectations,
                                    identity_id="identity-1",
                                    authorization_digest="auth-v1",
                                    tool_result_digest="result-v1",
                                    tool_implementation_digest="impl-v1",
                                    tool_schema_digest="schema-v1",
                                    source_contains_private_tool_result=True,
                                    context_state_provider=lambda:dict(state),
                                )
                        self.assertEqual(calls,["deepseek_web"])
                    finally:
                        bridge.close()
                        store.close()


if __name__=="__main__":
    unittest.main()
