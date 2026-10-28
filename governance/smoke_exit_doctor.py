#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke-phase exit doctor.

Local metadata only. It NEVER flips active_phase/benchmark_unlocked and never
calls a model/network. A PASS means only that Lead may perform a separate,
explicit phase switch after reviewing the frozen E2 protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import p1_integration_doctor as p1
import p2_integration_doctor as p2
from research_api import ResearchApiBudget

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
DEFAULT_CONTRACT = GOV / "SMOKE_EXIT_CONTRACT.json"
DEFAULT_DB = GOV / "registry.sqlite3"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _budget_status(root):
    budget = ResearchApiBudget(Path(root))
    try:
        return budget.status()
    finally:
        budget.close()


def _p2_scope_state(db_path, lineages):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        if not lineages:
            return {"active": [], "pending_e1": []}
        marks = ",".join("?" for _ in lineages)
        active = [
            dict(r) for r in con.execute(
                f"""SELECT lease_id,agent_id,role,family,lineage,capability,state
                      FROM leases
                     WHERE state='ACTIVE' AND lineage IN ({marks})
                     ORDER BY claimed_at""",
                tuple(lineages),
            ).fetchall()
        ]
        pending = [
            dict(r) for r in con.execute(
                f"""SELECT s.submission_id,s.evidence_label,s.decision,
                           l.lease_id,l.agent_id,l.role,l.family,l.lineage
                      FROM submissions s JOIN leases l ON l.lease_id=s.lease_id
                     WHERE s.decision='PENDING' AND l.lineage IN ({marks})
                     ORDER BY s.at""",
                tuple(lineages),
            ).fetchall()
        ]
        return {"active": active, "pending_e1": pending}
    finally:
        con.close()


def evaluate(
    contract_path=DEFAULT_CONTRACT,
    db_path=DEFAULT_DB,
    root=ROOT,
    *,
    p1_result=None,
    p2_result=None,
    budget_status=None,
):
    root = Path(root)
    contract_path = Path(contract_path)
    db_path = Path(db_path)
    c = load(contract_path)
    errors = []
    blockers = []
    warnings = []

    if c.get("schema") != "xiaoyu-smoke-exit-contract-v1":
        errors.append({"type": "contract_schema"})

    # Pin the policy/evaluation inputs used to decide that smoke is finished.
    input_checks = {}
    for name, spec in (c.get("pinned_inputs") or {}).items():
        path = root / spec["path"]
        got = sha(path) if path.is_file() else None
        exp = spec.get("sha256")
        ok = got == exp
        input_checks[name] = {
            "path": str(path),
            "expected": exp,
            "actual": got,
            "ok": ok,
        }
        if not ok:
            errors.append({
                "type": "pinned_input_hash_drift",
                "input": name,
                "expected": exp,
                "actual": got,
            })

    if p1_result is None:
        p1_result = p1.evaluate()
    if p2_result is None:
        p2_result = p2.evaluate()
    p1_ready = bool(p1_result.get("integration_ready"))
    p2_ready = bool(p2_result.get("p2_closeout_ready"))
    if not p1_ready:
        blockers.append({"type": "p1_not_integration_ready"})
    if not p2_ready:
        blockers.append({
            "type": "p2_not_closed",
            "blocked_stages": p2_result.get("blocked_required_stages", []),
        })

    # E2 protocol must be frozen prospectively, not retrofitted after benchmark calls.
    protocol_path = root / c["e2_protocol"]
    protocol = load(protocol_path) if protocol_path.is_file() else None
    protocol_check = {
        "path": str(protocol_path),
        "present": protocol is not None,
        "schema_ok": bool(protocol and protocol.get("schema") == "xiaoyu-e2-prospective-protocol-candidate-v1"),
        "status": protocol.get("status") if protocol else None,
        "required_status": c.get("required_e2_protocol_status"),
        "private_identity_data": (
            protocol.get("scope", {}).get("private_identity_data") if protocol else None
        ),
        "unready_tracks": [],
    }
    if protocol is None:
        blockers.append({"type": "e2_protocol_missing"})
    else:
        if not protocol_check["schema_ok"]:
            errors.append({"type": "e2_protocol_schema"})
        if protocol.get("status") != c.get("required_e2_protocol_status"):
            blockers.append({
                "type": "e2_protocol_not_frozen",
                "actual": protocol.get("status"),
                "required": c.get("required_e2_protocol_status"),
            })
        if protocol.get("scope", {}).get("private_identity_data") is not False:
            errors.append({"type": "e2_protocol_private_data_not_forbidden"})
        tracks = protocol.get("required_tracks") or []
        unready = [
            {"id": t.get("id"), "blocker": t.get("blocker")}
            for t in tracks if not t.get("ready_to_freeze")
        ]
        protocol_check["unready_tracks"] = unready
        if unready:
            blockers.append({"type": "e2_required_tracks_not_frozen", "tracks": unready})

        scoring = protocol.get("scoring") or {}
        required_layers = set(scoring.get("required_layers") or [])
        minimum_layers = {
            "source_or_stored_state_correctness",
            "derived_or_current_state_correctness",
            "retrieved_and_admitted_context_correctness",
            "final_answer_correctness",
        }
        if not minimum_layers.issubset(required_layers):
            errors.append({"type": "e2_scoring_layers_incomplete"})

    scope_state = _p2_scope_state(db_path, c.get("p2_scope_lineages") or [])
    if scope_state["active"]:
        blockers.append({
            "type": "p2_scope_not_quiescent",
            "active_leases": [r["lease_id"] for r in scope_state["active"]],
        })
    if scope_state["pending_e1"]:
        blockers.append({
            "type": "p2_scope_pending_e1",
            "submissions": [r["submission_id"] for r in scope_state["pending_e1"]],
        })

    if budget_status is None:
        budget_status = _budget_status(root)
    paid = c.get("paid_phase") or {}
    phase_checks = {
        "active_phase": budget_status.get("active_phase"),
        "required_current_phase": paid.get("required_current_phase"),
        "benchmark_unlocked": bool(budget_status.get("benchmark_unlocked")),
        "required_benchmark_unlocked": bool(paid.get("required_benchmark_unlocked")),
        "phase_used_or_reserved_tokens": int(budget_status.get("phase_used_or_reserved_tokens", 0)),
        "phase_cap_tokens": int(budget_status.get("phase_cap_tokens", 0)),
        "phase_remaining_tokens": int(budget_status.get("phase_remaining_tokens", 0)),
        "unknown_calls": int((budget_status.get("calls_by_status") or {}).get("UNKNOWN", 0)),
        "max_unknown_calls": int(paid.get("max_unknown_calls", 0)),
        "consume_remaining_tokens_to_exit": bool(paid.get("consume_remaining_tokens_to_exit", False)),
    }
    if phase_checks["active_phase"] != phase_checks["required_current_phase"]:
        blockers.append({
            "type": "wrong_current_paid_phase",
            "actual": phase_checks["active_phase"],
            "required": phase_checks["required_current_phase"],
        })
    if phase_checks["benchmark_unlocked"] != phase_checks["required_benchmark_unlocked"]:
        blockers.append({
            "type": "benchmark_lock_state_unexpected",
            "actual": phase_checks["benchmark_unlocked"],
            "required": phase_checks["required_benchmark_unlocked"],
        })
    if phase_checks["phase_used_or_reserved_tokens"] > phase_checks["phase_cap_tokens"]:
        errors.append({"type": "smoke_budget_exceeded"})
    if phase_checks["unknown_calls"] > phase_checks["max_unknown_calls"]:
        blockers.append({
            "type": "new_unknown_paid_outcomes",
            "actual": phase_checks["unknown_calls"],
            "allowed": phase_checks["max_unknown_calls"],
        })

    ready = not errors and not blockers
    return {
        "schema": "xiaoyu-smoke-exit-doctor-v1",
        "contract": str(contract_path),
        "input_checks": input_checks,
        "p1_integration_ready": p1_ready,
        "p2_closeout_ready": p2_ready,
        "p2_blocked_stages": p2_result.get("blocked_required_stages", []),
        "p2_scope_state": scope_state,
        "e2_protocol": protocol_check,
        "paid_phase": phase_checks,
        "errors": errors,
        "blockers": blockers,
        "warnings": warnings,
        "smoke_exit_ready": ready,
        "benchmark_phase_switch_allowed": ready,
        "phase_switch_performed": False,
        "e2_claim_allowed": False,
        "note": (
            "PASS permits only a separate explicit Lead switch from smoke to benchmark. "
            "This doctor never changes policy, never spends tokens, and never grants E2/E3."
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--require-ready", action="store_true")
    a = ap.parse_args()
    out = evaluate(a.contract, a.db)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out["errors"]:
        raise SystemExit(2)
    if a.require_ready and not out["smoke_exit_ready"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
