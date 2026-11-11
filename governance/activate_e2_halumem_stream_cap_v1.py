#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-audit activation for the HaluMem stream-cap amendment.

Default mode is read-only. --apply is accepted only after the exact independent
stream-cap final freeze exists. The operation registers exact amendment/freeze
bindings and raises only the already-frozen Halu epoch capacity guards; rolling,
daily, phase and global limits remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
POLICY = GOV / "policy.json"
AMEND = GOV / "E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
FREEZE = GOV / "E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE_V1.json"
BUDGET = GOV / "E2_HALUMEM_RUNTIME_BUDGET_CAPACITY_ADDENDUM_V1.json"
PROXY = GOV / "research_api_proxy_recovery_cap_v1.py"
LME_INCIDENT = GOV / "E2_LME_CONFIRMATORY_GOLD_BOUNDARY_INCIDENT_20261029.md"
LEDGER = GOV / "research_api_usage.sqlite3"
SCOPE = "proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"


class ActivationError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    if not path.is_file():
        raise ActivationError("missing: " + str(path))
    obj = json.loads(path.read_text("utf-8"))
    if not isinstance(obj, dict):
        raise ActivationError("expected JSON object: " + str(path))
    return obj


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def ledger_counts() -> dict[str, int]:
    con = sqlite3.connect(str(LEDGER))
    con.row_factory = sqlite3.Row
    try:
        return {
            str(r["status"]): int(r["n"])
            for r in con.execute(
                "select status,count(*) n from calls where budget_scope=? group by status",
                (SCOPE,),
            )
        }
    finally:
        con.close()


def validate() -> tuple[dict, dict]:
    policy = load(POLICY)
    amend = load(AMEND)
    freeze = load(FREEZE)
    budget = load(BUDGET)

    if amend.get("schema") != "xiaoyu-e2-execution-amendment-v1":
        raise ActivationError("bad amendment schema")
    if amend.get("status") != "FROZEN_POST_ENTRY_AMENDMENT":
        raise ActivationError("bad amendment status")
    if amend.get("execution_allowed_by_this_file") is not False:
        raise ActivationError("amendment candidate unexpectedly self-authorizes")

    if freeze.get("schema") != "xiaoyu-e2-halumem-stream-cap-amendment-freeze-v1":
        raise ActivationError("bad amendment freeze schema")
    if freeze.get("status") != "STREAM_CAP_AMENDMENT_EXECUTION_AUTHORIZED":
        raise ActivationError("amendment freeze is not authorized")
    if freeze.get("execution_allowed") is not True:
        raise ActivationError("amendment freeze does not allow execution")
    if freeze.get("amendment_sha256") != sha(AMEND):
        raise ActivationError("amendment/freeze hash drift")

    if budget.get("schema") != "xiaoyu-e2-halumem-runtime-budget-capacity-addendum-v1":
        raise ActivationError("bad runtime-budget addendum schema")
    if budget.get("status") != "FROZEN_NOT_ACTIVE":
        raise ActivationError("runtime-budget addendum status drift")
    if budget.get("execution_allowed_by_this_file") is not False:
        raise ActivationError("runtime-budget addendum unexpectedly self-authorizes")
    parent = (budget.get("parents") or {}).get("stream_cap_amendment") or {}
    if parent.get("sha256") != sha(AMEND):
        raise ActivationError("runtime-budget addendum amendment parent drift")

    if not LME_INCIDENT.is_file():
        raise ActivationError("LongMemEval invalidation incident missing")

    e2 = policy.get("e2_transition") or {}
    if e2.get("current_stage") != "E2_CONFIRMATORY":
        raise ActivationError("policy is not in E2_CONFIRMATORY")

    paid = ((policy.get("budget") or {}).get("paid_research") or {})
    runtime = paid.get("runtime_guard") or {}
    guard = (runtime.get("scope_overrides") or {}).get(SCOPE)
    if not isinstance(guard, dict):
        raise ActivationError("HaluMem scope guard missing")

    old = budget.get("old_scope_epoch_guard") or {}
    proposed = budget.get("proposed_scope_epoch_guard") or {}
    for key in (
        "epoch_raw_token_cap",
        "epoch_cache_miss_cap",
        "epoch_output_token_cap",
        "epoch_call_cap",
    ):
        live = int(guard.get(key, -1))
        allowed = {int(old[key]), int(proposed[key])}
        if live not in allowed:
            raise ActivationError("unexpected epoch guard drift: " + key)

    unchanged = budget.get("unchanged_hard_guards") or {}
    checks = {
        "rolling_window_seconds": runtime.get("rolling_window_seconds"),
        "rolling_raw_token_cap": guard.get("rolling_raw_token_cap"),
        "rolling_cache_miss_cap": guard.get("rolling_cache_miss_cap"),
        "rolling_output_token_cap": guard.get("rolling_output_token_cap"),
        "rolling_call_cap": guard.get("rolling_call_cap"),
        "global_daily_call_cap": (policy.get("budget") or {}).get("max_paid_api_calls_per_day"),
        "global_total_token_cap": paid.get("max_total_tokens"),
        "benchmark_phase_token_cap": paid.get("benchmark_max_tokens"),
        "max_single_reservation_tokens": runtime.get("max_single_reservation_tokens"),
    }
    for key, live in checks.items():
        if int(live) != int(unchanged[key]):
            raise ActivationError("unchanged hard guard drift: " + key)

    counts = ledger_counts()
    if counts.get("RESERVED", 0):
        raise ActivationError("HaluMem RESERVED calls present")
    if counts.get("UNKNOWN", 0) != 1:
        raise ActivationError("historical HaluMem UNKNOWN count drift")
    if counts.get("COMMITTED", 0) < 767:
        raise ActivationError("HaluMem committed ledger regressed")

    return policy, {
        "ready": True,
        "policy_sha256": sha(POLICY),
        "amendment_sha256": sha(AMEND),
        "freeze_sha256": sha(FREEZE),
        "runtime_budget_addendum_sha256": sha(BUDGET),
        "proxy_sha256": sha(PROXY),
        "ledger": counts,
        "proposed_scope_epoch_guard": proposed,
        "unchanged_hard_guards": unchanged,
    }


def apply(policy: dict) -> str:
    freeze = load(FREEZE)
    budget = load(BUDGET)
    e2 = policy.setdefault("e2_transition", {})
    rows = e2.setdefault("execution_amendments", [])
    amend_rel = rel(AMEND)
    amend_sha = sha(AMEND)

    existing = next(
        (x for x in rows if isinstance(x, dict) and x.get("path") == amend_rel),
        None,
    )
    if existing is None:
        rows.append({"path": amend_rel, "sha256": amend_sha})
    elif existing.get("sha256") != amend_sha:
        raise ActivationError("existing amendment registration SHA drift")

    e2["halumem_stream_cap_amendment_freeze"] = rel(FREEZE)
    e2["halumem_stream_cap_amendment_freeze_sha256"] = sha(FREEZE)
    e2["halumem_runtime_budget_capacity_addendum"] = rel(BUDGET)
    e2["halumem_runtime_budget_capacity_addendum_sha256"] = sha(BUDGET)
    e2["halumem_confirmatory_recovery_proxy"] = rel(PROXY)
    e2["halumem_confirmatory_recovery_proxy_sha256"] = sha(PROXY)

    guard = policy["budget"]["paid_research"]["runtime_guard"]["scope_overrides"][SCOPE]
    proposed = budget["proposed_scope_epoch_guard"]
    for key in (
        "epoch_raw_token_cap",
        "epoch_cache_miss_cap",
        "epoch_output_token_cap",
        "epoch_call_cap",
    ):
        guard[key] = int(proposed[key])

    tmp = POLICY.with_suffix(".json.tmp.stream-cap")
    tmp.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n")
    os.replace(tmp, POLICY)
    return sha(POLICY)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    policy, summary = validate()
    if not args.apply:
        print(json.dumps({"mode": "CHECK_ONLY", **summary}, ensure_ascii=False, indent=2))
        return

    new_sha = apply(policy)
    _, post = validate()
    print(
        json.dumps(
            {"mode": "APPLIED", "new_policy_sha256": new_sha, **post},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
