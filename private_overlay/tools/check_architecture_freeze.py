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

    qq_lock = json.loads((ROOT / "QQ_PLUGIN_UPSTREAM.lock.json").read_text(encoding="utf-8-sig"))
    if qq_lock.get("tested_commit") != "54acf36bf978edad4757e5fffc743c5618360700":
        raise SystemExit("QQ delivery-floor audit no longer matches the pinned plugin commit")

    print("PASS: architecture freeze and delivery floor contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
