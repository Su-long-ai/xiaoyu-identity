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
    base_patch_budget = int(patch_policy.get("base_managed_patch_budget", 999))
    correctness_exception_budget = int(
        patch_policy.get("correctness_exception_budget", 999)
    )
    max_patch_budget = int(patch_policy.get("max_managed_patch_budget", 999))
    if base_patch_budget < 1 or base_patch_budget > 10:
        raise SystemExit("base managed patch budget must remain in 1..10")
    if correctness_exception_budget < 0 or correctness_exception_budget > 9:
        raise SystemExit("correctness exception patch budget must remain in 0..9")
    if max_patch_budget != base_patch_budget + correctness_exception_budget:
        raise SystemExit(
            "max managed patch budget must equal base budget plus correctness exceptions"
        )

    exception_policy_rel = str(
        patch_policy.get("correctness_exception_policy") or ""
    ).strip()
    exception_policy_path = ROOT / exception_policy_rel
    if not exception_policy_rel or not exception_policy_path.is_file():
        raise SystemExit(
            f"correctness exception policy missing: {exception_policy_rel}"
        )
    exception_policy = json.loads(
        exception_policy_path.read_text(encoding="utf-8-sig")
    )
    if (
        exception_policy.get("policy_id")
        != "XIAOYU_CORE_PATCH_CORRECTNESS_EXCEPTIONS_V1"
    ):
        raise SystemExit("correctness exception policy id changed or missing")
    if int(exception_policy.get("base_managed_patch_budget", -1)) != base_patch_budget:
        raise SystemExit("correctness exception policy base budget drifted")
    if (
        int(exception_policy.get("correctness_exception_budget", -1))
        != correctness_exception_budget
    ):
        raise SystemExit("correctness exception policy exception budget drifted")
    if int(exception_policy.get("max_managed_patch_budget", -1)) != max_patch_budget:
        raise SystemExit("correctness exception policy max budget drifted")

    series = json.loads(
        (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
    )
    managed_patch_files = [
        str(item.get("file") or "") for item in series.get("patches", [])
    ]
    if len(managed_patch_files) > max_patch_budget:
        raise SystemExit("managed patch queue exceeds total architecture budget")

    exceptions = exception_policy.get("exceptions")
    if not isinstance(exceptions, list):
        raise SystemExit("correctness exception policy exceptions must be a list")
    exception_files = [str(item.get("file") or "") for item in exceptions]
    if len(exception_files) != len(set(exception_files)):
        raise SystemExit("duplicate correctness exception patch entry")
    if len(exception_files) > correctness_exception_budget:
        raise SystemExit("correctness exception patch queue exceeds exception budget")
    if any(name not in managed_patch_files for name in exception_files):
        raise SystemExit("correctness exception patch is not in the managed series")
    if len(managed_patch_files) - len(exception_files) > base_patch_budget:
        raise SystemExit("non-exception managed patch queue exceeds base budget")

    reviews = json.loads(
        (ROOT / "governance" / "reuse_reviews.json").read_text(
            encoding="utf-8-sig"
        )
    )
    review_ids = {
        str(item.get("id") or "")
        for item in reviews.get("reviews", [])
        if item.get("status") == "approved"
    }
    for item in exceptions:
        filename = str(item.get("file") or "")
        review_id = str(item.get("reuse_review_id") or "")
        evidence = str(item.get("evidence") or "")
        retirement = str(item.get("retirement_condition") or "").strip()
        group = str(item.get("group") or "").strip()
        if review_id != f"patch:{filename}" or review_id not in review_ids:
            raise SystemExit(
                f"correctness exception lacks exact approved patch review: {filename}"
            )
        if not evidence or not (ROOT / evidence).is_file():
            raise SystemExit(
                f"correctness exception acceptance evidence missing: {filename}"
            )
        if not retirement:
            raise SystemExit(
                f"correctness exception retirement condition missing: {filename}"
            )
        if not group:
            raise SystemExit(
                f"correctness exception promotion group missing: {filename}"
            )

    groups = exception_policy.get("promotion_groups")
    if not isinstance(groups, list) or not groups:
        raise SystemExit("correctness exception promotion groups missing")
    grouped_files: set[str] = set()
    for group in groups:
        group_id = str(group.get("id") or "").strip()
        blockers = group.get("blockers_closed")
        patches = group.get("patches")
        evidence = group.get("evidence")
        if not group_id:
            raise SystemExit("correctness exception promotion group missing id")
        if not isinstance(blockers, list) or not blockers:
            raise SystemExit(
                f"correctness exception group has no reproduced blockers: {group_id}"
            )
        if not isinstance(patches, list) or not patches:
            raise SystemExit(
                f"correctness exception group has no patches: {group_id}"
            )
        if not isinstance(evidence, list) or not evidence:
            raise SystemExit(
                f"correctness exception group has no evidence: {group_id}"
            )
        for relpath in evidence:
            if not (ROOT / str(relpath)).is_file():
                raise SystemExit(
                    f"correctness exception group evidence missing: {group_id}: {relpath}"
                )
        for filename in patches:
            filename = str(filename)
            if filename not in exception_files:
                raise SystemExit(
                    f"correctness exception group references unadmitted patch: {group_id}: {filename}"
                )
            grouped_files.add(filename)
    if grouped_files != set(exception_files):
        raise SystemExit(
            "every correctness exception patch must belong to a blocker-closing promotion group"
        )

    candidate_only = {
        Path(str(item)).name
        for item in exception_policy.get("candidate_only_exclusions", [])
    }
    if any(name in managed_patch_files for name in candidate_only):
        raise SystemExit(
            "candidate-only host-restart continuity patch was promoted without closing its parent blocker"
        )

    lock = json.loads(
        (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
    )
    if int(lock.get("core_patch_budget", -1)) != max_patch_budget:
        raise SystemExit("N.E.K.O lock core patch budget drifted from architecture freeze")

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
