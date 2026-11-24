#!/usr/bin/env python3
"""Candidate-only second-pass retirement probe for XiaoYu core patches on a0bb.

Reuses the reversible focused-test machinery from
probe_a0bb_core_patch_retirement.py.  A disposable exact-a0bb worktree is
constructed with only managed patches 0001-0009, so 0009 can be reversed
without later 0010+/restart overlap.  Patch 0002 is classified separately by
native blob identity because both its implementation seam and its patch-owned
test are byte-identical between the current c3 pin and a0bb.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from private_overlay.candidates.execution_plane.probe_a0bb_core_patch_retirement import (
    EXPECTED_CANDIDATE_SHA,
    ProbeTarget,
    _probe_one,
    _run,
    _write_result,
)

EXPECTED_CURRENT_PIN_SHA = "c3fc33ff0d32e4a79fd905d1add22d45725071f5"

TARGETS: tuple[ProbeTarget, ...] = (
    ProbeTarget(
        patch="0001-proactive-autostart-idle-gate.patch",
        runner="pytest",
        tests=("tests/unit/test_proactive_sid_guard.py",),
    ),
    ProbeTarget(
        patch="0004-native-ingress-activity-before-backpressure.patch",
        runner="pytest",
        tests=("tests/unit/test_audio_stream_queue.py",),
    ),
    ProbeTarget(
        patch="0006-private-speech-output-gate.patch",
        runner="pytest",
        tests=(
            "tests/unit/test_private_speech_output_gate.py",
            "tests/unit/test_proactive_sid_guard.py",
        ),
    ),
    ProbeTarget(
        patch="0009-proactive-interruptibility-gate.patch",
        runner="pytest",
        tests=(
            "plugin/tests/unit/server/test_xiaoyu_push_origin.py",
            "tests/unit/test_mini_game_invite.py",
            "tests/unit/test_proactive_service_boundary.py",
            "tests/unit/test_proactive_sid_guard.py",
            "tests/unit/test_proactive_vision_revocation.py",
            "tests/unit/test_windows_interruptibility_signal.py",
            "tests/unit/test_xiaoyu_capability_shadow.py",
            "tests/unit/test_xiaoyu_plugin_visible_final_admission.py",
        ),
    ),
)

PATCH_0002 = "0002-full-chat-native-voice-entry.patch"
PATCH_0002_NATIVE_SEAMS = (
    "frontend/react-neko-chat/src/FullChatSurface.tsx",
    "frontend/react-neko-chat/src/App.test.tsx",
)


def _git_head(root: Path) -> str:
    result = _run(("git", "rev-parse", "HEAD"), cwd=root, timeout=30)
    if result["returncode"] != 0:
        return ""
    return result["stdout_tail"].strip()


def _blob_sha(root: Path, relpath: str) -> str:
    result = _run(("git", "rev-parse", f"HEAD:{relpath}"), cwd=root, timeout=30)
    if result["returncode"] != 0:
        return ""
    return result["stdout_tail"].strip()


def _series_prefix(workspace: Path) -> list[str]:
    payload = json.loads((workspace / "private_overlay" / "patches" / "series.json").read_text(encoding="utf-8-sig"))
    patches = payload.get("patches")
    if not isinstance(patches, list) or len(patches) < 9:
        raise ValueError("managed patch series must contain at least 0001-0009")
    names = [str(item.get("file") or "").strip() for item in patches[:9] if isinstance(item, dict)]
    if len(names) != 9 or any(not name for name in names):
        raise ValueError("managed 0001-0009 prefix is invalid")
    return names


def _remove_worktree(repo_root: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree)],
        text=True,
        capture_output=True,
        check=False,
    )
    if worktree.exists():
        shutil.rmtree(worktree)


def probe(
    *,
    workspace: Path,
    candidate_root: Path,
    current_pin_root: Path,
    result_path: Path,
) -> tuple[dict[str, Any], int]:
    workspace = workspace.resolve()
    candidate_root = candidate_root.resolve()
    current_pin_root = current_pin_root.resolve()
    prefix_root = (workspace / "_neko_core_retirement_prefix_candidate").resolve()

    result: dict[str, Any] = {
        "schema_version": 1,
        "candidate_only": True,
        "promotion_authority": False,
        "expected_candidate_sha": EXPECTED_CANDIDATE_SHA,
        "expected_current_pin_sha": EXPECTED_CURRENT_PIN_SHA,
        "candidate_sha": _git_head(candidate_root),
        "current_pin_sha": _git_head(current_pin_root),
        "patch_0002_frozen_native_seam": None,
        "prefix_patch_replay": [],
        "targets": [],
        "retirement_candidates": [],
        "non_retirement_candidates": [],
        "infrastructure_error": None,
    }

    if result["candidate_sha"] != EXPECTED_CANDIDATE_SHA:
        result["infrastructure_error"] = {
            "kind": "candidate_sha",
            "detail": result["candidate_sha"] or "unresolved",
        }
        _write_result(result_path, result)
        return result, 3
    if result["current_pin_sha"] != EXPECTED_CURRENT_PIN_SHA:
        result["infrastructure_error"] = {
            "kind": "current_pin_sha",
            "detail": result["current_pin_sha"] or "unresolved",
        }
        _write_result(result_path, result)
        return result, 4

    frozen_files: dict[str, dict[str, str | bool]] = {}
    frozen = True
    for relpath in PATCH_0002_NATIVE_SEAMS:
        current_blob = _blob_sha(current_pin_root, relpath)
        candidate_blob = _blob_sha(candidate_root, relpath)
        same = bool(current_blob and candidate_blob and current_blob == candidate_blob)
        frozen_files[relpath] = {
            "current_pin_blob": current_blob,
            "candidate_blob": candidate_blob,
            "identical": same,
        }
        frozen = frozen and same
    result["patch_0002_frozen_native_seam"] = {
        "patch": PATCH_0002,
        "files": frozen_files,
        "verdict": (
            "NO_NATIVE_SEAM_CHANGE_NOT_RETIREMENT_CANDIDATE"
            if frozen
            else "NATIVE_SEAM_CHANGED_REQUIRES_FOCUSED_UI_ACCEPTANCE"
        ),
        "retirement_candidate": False,
    }
    if frozen:
        result["non_retirement_candidates"].append(PATCH_0002)

    uv_path = shutil.which("uv")
    if not uv_path:
        result["infrastructure_error"] = {"kind": "probe_environment", "detail": "uv is unavailable"}
        _write_result(result_path, result)
        return result, 2

    _remove_worktree(candidate_root, prefix_root)
    add = _run(
        ("git", "worktree", "add", "--detach", str(prefix_root), "HEAD"),
        cwd=candidate_root,
        timeout=60,
    )
    if add["returncode"] != 0:
        result["infrastructure_error"] = {
            "kind": "worktree_add",
            "detail": add["stderr_tail"] or add["stdout_tail"],
        }
        _write_result(result_path, result)
        return result, 2

    try:
        for patch_name in _series_prefix(workspace):
            patch_path = workspace / "private_overlay" / "patches" / patch_name
            check = _run(("git", "apply", "--check", "--", str(patch_path)), cwd=prefix_root, timeout=60)
            replay = {"patch": patch_name, "check": check}
            result["prefix_patch_replay"].append(replay)
            if check["returncode"] != 0:
                raise RuntimeError(f"prefix patch check failed: {patch_name}")
            apply = _run(("git", "apply", "--", str(patch_path)), cwd=prefix_root, timeout=60)
            replay["apply"] = apply
            if apply["returncode"] != 0:
                raise RuntimeError(f"prefix patch apply failed: {patch_name}")

        for target in TARGETS:
            item = _probe_one(
                workspace=workspace,
                candidate_root=prefix_root,
                target=target,
                uv_path=uv_path,
            )
            result["targets"].append(item)
            if item["retirement_candidate"]:
                result["retirement_candidates"].append(target.patch)
            else:
                result["non_retirement_candidates"].append(target.patch)
    except Exception as exc:
        result["infrastructure_error"] = {
            "kind": type(exc).__name__,
            "detail": str(exc),
        }
        _write_result(result_path, result)
        return result, 2
    finally:
        _remove_worktree(candidate_root, prefix_root)

    _write_result(result_path, result)
    return result, 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--current-pin-root", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result, code = probe(
        workspace=args.workspace,
        candidate_root=args.candidate_root,
        current_pin_root=args.current_pin_root,
        result_path=args.result,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
