#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

BLOCKING_MARKERS = (
    "pending",
    "deferred",
    "partial",
    "blocked",
    "not_yet",
    "manual_owner_recheck_required",
)

REQUIRED_ACCEPTANCE_IDS = frozenset(
    {
        "identity_restart",
        "identity_model_swap",
        "desktop_qq_continuity",
        "plugin_autostart_restart",
        "private_group_isolation",
        "provider_privacy",
        "correction",
        "erasure_closure",
        "no_resurrection",
        "erase_race",
        "commitment_restart",
        "uncertain_effect",
        "realtime_voice_provider_e2e",
        "avatar_vrm_binding",
        "private_product_e2e",
        "legacy_migration",
        "neko_upstream_upgrade",
        "semantic_interaction_policy",
        "recent_activity_recall",
        "switchable_qwen_clone_voice",
        "proactive_game_timing",
        "startup_event_loop_responsiveness",
        "proactive_interruptibility_authority",
        "runtime_health_self_heal",
        "plugin_capability_floor",
    }
)


def evaluate_matrix(matrix: dict, overlay_root: Path) -> list[str]:
    problems: list[str] = []
    tests = matrix.get("tests")
    if not isinstance(tests, list) or not tests:
        return ["acceptance matrix has no tests"]

    seen: set[str] = set()
    for case in tests:
        case_id = str(case.get("id") or "").strip()
        status = str(case.get("status") or "").strip()
        if not case_id:
            problems.append("acceptance case missing id")
            continue
        if case_id in seen:
            problems.append(f"duplicate acceptance id: {case_id}")
        seen.add(case_id)

        low = status.lower()
        if not status:
            problems.append(f"{case_id}: missing status")
        elif "pass" not in low or any(marker in low for marker in BLOCKING_MARKERS):
            problems.append(f"{case_id}: unresolved status={status}")

        evidence = str(case.get("evidence") or "").strip()
        if not evidence:
            problems.append(f"{case_id}: missing evidence")
        else:
            evidence_path = overlay_root / evidence
            if not evidence_path.is_file():
                problems.append(f"{case_id}: evidence not found: {evidence}")

    missing_required = sorted(REQUIRED_ACCEPTANCE_IDS - seen)
    for case_id in missing_required:
        problems.append(f"missing required acceptance id: {case_id}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed unless every XiaoYu release acceptance case is closed.")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evals" / "acceptance_matrix.json",
    )
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    overlay_root = matrix_path.parents[1]
    matrix = json.loads(matrix_path.read_text(encoding="utf-8-sig"))
    problems = evaluate_matrix(matrix, overlay_root)
    if problems:
        print("BLOCK_RELEASE_READINESS")
        for problem in problems:
            print(f"- {problem}")
        return 5

    print(f"PASS: release readiness ({len(matrix['tests'])}/{len(matrix['tests'])} acceptance cases closed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
