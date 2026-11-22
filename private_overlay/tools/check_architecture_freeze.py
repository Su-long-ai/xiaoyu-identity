from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str) -> dict:
    path = ROOT / "governance" / name
    if not path.is_file():
        raise SystemExit(f"missing governance contract: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    arch = load_json("architecture_freeze.json")
    delivery = load_json("delivery_floor_v1.json")

    if arch.get("decision_id") != "XIAOYU_ARCHITECTURE_FREEZE_V1":
        raise SystemExit("architecture freeze id changed or missing")
    if arch.get("companion_runtime_authority") != "neko_native":
        raise SystemExit("N.E.K.O must remain the sole companion runtime authority")
    if arch.get("extension_plane_default") != "neko_plugin_sdk":
        raise SystemExit("N.E.K.O Plugin SDK must remain the default extension plane")

    boundaries = set(arch.get("external_execution_boundaries", []))
    required_boundaries = {"neko_external_agent", "neko_mcp", "neko_plugin_sdk"}
    if not required_boundaries.issubset(boundaries):
        raise SystemExit("external execution must stay behind N.E.K.O boundaries")

    memory = arch.get("memory", {})
    if memory.get("authority") != "neko_native":
        raise SystemExit("memory authority must remain N.E.K.O native")
    if memory.get("external_candidates_mode") != "shadow_only_until_explicit_promotion":
        raise SystemExit("external memory candidates must stay shadow-only until promotion")

    forbidden = set(arch.get("forbidden_xiaoyu_duplicate_authorities", []))
    required_forbidden = {
        "plugin_host",
        "model_gateway",
        "vector_store",
        "memory_runtime",
        "agent_runtime",
        "http_pool",
        "credential_store",
    }
    if not required_forbidden.issubset(forbidden):
        raise SystemExit("architecture freeze no longer forbids all duplicate authorities")

    patch_policy = arch.get("private_core_patch_policy", {})
    if patch_policy.get("mode") != "exception_only":
        raise SystemExit("private core patches must remain exception-only")
    if patch_policy.get("requires_reuse_review") is not True:
        raise SystemExit("private core patches must remain reuse-reviewed")
    if patch_policy.get("retire_when_native_extension_exists") is not True:
        raise SystemExit("native extension points must retire equivalent private patches")
    if int(patch_policy.get("max_managed_patch_budget", 999)) > 10:
        raise SystemExit("managed patch budget may not exceed 10")
    retirement_evidence = str(patch_policy.get("latest_retirement_audit") or "")
    if not retirement_evidence or not (ROOT / retirement_evidence).is_file():
        raise SystemExit(f"latest patch-retirement audit missing: {retirement_evidence}")
    if arch.get("principles", {}).get("no_second_runtime") is not True:
        raise SystemExit("second XiaoYu runtime is forbidden")

    if delivery.get("contract_id") != "XIAOYU_DELIVERY_FLOOR_V1":
        raise SystemExit("delivery floor contract id changed or missing")
    if delivery.get("implementation_mode") != "contract_only_no_second_runtime":
        raise SystemExit("delivery floor must remain a contract, not a second runtime")
    if delivery.get("publication_authority") != "neko_native":
        raise SystemExit("N.E.K.O must remain publication authority")
    if set(delivery.get("decisions", [])) != {"ALLOW", "HOLD", "DROP"}:
        raise SystemExit("delivery decisions must remain ALLOW/HOLD/DROP")

    global_req = delivery.get("global_requirements", {})
    required_true = {
        "latest_state_recheck_before_claim_or_publication",
        "audience_and_privacy_must_be_valid_at_delivery",
        "nonessential_output_must_respect_interruptibility",
        "text_and_paired_tts_must_share_one_admission",
        "policy_layer_must_not_publish_directly",
        "native_delivery_remains_effect_authority",
        "surface_specific_interruptibility_is_allowed",
        "plugin_visible_sinks_require_final_surface_admission",
    }
    if any(global_req.get(key) is not True for key in required_true):
        raise SystemExit("delivery floor global requirements were weakened")

    classes = delivery.get("output_classes", {})
    required_classes = {
        "ordinary_reply",
        "proactive",
        "work_break",
        "game_invite",
        "agent_result",
        "qq_outbound",
    }
    if set(classes) != required_classes:
        raise SystemExit("delivery floor output class inventory changed unexpectedly")

    expected = {
        "ordinary_reply": "patch:0006-private-speech-output-gate.patch",
        "proactive": "patch:0009-proactive-interruptibility-gate.patch",
        "work_break": "patch:0009-proactive-interruptibility-gate.patch",
        "game_invite": "patch:0009-proactive-interruptibility-gate.patch",
        "agent_result": "neko_native:task_result_outbox_to_proactive_callback",
        "qq_outbound": "external:pinned_qq_auto_reply_surface_floor",
    }
    for output_class, adapter in expected.items():
        item = classes[output_class]
        if item.get("current_enforcement_adapter") != adapter:
            raise SystemExit(f"{output_class} enforcement adapter drifted")
        evidence = str(item.get("evidence") or "")
        if not evidence or not (ROOT / evidence).is_file():
            raise SystemExit(f"{output_class} evidence missing: {evidence}")

    patch_files = {path.name for path in (ROOT / "patches").glob("*.patch")}
    for adapter in expected.values():
        if not adapter.startswith("patch:"):
            continue
        patch_name = adapter.removeprefix("patch:")
        if patch_name not in patch_files:
            raise SystemExit(f"declared delivery adapter missing: {patch_name}")

    uncovered = delivery.get("blocked_uncovered_output_classes", {})
    if uncovered:
        raise SystemExit(
            "delivery floor still has blocked/uncovered user-visible output classes: "
            + ", ".join(sorted(uncovered))
        )

    managed = delivery.get("managed_extension_output_classes", {})
    required_managed = {"desktop_notification", "plugin_triggered_output"}
    if set(managed) != required_managed:
        raise SystemExit("managed delivery extension output class inventory drifted")
    for output_class in sorted(required_managed):
        item = managed[output_class]
        if item.get("coverage_status") != "MANAGED_EXTENSION_ACTIVE":
            raise SystemExit(f"{output_class} managed delivery coverage is not active")
        adapter = str(item.get("current_enforcement_adapter") or "")
        if not adapter:
            raise SystemExit(f"{output_class} managed delivery adapter missing")
        evidence = str(item.get("evidence") or "")
        if not evidence or not (ROOT / evidence).is_file():
            raise SystemExit(f"{output_class} managed delivery evidence missing: {evidence}")
        promotion = item.get("promotion_evidence") or {}
        if (
            promotion.get("conclusion") != "success"
            or not promotion.get("run_id")
            or not promotion.get("head_sha")
        ):
            raise SystemExit(f"{output_class} managed delivery promotion evidence is not green")
        if not str(item.get("retirement_condition") or "").strip():
            raise SystemExit(f"{output_class} managed delivery retirement condition missing")
        if adapter.startswith("patch:"):
            patch_name = adapter.removeprefix("patch:")
            if patch_name not in patch_files:
                raise SystemExit(
                    f"{output_class} managed delivery patch missing: {patch_name}"
                )

    qq_lock = json.loads((ROOT / "QQ_PLUGIN_UPSTREAM.lock.json").read_text(encoding="utf-8-sig"))
    if qq_lock.get("tested_commit") != "54acf36bf978edad4757e5fffc743c5618360700":
        raise SystemExit("QQ delivery-floor audit no longer matches the pinned plugin commit")

    execution = load_json("execution_contract_v1.json")
    if execution.get("contract_id") != "XIAOYU_EXTERNAL_EXECUTION_V1":
        raise SystemExit("external execution contract id changed or missing")
    if execution.get("implementation_mode") != "reuse_neko_native_no_second_agent_runtime":
        raise SystemExit("external execution must reuse N.E.K.O instead of creating a second runtime")
    authority = execution.get("authority", {})
    for key in ("commission_ledger", "permission_gate", "capability_gateway", "result_outbox"):
        if authority.get(key) != "nekoclaw_host":
            raise SystemExit(f"execution authority drifted: {key}")
    for key in ("publication", "identity_and_persona", "memory"):
        if authority.get(key) != "neko_native":
            raise SystemExit(f"N.E.K.O authority drifted: {key}")
    routing = execution.get("routing", {})
    if routing.get("single_step") != "neko_plugin_direct":
        raise SystemExit("single-step execution must stay on native plugin direct dispatch")
    if routing.get("multi_step") != "nekoclaw_task_agent":
        raise SystemExit("multi-step execution must stay on NekoClaw")
    if routing.get("capabilities") != "nekoclaw_mcp_capability_gateway":
        raise SystemExit("external capabilities must stay behind the NekoClaw MCP gateway")
    seams = execution.get("runtime_seam", {})
    if seams.get("builtin", {}).get("allowed") is not True:
        raise SystemExit("built-in NekoClaw runtime must remain available")
    dsh = seams.get("dsh", {})
    if (
        dsh.get("allowed") is not True
        or dsh.get("transport") != "ACP_JSON_RPC_stdio"
        or dsh.get("host_permission_guard_required") is not True
        or dsh.get("fallback_to_builtin") is not True
    ):
        raise SystemExit("dsh may only remain the host-guarded ACP alternate runtime")
    for unsupported in ("openclaw", "hermes"):
        if seams.get(unsupported, {}).get("allowed") is not False:
            raise SystemExit(f"{unsupported} is not an approved N.E.K.O runtime seam")
    ext = execution.get("external_capability_policy", {})
    required_ext = {
        "mcp_servers_are_individually_permissioned",
        "credentials_remain_host_owned",
        "external_tools_do_not_gain_identity_authority",
        "external_tools_do_not_gain_memory_authority",
        "external_tools_do_not_publish_user_visible_output_directly",
    }
    if ext.get("preferred_boundary") != "MCP" or any(ext.get(key) is not True for key in required_ext):
        raise SystemExit("external capability boundary or authority policy was weakened")
    forbidden_exec = {
        "xiaoyu_agent_orchestrator",
        "xiaoyu_permission_store",
        "xiaoyu_task_ledger",
        "xiaoyu_capability_gateway",
        "xiaoyu_external_agent_memory_authority",
        "direct_external_agent_publication",
    }
    if not forbidden_exec.issubset(set(execution.get("forbidden", []))):
        raise SystemExit("execution contract no longer forbids duplicate XiaoYu agent authorities")
    activation = execution.get("activation", {})
    if activation.get("enable_agent_master_in_this_change") is not False:
        raise SystemExit("architecture freeze must not silently enable Agent master")
    if activation.get("install_dsh_in_this_change") is not False:
        raise SystemExit("architecture freeze must not silently install dsh")
    exec_evidence = str(execution.get("evidence") or "")
    if not exec_evidence or not (ROOT / exec_evidence).is_file():
        raise SystemExit(f"execution contract evidence missing: {exec_evidence}")

    print("PASS: architecture, delivery and external execution contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
