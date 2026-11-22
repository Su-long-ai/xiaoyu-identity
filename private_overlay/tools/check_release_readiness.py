#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
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



def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def evaluate_release_manifest(manifest: dict, overlay_root: Path) -> list[str]:
    problems: list[str] = []

    def load_json(relpath: str) -> dict:
        return json.loads((overlay_root / relpath).read_text(encoding="utf-8-sig"))

    neko = load_json("NEKO_UPSTREAM.lock.json")
    qq = load_json("QQ_PLUGIN_UPSTREAM.lock.json")
    desktop = load_json("DESKTOP_SHELL.lock.json")
    series = load_json("patches/series.json")
    matrix = load_json("evals/acceptance_matrix.json")
    plugin_toml = tomllib.loads(
        (overlay_root / "plugins" / "xiaoyu_interaction_policy" / "plugin.toml").read_text(
            encoding="utf-8"
        )
    )

    if manifest.get("status") != "STABLE":
        problems.append("release manifest status must remain STABLE")
    if manifest.get("no_open_release_blockers") is not True:
        problems.append("release manifest must declare no_open_release_blockers=true")

    external = manifest.get("external_pins", {})
    manifest_neko = external.get("neko", {})
    if manifest_neko.get("commit") != neko.get("tested_commit"):
        problems.append("release manifest N.E.K.O pin does not match NEKO_UPSTREAM.lock.json")

    manifest_qq = external.get("qq_plugin", {})
    if manifest_qq.get("commit") != qq.get("tested_commit"):
        problems.append("release manifest QQ pin does not match QQ_PLUGIN_UPSTREAM.lock.json")
    if manifest_qq.get("version") != qq.get("tested_version"):
        problems.append("release manifest QQ version does not match QQ_PLUGIN_UPSTREAM.lock.json")
    if manifest_qq.get("neko_commit") != qq.get("neko_commit"):
        problems.append("release manifest QQ compatibility N.E.K.O pin is stale")

    manifest_desktop = external.get("desktop_shell", {})
    if manifest_desktop.get("version") != desktop.get("version"):
        problems.append("release manifest desktop shell version does not match DESKTOP_SHELL.lock.json")
    if manifest_desktop.get("entrypoint_sha256") != desktop.get("entrypoint_sha256"):
        problems.append("release manifest desktop shell entrypoint hash is stale")

    patch_files = [str(item.get("file") or "") for item in series.get("patches", [])]
    managed = manifest.get("managed_core_patches", {})
    if managed.get("count") != len(patch_files):
        problems.append("release manifest managed patch count is stale")
    if managed.get("budget") != neko.get("core_patch_budget"):
        problems.append("release manifest managed patch budget is stale")
    if managed.get("files") != patch_files:
        problems.append("release manifest managed patch file list is stale")

    acceptance_ids = [str(item.get("id") or "") for item in matrix.get("tests", [])]
    acceptance = manifest.get("acceptance", {})
    if acceptance.get("closed") != len(acceptance_ids):
        problems.append("release manifest acceptance closed count is stale")
    if acceptance.get("total") != len(acceptance_ids):
        problems.append("release manifest acceptance total count is stale")
    if acceptance.get("ids") != acceptance_ids:
        problems.append("release manifest acceptance IDs are stale")
    if acceptance.get("release_gate") != "PASS":
        problems.append("release manifest release_gate must be PASS")

    plugin_version = (
        plugin_toml.get("plugin", {}).get("version")
        if isinstance(plugin_toml.get("plugin"), dict)
        else None
    )
    manifest_plugin = (
        manifest.get("private_runtime_plugins", {})
        .get("xiaoyu_interaction_policy", {})
    )
    if manifest_plugin.get("source_version") != plugin_version:
        problems.append("release manifest interaction-policy source version is stale")

    expected_bindings = {
        "NEKO_UPSTREAM.lock.json": "NEKO_UPSTREAM.lock.json",
        "QQ_PLUGIN_UPSTREAM.lock.json": "QQ_PLUGIN_UPSTREAM.lock.json",
        "DESKTOP_SHELL.lock.json": "DESKTOP_SHELL.lock.json",
        "patches/series.json": "patches/series.json",
        "evals/acceptance_matrix.json": "evals/acceptance_matrix.json",
        "plugins/manifest.json": "plugins/manifest.json",
        "plugins/xiaoyu_interaction_policy/plugin.toml": "plugins/xiaoyu_interaction_policy/plugin.toml",
    }
    bindings = manifest.get("bindings_git_blob_sha", {})
    for label, relpath in expected_bindings.items():
        expected_sha = _git_blob_sha(overlay_root / relpath)
        if bindings.get(label) != expected_sha:
            problems.append(f"release manifest binding stale: {label}")

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
    release_manifest_path = overlay_root / "release" / "NEKO_OVERLAY_V1_FINAL.json"
    if not release_manifest_path.is_file():
        problems.append("stable release manifest missing: release/NEKO_OVERLAY_V1_FINAL.json")
    else:
        release_manifest = json.loads(
            release_manifest_path.read_text(encoding="utf-8-sig")
        )
        problems.extend(evaluate_release_manifest(release_manifest, overlay_root))
    if problems:
        print("BLOCK_RELEASE_READINESS")
        for problem in problems:
            print(f"- {problem}")
        return 5

    print(
        f"PASS: release readiness ({len(matrix['tests'])}/{len(matrix['tests'])} acceptance cases closed; stable manifest consistent)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
