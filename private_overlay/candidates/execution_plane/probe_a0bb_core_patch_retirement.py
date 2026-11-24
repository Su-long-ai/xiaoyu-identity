#!/usr/bin/env python3
"""Candidate-only probe for retiring selected XiaoYu managed patches on N.E.K.O a0bb.

The probe runs against an already fully migrated a0bb candidate tree. For each
selected managed patch it temporarily removes that patch's runtime implementation
while preserving the patch-provided acceptance tests, executes those tests, and
then restores the candidate byte-for-byte.

A passing focused test is only a *retirement candidate* signal. It never edits
series.json, NEKO_UPSTREAM.lock.json, or any Stable release binding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

EXPECTED_CANDIDATE_SHA = "a0bb66f47fd097cc21f18d75e4c72c90489a903f"

_PATCH_PATH_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")


@dataclass(frozen=True)
class ProbeTarget:
    patch: str
    runner: str
    tests: tuple[str, ...]


TARGETS: tuple[ProbeTarget, ...] = (
    ProbeTarget(
        patch="0003-qwen38-server-vad-reliability.patch",
        runner="pytest",
        tests=("tests/unit/test_voice_session.py",),
    ),
    ProbeTarget(
        patch="0005-latest-character-switch-intent-replay.patch",
        runner="node",
        tests=("tests/frontend/chat_avatar_integration.test.cjs",),
    ),
    ProbeTarget(
        patch="0007-private-first-round-tool-route.patch",
        runner="pytest",
        tests=("tests/unit/test_tool_calling.py",),
    ),
    ProbeTarget(
        patch="0008-qwen-clone-provider-routing.patch",
        runner="pytest",
        tests=(
            "tests/unit/test_glm_tts.py",
            "tests/unit/test_qwen_voice_bundle.py",
        ),
    ),
)


def _tail(value: str, limit: int = 6000) -> str:
    value = value or ""
    return value if len(value) <= limit else value[-limit:]


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 1200.0,
) -> dict[str, Any]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
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


def _patch_paths(patch_path: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for raw in patch_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = _PATCH_PATH_RE.match(raw)
        if not match:
            continue
        left, right = match.groups()
        if left != right:
            raise ValueError(f"rename patches are not supported by retirement probe: {raw}")
        if left not in paths:
            paths.append(left)
    if not paths:
        raise ValueError(f"no file paths found in patch: {patch_path}")
    return tuple(paths)


def _is_test_path(relpath: str) -> bool:
    lowered = relpath.lower()
    return (
        lowered.startswith("tests/")
        or lowered.startswith("plugin/tests/")
        or ".test." in lowered
        or lowered.endswith(".test.cjs")
        or lowered.endswith(".test.tsx")
    )


def _snapshot(root: Path, relpaths: Sequence[str]) -> dict[str, bytes | None]:
    result: dict[str, bytes | None] = {}
    for relpath in relpaths:
        path = root / relpath
        result[relpath] = path.read_bytes() if path.is_file() else None
    return result


def _restore_snapshot(root: Path, snapshot: dict[str, bytes | None]) -> None:
    for relpath, payload in snapshot.items():
        path = root / relpath
        if payload is None:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _snapshot_digest(snapshot: dict[str, bytes | None]) -> str:
    digest = hashlib.sha256()
    for relpath in sorted(snapshot):
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        payload = snapshot[relpath]
        if payload is None:
            digest.update(b"<MISSING>")
        else:
            digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _runner_command(
    *,
    target: ProbeTarget,
    candidate_root: Path,
    uv_path: str | None,
) -> tuple[str, ...]:
    if target.runner == "pytest":
        if not uv_path:
            raise RuntimeError("uv is required for pytest retirement probes")
        return (
            uv_path,
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
            *target.tests,
        )
    if target.runner == "node":
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node is required for frontend retirement probes")
        return (node, "--test", *target.tests)
    raise ValueError(f"unsupported runner: {target.runner}")


def _probe_one(
    *,
    workspace: Path,
    candidate_root: Path,
    target: ProbeTarget,
    uv_path: str | None,
) -> dict[str, Any]:
    patch_path = workspace / "private_overlay" / "patches" / target.patch
    if not patch_path.is_file():
        raise FileNotFoundError(patch_path)

    touched_paths = _patch_paths(patch_path)
    test_paths = tuple(path for path in touched_paths if _is_test_path(path))
    if not test_paths:
        raise RuntimeError(f"{target.patch} has no patch-provided acceptance tests")

    missing_declared = [rel for rel in target.tests if rel not in test_paths]
    if missing_declared:
        raise RuntimeError(
            f"{target.patch} declared tests not owned by patch: {missing_declared}"
        )

    baseline = _snapshot(candidate_root, touched_paths)
    baseline_digest = _snapshot_digest(baseline)

    reverse_check = _run(
        ("git", "apply", "--reverse", "--check", "--", str(patch_path)),
        cwd=candidate_root,
        timeout=60,
    )
    if reverse_check["returncode"] != 0:
        raise RuntimeError(
            f"{target.patch} cannot be cleanly reversed from migrated candidate: "
            f"{reverse_check['stderr_tail']}"
        )

    reverse_apply = _run(
        ("git", "apply", "--reverse", "--", str(patch_path)),
        cwd=candidate_root,
        timeout=60,
    )
    if reverse_apply["returncode"] != 0:
        raise RuntimeError(f"reverse apply failed for {target.patch}")

    reversed_tests = _snapshot(candidate_root, test_paths)
    _restore_snapshot(
        candidate_root,
        {relpath: baseline[relpath] for relpath in test_paths},
    )

    test_result: dict[str, Any]
    try:
        command = _runner_command(
            target=target,
            candidate_root=candidate_root,
            uv_path=uv_path,
        )
        test_result = _run(command, cwd=candidate_root)
    finally:
        _restore_snapshot(candidate_root, reversed_tests)
        forward_check = _run(
            ("git", "apply", "--check", "--", str(patch_path)),
            cwd=candidate_root,
            timeout=60,
        )
        if forward_check["returncode"] != 0:
            raise RuntimeError(
                f"{target.patch} could not be restored after probe: "
                f"{forward_check['stderr_tail']}"
            )
        forward_apply = _run(
            ("git", "apply", "--", str(patch_path)),
            cwd=candidate_root,
            timeout=60,
        )
        if forward_apply["returncode"] != 0:
            raise RuntimeError(f"forward restore failed for {target.patch}")

    restored = _snapshot(candidate_root, touched_paths)
    restored_digest = _snapshot_digest(restored)
    if restored_digest != baseline_digest:
        raise RuntimeError(f"{target.patch} probe did not restore candidate byte-for-byte")

    passed = test_result["returncode"] == 0
    return {
        "patch": target.patch,
        "runner": target.runner,
        "tests": list(target.tests),
        "touched_paths": list(touched_paths),
        "baseline_digest": baseline_digest,
        "restored_digest": restored_digest,
        "restored": True,
        "focused_acceptance": test_result,
        "verdict": (
            "RETIREMENT_CANDIDATE_REQUIRES_FULL_OMISSION_ACCEPTANCE"
            if passed
            else "PATCH_STILL_REQUIRED_BY_FOCUSED_ACCEPTANCE"
        ),
        "retirement_candidate": passed,
    }


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
        "promotion_authority": False,
        "expected_candidate_sha": EXPECTED_CANDIDATE_SHA,
        "candidate_sha": None,
        "targets": [],
        "retirement_candidates": [],
        "required_patches": [],
        "infrastructure_error": None,
    }

    sha = _run(("git", "rev-parse", "HEAD"), cwd=candidate_root, timeout=30)
    actual_sha = sha["stdout_tail"].strip()
    result["candidate_sha"] = actual_sha
    if sha["returncode"] != 0 or actual_sha != EXPECTED_CANDIDATE_SHA:
        result["infrastructure_error"] = {
            "kind": "candidate_sha",
            "detail": actual_sha or "unresolved",
        }
        _write_result(result_path, result)
        return result, 3

    uv_path = shutil.which("uv")
    try:
        for target in TARGETS:
            item = _probe_one(
                workspace=workspace,
                candidate_root=candidate_root,
                target=target,
                uv_path=uv_path,
            )
            result["targets"].append(item)
            if item["retirement_candidate"]:
                result["retirement_candidates"].append(target.patch)
            else:
                result["required_patches"].append(target.patch)
    except Exception as exc:
        result["infrastructure_error"] = {
            "kind": type(exc).__name__,
            "detail": str(exc),
        }
        _write_result(result_path, result)
        return result, 2

    _write_result(result_path, result)
    return result, 0


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result, code = probe(
        workspace=args.workspace,
        candidate_root=args.candidate_root,
        result_path=args.result,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
