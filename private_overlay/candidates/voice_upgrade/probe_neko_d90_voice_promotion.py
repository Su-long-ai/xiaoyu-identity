#!/usr/bin/env python3
"""Machine probe for a fixed N.E.K.O Voice native-promotion candidate.

This is candidate-only acceptance tooling. It never edits the XiaoYu product pin.
It verifies the fixed upstream candidate, runs native Voice lifecycle tests,
replays the existing managed patch series in order in a disposable worktree, and
only then runs existing XiaoYu Voice/Qwen product tests.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

EXPECTED_CANDIDATE_SHA = "d90f8371653c5a2a9b01d655c38475414711266a"
EXPECTED_PRODUCT_SHA = "c3fc33ff0d32e4a79fd905d1add22d45725071f5"

REQUIRED_NATIVE_FILES = (
    "main_logic/tts_client/_http_pool.py",
    "main_logic/tts_client/_preconnect.py",
    "main_logic/tts_client/workers/qwen.py",
    "tests/unit/test_spare_socket.py",
    "tests/unit/test_tts_preconnect_providers.py",
    "tests/unit/test_step_tts_preconnect.py",
    "tests/unit/test_qwen_server_close_reporting.py",
)

NATIVE_TESTS = (
    "tests/unit/test_spare_socket.py",
    "tests/unit/test_tts_preconnect_providers.py",
    "tests/unit/test_step_tts_preconnect.py",
    "tests/unit/test_qwen_server_close_reporting.py",
)

PRODUCT_TESTS = (
    "tests/unit/test_qwen_voice_bundle.py",
    "tests/unit/test_tts_handoff_ownership.py",
    "tests/unit/test_realtime_close_ownership.py",
    "tests/unit/runtime/test_realtime_connection_recovery.py",
    "tests/unit/test_voice_start_slot_ownership.py",
    "tests/unit/test_cosyvoice_audio_done_generation.py",
    "tests/unit/test_private_speech_output_gate.py",
)


def _tail(value: str, limit: int = 4000) -> str:
    value = value or ""
    return value if len(value) <= limit else value[-limit:]


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 900.0,
) -> dict[str, Any]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "args": list(args),
        "returncode": int(completed.returncode),
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _series(workspace: Path) -> list[str]:
    payload = _read_object(workspace / "private_overlay" / "patches" / "series.json")
    patches = payload.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("managed patch series is empty")
    names = [str(item.get("file") or "").strip() for item in patches if isinstance(item, dict)]
    if not names or any(not name for name in names):
        raise ValueError("managed patch series contains an invalid entry")
    return names


def _product_pin(workspace: Path) -> str:
    payload = _read_object(workspace / "private_overlay" / "NEKO_UPSTREAM.lock.json")
    return str(payload.get("tested_commit") or "").strip()


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _blocked(result: dict[str, Any], kind: str, detail: str) -> None:
    result["blockers"].append({"kind": kind, "detail": detail})


def probe(
    *,
    workspace: Path,
    candidate_root: Path,
    result_path: Path,
) -> tuple[dict[str, Any], int]:
    workspace = workspace.resolve()
    candidate_root = candidate_root.resolve()
    result: dict[str, Any] = {
        "schema_version": 1,
        "candidate_only": True,
        "expected_candidate_sha": EXPECTED_CANDIDATE_SHA,
        "expected_product_sha": EXPECTED_PRODUCT_SHA,
        "promotion_ready": False,
        "blockers": [],
        "native_files": {},
        "native_tests": None,
        "patch_replay": [],
        "product_tests": None,
    }

    sha_check = _run(
        ("git", "rev-parse", "HEAD"),
        cwd=candidate_root,
        timeout=30,
    )
    result["candidate_git"] = sha_check
    actual_sha = sha_check["stdout_tail"].strip()
    result["candidate_sha"] = actual_sha
    if sha_check["returncode"] != 0 or actual_sha != EXPECTED_CANDIDATE_SHA:
        _blocked(result, "candidate_sha", actual_sha or "unresolved")
        _write_result(result_path, result)
        return result, 3

    pin = _product_pin(workspace)
    result["product_pin"] = pin
    if pin != EXPECTED_PRODUCT_SHA:
        _blocked(result, "product_pin_changed", pin or "missing")
        _write_result(result_path, result)
        return result, 4

    license_text = (candidate_root / "LICENSE").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    result["apache_2_license"] = "Apache License" in license_text and "Version 2.0" in license_text
    if not result["apache_2_license"]:
        _blocked(result, "license", "candidate is not Apache-2.0")

    for relpath in REQUIRED_NATIVE_FILES:
        exists = (candidate_root / relpath).is_file()
        result["native_files"][relpath] = exists
        if not exists:
            _blocked(result, "missing_native_file", relpath)

    if result["blockers"]:
        _write_result(result_path, result)
        return result, 0

    uv = shutil.which("uv")
    if not uv:
        _blocked(result, "probe_environment", "uv is unavailable")
        _write_result(result_path, result)
        return result, 2

    native_command = (
        uv,
        "run",
        "--project",
        str(candidate_root),
        "--locked",
        "--group",
        "dev",
        "python",
        "-m",
        "pytest",
        "-q",
        *NATIVE_TESTS,
    )
    native = _run(native_command, cwd=candidate_root, timeout=1200)
    result["native_tests"] = native
    if native["returncode"] != 0:
        _blocked(result, "native_voice_tests", f"exit {native['returncode']}")
        _write_result(result_path, result)
        return result, 0

    product_root = (workspace / "_neko_voice_candidate_product").resolve()
    if product_root.exists():
        subprocess.run(
            ["git", "-C", str(candidate_root), "worktree", "remove", "--force", str(product_root)],
            text=True,
            capture_output=True,
            check=False,
        )
        if product_root.exists():
            shutil.rmtree(product_root)

    add_worktree = _run(
        ("git", "worktree", "add", "--detach", str(product_root), "HEAD"),
        cwd=candidate_root,
        timeout=60,
    )
    result["worktree_add"] = add_worktree
    if add_worktree["returncode"] != 0:
        _blocked(result, "probe_environment", "candidate worktree creation failed")
        _write_result(result_path, result)
        return result, 2

    try:
        patches = _series(workspace)
        result["managed_patch_count"] = len(patches)
        replay_ok = True
        for patch_name in patches:
            patch_path = workspace / "private_overlay" / "patches" / patch_name
            check = _run(
                ("git", "apply", "--check", "--", str(patch_path)),
                cwd=product_root,
                timeout=60,
            )
            record: dict[str, Any] = {
                "patch": patch_name,
                "check_returncode": check["returncode"],
                "check_stderr_tail": check["stderr_tail"],
            }
            if check["returncode"] != 0:
                record["applied"] = False
                result["patch_replay"].append(record)
                _blocked(result, "managed_patch_conflict", patch_name)
                replay_ok = False
                break

            apply_result = _run(
                ("git", "apply", "--", str(patch_path)),
                cwd=product_root,
                timeout=60,
            )
            record["apply_returncode"] = apply_result["returncode"]
            record["apply_stderr_tail"] = apply_result["stderr_tail"]
            if apply_result["returncode"] != 0:
                record["applied"] = False
                result["patch_replay"].append(record)
                _blocked(result, "managed_patch_apply", patch_name)
                replay_ok = False
                break

            reverse = _run(
                ("git", "apply", "--reverse", "--check", "--", str(patch_path)),
                cwd=product_root,
                timeout=60,
            )
            record["reverse_check_returncode"] = reverse["returncode"]
            record["applied"] = reverse["returncode"] == 0
            result["patch_replay"].append(record)
            if reverse["returncode"] != 0:
                _blocked(result, "managed_patch_postcondition", patch_name)
                replay_ok = False
                break

        if replay_ok:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(product_root)
            product_command = (
                uv,
                "run",
                "--project",
                str(candidate_root),
                "--locked",
                "--group",
                "dev",
                "python",
                "-m",
                "pytest",
                "-q",
                *PRODUCT_TESTS,
            )
            product = _run(
                product_command,
                cwd=product_root,
                env=env,
                timeout=1800,
            )
            result["product_tests"] = product
            if product["returncode"] != 0:
                _blocked(result, "xiaoyu_voice_product_tests", f"exit {product['returncode']}")
    finally:
        subprocess.run(
            ["git", "-C", str(candidate_root), "worktree", "remove", "--force", str(product_root)],
            text=True,
            capture_output=True,
            check=False,
        )

    result["promotion_ready"] = not result["blockers"]
    result["verdict"] = "PROMOTION_READY" if result["promotion_ready"] else "BLOCKED"
    _write_result(result_path, result)
    return result, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    args = parser.parse_args()

    result, code = probe(
        workspace=args.workspace,
        candidate_root=args.candidate_root,
        result_path=args.result_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
