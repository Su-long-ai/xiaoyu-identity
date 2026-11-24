#!/usr/bin/env python3
"""Candidate-only migration probe from the c3 NekoClaw product to fac795 NekoPower.

The probe never edits the product pin or managed patch series. It measures:
- exact upstream identity/license;
- how far the base managed patch prefix mechanically replays;
- whether latest NekoPower natively closes restart/effect/plugin correctness gaps.

A blocked migration is a successful observation. Hard failure is reserved for
probe integrity (wrong SHA/product pin/license/environment).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

EXPECTED_CANDIDATE_SHA = "fac795091e33cd92a6604d14ac242510944badac"
EXPECTED_PRODUCT_SHA = "c3fc33ff0d32e4a79fd905d1add22d45725071f5"
BASE_PATCH_COUNT = 10

REQUIRED_FILES = (
    "nekopower/host/ledger.py",
    "nekopower/host/task_agents.py",
    "nekopower/host/outbox.py",
    "nekopower/host/plugin_runs.py",
)


def _tail(value: str, limit: int = 3000) -> str:
    value = value or ""
    return value if len(value) <= limit else value[-limit:]


def _run(args: Sequence[str], *, cwd: Path, timeout: float = 120.0) -> dict[str, Any]:
    done = subprocess.run(
        list(args),
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return {
        "args": list(args),
        "returncode": int(done.returncode),
        "stdout_tail": _tail(done.stdout),
        "stderr_tail": _tail(done.stderr),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _product_pin(workspace: Path) -> str:
    return str(
        _read_json(workspace / "private_overlay" / "NEKO_UPSTREAM.lock.json").get(
            "tested_commit"
        )
        or ""
    ).strip()


def _patches(workspace: Path) -> list[str]:
    series = _read_json(workspace / "private_overlay" / "patches" / "series.json")
    rows = series.get("patches")
    if not isinstance(rows, list):
        raise ValueError("managed patch series missing")
    names = [str(row.get("file") or "").strip() for row in rows if isinstance(row, dict)]
    if len(names) < BASE_PATCH_COUNT or any(not item for item in names):
        raise ValueError("managed patch series is incomplete")
    return names


def _semantic_matrix(candidate_root: Path) -> dict[str, Any]:
    ledger = (candidate_root / "nekopower/host/ledger.py").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    agents = (candidate_root / "nekopower/host/task_agents.py").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    outbox = (candidate_root / "nekopower/host/outbox.py").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    plugin_runs = (candidate_root / "nekopower/host/plugin_runs.py").read_text(
        encoding="utf-8-sig", errors="replace"
    )

    old_active_failed = (
        "status IN ('queued','working','waiting_user')" in ledger
        or 'status IN ("queued","working","waiting_user")' in ledger
    ) and "HOST_ENDED_REASON" in ledger
    queue_memory_only = all(
        marker in agents
        for marker in (
            "self._queue: deque[str]",
            "self._notes: dict[str, list[str]]",
            "self._resume: dict[str, str]",
        )
    )
    durable_queue_events = any(
        marker in ledger or marker in agents
        for marker in ("restart_queue_resume", "restart_queue_note")
    )

    effect_markers = {
        name: (name in outbox or name in ledger)
        for name in (
            "delivery_handoff",
            "delivery_claimed",
            "delivery_uncertain",
            "delivery_receipt",
        )
    }
    plugin_unknown_consumed = (
        'status == "unknown"' in plugin_runs
        or "status == 'unknown'" in plugin_runs
        or '"unknown":' in plugin_runs
    )
    plugin_idempotency = "idempotency_key" in plugin_runs

    return {
        "restart": {
            "prior_host_active_failed": old_active_failed,
            "queue_resume_notes_are_process_memory": queue_memory_only,
            "native_durable_queue_epoch_events": durable_queue_events,
            "equivalent_to_green_restart_stack": (
                not old_active_failed and not queue_memory_only and durable_queue_events
            ),
        },
        "delivery_effect": {
            "markers": effect_markers,
            "equivalent_to_0011_0012": all(effect_markers.values()),
        },
        "plugin_effect": {
            "unknown_effect_consumed_explicitly": plugin_unknown_consumed,
            "idempotent_create_key": plugin_idempotency,
            "equivalent_to_0013_0014": plugin_unknown_consumed and plugin_idempotency,
        },
    }


def _write(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(*, workspace: Path, candidate_root: Path, result_path: Path) -> tuple[dict[str, Any], int]:
    workspace = workspace.resolve()
    candidate_root = candidate_root.resolve()
    result: dict[str, Any] = {
        "schema_version": 1,
        "candidate_only": True,
        "promotion_forbidden": True,
        "expected_candidate_sha": EXPECTED_CANDIDATE_SHA,
        "expected_product_sha": EXPECTED_PRODUCT_SHA,
        "hard_failures": [],
        "migration_blockers": [],
        "base_patch_replay": [],
    }

    rev = _run(("git", "rev-parse", "HEAD"), cwd=candidate_root, timeout=30)
    actual = rev["stdout_tail"].strip()
    result["candidate_sha"] = actual
    if rev["returncode"] != 0 or actual != EXPECTED_CANDIDATE_SHA:
        result["hard_failures"].append({"kind": "candidate_sha", "detail": actual or "unresolved"})

    product_pin = _product_pin(workspace)
    result["product_pin"] = product_pin
    if product_pin != EXPECTED_PRODUCT_SHA:
        result["hard_failures"].append({"kind": "product_pin_changed", "detail": product_pin or "missing"})

    license_path = candidate_root / "LICENSE"
    license_text = license_path.read_text(encoding="utf-8-sig", errors="replace") if license_path.is_file() else ""
    result["apache_2_license"] = "Apache License" in license_text and "Version 2.0" in license_text
    if not result["apache_2_license"]:
        result["hard_failures"].append({"kind": "license", "detail": "Apache-2.0 marker missing"})

    result["required_files"] = {rel: (candidate_root / rel).is_file() for rel in REQUIRED_FILES}
    missing = [rel for rel, exists in result["required_files"].items() if not exists]
    if missing:
        result["hard_failures"].append({"kind": "candidate_layout", "detail": missing})

    if result["hard_failures"]:
        result["verdict"] = "PROBE_INVALID"
        _write(result_path, result)
        return result, 2

    # Mechanical compatibility is measured only for the original ten base
    # patches. 0011-0014 target the old NekoClaw host paths and therefore
    # require semantic NekoPower migration, not path-only replay.
    scratch = (workspace / "_neko_fac795_base_patch_probe").resolve()
    if scratch.exists():
        subprocess.run(
            ["git", "-C", str(candidate_root), "worktree", "remove", "--force", str(scratch)],
            text=True,
            capture_output=True,
            check=False,
        )
        if scratch.exists():
            shutil.rmtree(scratch)
    add = _run(("git", "worktree", "add", "--detach", str(scratch), "HEAD"), cwd=candidate_root, timeout=60)
    result["worktree_add"] = add
    if add["returncode"] != 0:
        result["hard_failures"].append({"kind": "worktree", "detail": "candidate worktree creation failed"})
        result["verdict"] = "PROBE_INVALID"
        _write(result_path, result)
        return result, 2

    try:
        for patch_name in _patches(workspace)[:BASE_PATCH_COUNT]:
            patch = workspace / "private_overlay" / "patches" / patch_name
            check = _run(("git", "apply", "--check", "--", str(patch)), cwd=scratch, timeout=60)
            row = {
                "patch": patch_name,
                "check_returncode": check["returncode"],
                "stderr_tail": check["stderr_tail"],
            }
            result["base_patch_replay"].append(row)
            if check["returncode"] != 0:
                result["base_patch_first_conflict"] = patch_name
                break
            applied = _run(("git", "apply", "--", str(patch)), cwd=scratch, timeout=60)
            row["apply_returncode"] = applied["returncode"]
            if applied["returncode"] != 0:
                result["hard_failures"].append({"kind": "patch_probe_apply", "detail": patch_name})
                break
    finally:
        subprocess.run(
            ["git", "-C", str(candidate_root), "worktree", "remove", "--force", str(scratch)],
            text=True,
            capture_output=True,
            check=False,
        )

    if result["hard_failures"]:
        result["verdict"] = "PROBE_INVALID"
        _write(result_path, result)
        return result, 2

    matrix = _semantic_matrix(candidate_root)
    result["semantic_matrix"] = matrix
    if result.get("base_patch_first_conflict"):
        result["migration_blockers"].append(
            {"kind": "base_patch_rebase", "detail": result["base_patch_first_conflict"]}
        )
    if not matrix["restart"]["equivalent_to_green_restart_stack"]:
        result["migration_blockers"].append({"kind": "restart_continuity", "detail": "latest NekoPower is not yet equivalent"})
    if not matrix["delivery_effect"]["equivalent_to_0011_0012"]:
        result["migration_blockers"].append({"kind": "delivery_effect", "detail": "0011-0012 semantics require migration"})
    if not matrix["plugin_effect"]["equivalent_to_0013_0014"]:
        result["migration_blockers"].append({"kind": "plugin_effect", "detail": "0013-0014 semantics require migration"})

    result["promotion_ready"] = not result["migration_blockers"]
    result["verdict"] = "PROMOTION_READY" if result["promotion_ready"] else "MIGRATION_BLOCKED_RESIDUALS"
    _write(result_path, result)
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
