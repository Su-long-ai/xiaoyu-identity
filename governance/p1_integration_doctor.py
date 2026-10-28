#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 integration readiness doctor.

Reads only local governance metadata. It never calls a model or network service.
Its job is different from reuse-doctor:
- reuse-doctor asks whether a research claim may be opened;
- integration-doctor asks whether a concrete P1 assembly only pins evidence/implementations
  that are still admissible after later audits and architecture decisions.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
DEFAULT_CONTRACT = GOV / "P1_INTEGRATION_CONTRACT.json"
DEFAULT_CANDIDATE = GOV / "P1_INTEGRATION_CANDIDATE.json"
DEFAULT_DB = GOV / "registry.sqlite3"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_submission(con: sqlite3.Connection, submission_id: str):
    return con.execute(
        """SELECT s.submission_id,s.at,s.evidence_label,s.decision,s.decision_reason,
                  l.lease_id,l.family,l.lineage,l.capability,l.hypothesis,l.workspace
             FROM submissions s JOIN leases l ON l.lease_id=s.lease_id
            WHERE s.submission_id=?""",
        (submission_id,),
    ).fetchone()


def accepted_replacements(con: sqlite3.Connection, lineage: str, after_at: float):
    return con.execute(
        """SELECT s.submission_id,s.at,l.family,l.hypothesis
             FROM submissions s JOIN leases l ON l.lease_id=s.lease_id
            WHERE l.lineage=? AND s.decision='ACCEPT_E1' AND s.at>?
            ORDER BY s.at""",
        (lineage, after_at),
    ).fetchall()


def backlog_path_status(con, project_root, backlog_id):
    path=project_root/"governance"/"RESEARCH_BACKLOG.json"
    if not path.is_file():
        return {"ok":False,"status":"BACKLOG_FILE_MISSING","backlog_id":backlog_id}
    try:
        data=load_json(path)
    except Exception as exc:
        return {"ok":False,"status":"BACKLOG_INVALID","backlog_id":backlog_id,
                "error":type(exc).__name__+":"+str(exc)}
    rows=[r for r in data.get("candidates",[]) if r.get("id")==backlog_id]
    if len(rows)!=1:
        return {"ok":False,"status":"BACKLOG_COUNT_"+str(len(rows)),"backlog_id":backlog_id}
    row=rows[0]
    lifecycle=row.get("status","active")
    try:
        leases=con.execute(
            """SELECT l.lease_id,l.state,s.submission_id,s.evidence_label,s.decision,
                      l.family,l.lineage,l.hypothesis,l.claimed_at
                 FROM leases l LEFT JOIN submissions s ON s.lease_id=l.lease_id
                WHERE l.backlog_id=? ORDER BY l.claimed_at""",(backlog_id,)).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        leases=[]
    # A self-directed Reuse-Guard-v2 task can be adopted into the formal backlog
    # after its lease was created, so backlog_id may legitimately be empty.
    # Adoption is explicit and must still match the backlog family+hypothesis.
    if not leases:
        adopted=row.get("adopted_lease_id")
        if adopted:
            adopted_rows=con.execute(
                """SELECT l.lease_id,l.state,s.submission_id,s.evidence_label,s.decision,
                          l.family,l.lineage,l.hypothesis,l.claimed_at
                     FROM leases l LEFT JOIN submissions s ON s.lease_id=l.lease_id
                    WHERE l.lease_id=? ORDER BY s.at""",(adopted,)).fetchall()
            if adopted_rows:
                for x in adopted_rows:
                    if x["family"]!=row.get("family") or x["hypothesis"]!=row.get("hypothesis"):
                        return {"ok":False,"status":"ADOPTED_LEASE_SCOPE_MISMATCH",
                                "backlog_id":backlog_id,"adopted_lease_id":adopted,
                                "expected_family":row.get("family"),
                                "actual_family":x["family"]}
                # Normalize to the same public shape as backlog-bound leases.
                leases=[dict(x) for x in adopted_rows]

    # Some formally adopted tasks were originally self-directed and later recovered
    # under an exact same scientific scope. Recovery leases intentionally do not
    # mutate the historic backlog_id. For rows that explicitly opt in, merge every
    # exact family+lineage+hypothesis lease so ACTIVE recovery is visible and an
    # old TTL_EXPIRED lease does not make the remediation path look consumed.
    if row.get("adopt_scope_match"):
        scoped=con.execute(
            """SELECT l.lease_id,l.state,s.submission_id,s.evidence_label,s.decision,
                      l.family,l.lineage,l.hypothesis,l.claimed_at
                 FROM leases l LEFT JOIN submissions s ON s.lease_id=l.lease_id
                WHERE l.family=? AND l.lineage=? AND l.hypothesis=?
                ORDER BY l.claimed_at,s.at""",
            (row.get("family"),row.get("lineage") or row.get("family"),
             row.get("hypothesis"))).fetchall()
        merged={}
        for item in list(leases)+[dict(x) for x in scoped]:
            x=dict(item)
            key=(x["lease_id"],x.get("submission_id"))
            merged[key]=x
        leases=list(merged.values())

    detail=[dict(x) for x in leases]
    accepted=[x for x in detail if x.get("decision")=="ACCEPT_E1"]
    pending=[x for x in detail if x.get("evidence_label")=="LEAD_READY"
             and x.get("decision")=="PENDING"]
    active=[x for x in detail if x.get("state")=="ACTIVE"]
    recoverable=[x for x in detail
                 if x.get("state") in ("STALE","TTL_EXPIRED")
                 and not x.get("submission_id")]
    if accepted:
        status="ACCEPT_E1_AVAILABLE";ok=True
    elif pending:
        status="PENDING_AUDIT";ok=True
    elif active:
        status="IN_PROGRESS";ok=(lifecycle=="active")
    elif recoverable and lifecycle=="active":
        status="RECOVERABLE_INTERRUPTED";ok=True
    elif detail:
        status="CONSUMED_NON_E1";ok=False
    elif lifecycle=="active":
        status="AVAILABLE_UNCLAIMED";ok=True
    else:
        status="NOT_ACTIVE";ok=False
    return {"ok":ok,"status":status,"backlog_id":backlog_id,
            "backlog_lifecycle":lifecycle,"leases":detail,
            "accepted_submissions":[x.get("submission_id") for x in accepted],
            "pending_submissions":[x.get("submission_id") for x in pending],
            "recoverable_leases":[x.get("lease_id") for x in recoverable]}


def evaluate(contract_path=DEFAULT_CONTRACT, candidate_path=DEFAULT_CANDIDATE, db_path=DEFAULT_DB):
    contract_path=Path(contract_path).resolve()
    candidate_path=Path(candidate_path).resolve()
    db_path=Path(db_path).resolve()
    project_root=contract_path.parent.parent
    contract = load_json(contract_path)
    candidate = load_json(candidate_path)
    if contract.get("schema") != "xiaoyu-p1-integration-contract-v1":
        raise ValueError("unsupported integration contract schema")
    if candidate.get("schema") != "xiaoyu-p1-integration-candidate-v1":
        raise ValueError("unsupported integration candidate schema")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    errors = []
    warnings = []
    stages = []
    try:
        pins = candidate.get("stage_pins", {})
        for spec in contract.get("stages", []):
            sid = spec["id"]
            pin = pins.get(sid)
            deps=spec.get("depends_on_stages")
            if deps is None:
                one=spec.get("depends_on_stage")
                deps=[one] if one else []
            row_out = {
                "id": sid,
                "required": bool(spec.get("required", False)),
                "contract_status": spec.get("status"),
                "candidate_present": isinstance(pin, dict),
                "ready": False,
                "depends_on": list(deps),
                "checks": [],
            }
            if not isinstance(pin, dict):
                errors.append({"stage": sid, "type": "candidate_stage_missing"})
                row_out["intrinsic_ready"]=False
                stages.append(row_out)
                continue

            accepted_id = spec.get("accepted_submission")
            if accepted_id:
                row = fetch_submission(con, accepted_id)
                ok = bool(row and row["decision"] == "ACCEPT_E1")
                row_out["checks"].append(
                    {"type": "accepted_e1", "submission": accepted_id, "ok": ok,
                     "actual": row["decision"] if row else "MISSING"}
                )
                if not ok:
                    errors.append({"stage": sid, "type": "accepted_e1_not_accepted",
                                   "submission": accepted_id,
                                   "actual": row["decision"] if row else "MISSING"})
                if pin.get("submission") not in (accepted_id, None):
                    errors.append({"stage": sid, "type": "candidate_submission_mismatch",
                                   "expected": accepted_id, "actual": pin.get("submission")})

            pending_id = spec.get("pending_submission")
            if pending_id:
                row = fetch_submission(con, pending_id)
                actual = row["decision"] if row else "MISSING"
                row_out["checks"].append(
                    {"type": "pending_or_advanced", "submission": pending_id,
                     "ok": actual in ("PENDING", "ACCEPT_E1", "NEEDS_WORK"),
                     "actual": actual}
                )
                if actual == "MISSING":
                    errors.append({"stage": sid, "type": "pending_submission_missing",
                                   "submission": pending_id})
                elif actual == "ACCEPT_E1":
                    warnings.append({"stage": sid, "type": "pending_status_advanced",
                                     "submission": pending_id,
                                     "note": "Update the integration contract/candidate before using the new evidence."})
                elif actual == "NEEDS_WORK":
                    warnings.append({"stage": sid, "type": "pending_candidate_needs_work",
                                     "submission": pending_id})

            lead_e0=spec.get("lead_e0")
            if isinstance(lead_e0,dict):
                metric_ref=lead_e0.get("metrics")
                metric_path=Path(str(metric_ref)) if metric_ref else None
                if metric_path is not None and not metric_path.is_absolute():
                    metric_path=project_root/metric_path
                e0_ok=False
                e0_actual="MISSING"
                if metric_path is not None and metric_path.is_file():
                    try:
                        metrics=load_json(metric_path)
                        schema_ok=(not lead_e0.get("expected_schema")
                                   or metrics.get("schema")==lead_e0.get("expected_schema"))
                        e0_ok=bool(metrics.get("pass") is True and schema_ok)
                        e0_actual={
                            "pass":metrics.get("pass"),
                            "schema":metrics.get("schema"),
                            "path":str(metric_path),
                        }
                    except Exception as exc:
                        e0_actual="INVALID:"+type(exc).__name__+":"+str(exc)
                row_out["checks"].append({
                    "type":"lead_e0_pass","ok":e0_ok,"actual":e0_actual
                })
                if not e0_ok:
                    errors.append({"stage":sid,"type":"lead_e0_missing_or_nonpass",
                                   "metrics":str(metric_path) if metric_path else None,
                                   "actual":e0_actual})
                backlog_id=lead_e0.get("replication_backlog_id")
                if backlog_id:
                    path_status=backlog_path_status(con,project_root,backlog_id)
                    row_out["checks"].append({
                        "type":"replication_path","backlog_id":backlog_id,
                        "ok":path_status["ok"],"actual":path_status
                    })
                    if not path_status["ok"]:
                        errors.append({"stage":sid,"type":"replication_path_unavailable",
                                       "backlog_id":backlog_id,"actual":path_status})
                    elif path_status["status"]=="ACCEPT_E1_AVAILABLE":
                        pinned=spec.get("accepted_submission")
                        already_pinned=(pinned in set(path_status["accepted_submissions"])
                                        and spec.get("status") in (
                                            "ready_e1",
                                            "ready_semantics_e1_integration_e0",
                                            "ready_semantics_e1_storage_e0"))
                        if not already_pinned:
                            warnings.append({"stage":sid,"type":"replication_e1_available",
                                             "backlog_id":backlog_id,
                                             "submissions":path_status["accepted_submissions"],
                                             "note":"Lead may explicitly revise the integration contract; no auto-promotion."})

            for supporting in spec.get("supporting_lead_e0",[]):
                metric_ref=supporting.get("metrics")
                metric_path=Path(str(metric_ref)) if metric_ref else None
                if metric_path is not None and not metric_path.is_absolute():
                    metric_path=project_root/metric_path
                e0_ok=False
                e0_actual="MISSING"
                if metric_path is not None and metric_path.is_file():
                    try:
                        metrics=load_json(metric_path)
                        schema_ok=(not supporting.get("expected_schema")
                                   or metrics.get("schema")==supporting.get("expected_schema"))
                        e0_ok=bool(metrics.get("pass") is True and schema_ok)
                        e0_actual={
                            "pass":metrics.get("pass"),
                            "schema":metrics.get("schema"),
                            "path":str(metric_path),
                        }
                    except Exception as exc:
                        e0_actual="INVALID:"+type(exc).__name__+":"+str(exc)
                row_out["checks"].append({
                    "type":"supporting_lead_e0_pass","ok":e0_ok,
                    "name":supporting.get("name"),"actual":e0_actual
                })
                if not e0_ok:
                    errors.append({
                        "stage":sid,"type":"supporting_lead_e0_missing_or_nonpass",
                        "name":supporting.get("name"),
                        "metrics":str(metric_path) if metric_path else None,
                        "actual":e0_actual
                    })

            remediation_id=spec.get("remediation_backlog_id")
            if remediation_id:
                path_status=backlog_path_status(con,project_root,remediation_id)
                row_out["checks"].append({
                    "type":"remediation_path","backlog_id":remediation_id,
                    "ok":path_status["ok"],"actual":path_status
                })
                if not path_status["ok"]:
                    errors.append({"stage":sid,"type":"remediation_path_unavailable",
                                   "backlog_id":remediation_id,"actual":path_status})
                elif path_status["status"]=="ACCEPT_E1_AVAILABLE":
                    pinned=spec.get("accepted_submission")
                    already_pinned=(pinned in set(path_status["accepted_submissions"])
                                    and spec.get("status") in (
                                        "ready_e1",
                                        "ready_semantics_e1_integration_e0",
                                        "ready_semantics_e1_storage_e0"))
                    if not already_pinned:
                        warnings.append({"stage":sid,"type":"remediation_e1_available",
                                         "backlog_id":remediation_id,
                                         "submissions":path_status["accepted_submissions"],
                                         "note":"Lead must update the frozen contract/candidate before declaring this stage ready."})

            for lf in spec.get("local_falsifiers",[]):
                metric_ref=lf.get("metrics")
                metric_path=Path(str(metric_ref)) if metric_ref else None
                if metric_path is not None and not metric_path.is_absolute():
                    metric_path=project_root/metric_path
                actual="MISSING";ok=False
                if metric_path is not None and metric_path.is_file():
                    try:
                        metrics=load_json(metric_path)
                        actual=metrics.get(lf.get("truth_key"))
                        ok=(actual==lf.get("expected"))
                    except Exception as exc:
                        actual="INVALID:"+type(exc).__name__+":"+str(exc)
                row_out["checks"].append({
                    "type":"local_falsifier","metrics":str(metric_path) if metric_path else None,
                    "truth_key":lf.get("truth_key"),"expected":lf.get("expected"),
                    "actual":actual,"ok":ok,"blocks":lf.get("blocks",[])
                })
                if not ok:
                    errors.append({"stage":sid,"type":"local_falsifier_missing_or_unmatched",
                                   "metrics":str(metric_path) if metric_path else None,
                                   "truth_key":lf.get("truth_key"),
                                   "expected":lf.get("expected"),"actual":actual})

            blocker_times = []
            for blocker in spec.get("known_later_blockers", []):
                row = fetch_submission(con, blocker)
                actual = row["decision"] if row else "MISSING"
                row_out["checks"].append(
                    {"type": "known_later_blocker", "submission": blocker,
                     "ok": actual == "NEEDS_WORK", "actual": actual}
                )
                if row:
                    blocker_times.append(float(row["at"]))
                if actual != "NEEDS_WORK":
                    errors.append({"stage": sid, "type": "blocker_state_unexpected",
                                   "submission": blocker, "actual": actual})

            # No stale implementation pin may name an implementation explicitly blocked by contract.
            implementation = pin.get("implementation")
            if implementation and implementation in set(spec.get("blocked_implementations", [])):
                errors.append({"stage": sid, "type": "blocked_implementation_pinned",
                               "implementation": implementation})

            # A blocked replacement stage is allowed to remain blocked, but the doctor tells Lead
            # if a newer accepted replacement exists so the contract can be explicitly revised.
            if spec.get("status") == "blocked_replacement_required":
                latest = max(blocker_times) if blocker_times else 0.0
                replacements = accepted_replacements(
                    con, spec.get("replacement_lineage", ""), latest
                ) if spec.get("replacement_lineage") else []
                row_out["accepted_replacements_after_blocker"] = [dict(r) for r in replacements]
                if replacements:
                    warnings.append({
                        "stage": sid,
                        "type": "replacement_e1_available",
                        "submissions": [r["submission_id"] for r in replacements],
                        "note": "Do not auto-upgrade. Lead must review and revise the frozen candidate."
                    })

            if sid == "global_source_aware_retrieval":
                expected_storage = spec.get("lexical_storage")
                actual_storage = pin.get("lexical_storage")
                ok = actual_storage == expected_storage
                row_out["checks"].append(
                    {"type": "lexical_storage", "ok": ok,
                     "expected": expected_storage, "actual": actual_storage}
                )
                if not ok:
                    errors.append({"stage": sid, "type": "wrong_lexical_storage",
                                   "expected": expected_storage, "actual": actual_storage})

            # Contract status is intentionally conservative.
            status = spec.get("status", "")
            if status in ("ready_e1", "ready_semantics_e1_integration_e0"):
                row_out["ready"] = not any(e.get("stage") == sid for e in errors)
            elif status == "ready_semantics_e1_storage_e0":
                row_out["ready"] = not any(e.get("stage") == sid for e in errors)
            elif status == "ready_e1_runtime_hardening_pending":
                # Core E1 is ready; E2 integration is still not complete until pending runtime work is resolved.
                row_out["ready"] = False
            elif status in ("pending_e1", "blocked_replacement_required", "blocked_no_e1"):
                row_out["ready"] = False

            # Preserve the stage's own evidence/contract readiness before dependency propagation.
            row_out["intrinsic_ready"]=bool(row_out["ready"])
            stages.append(row_out)
    finally:
        con.close()

    # Dependency readiness is evaluated after all stages so contract order does not matter.
    # A blocked dependency is an expected readiness blocker, not a contract-health error.
    stage_map={s["id"]:s for s in stages}

    # Contract dependencies must form a DAG. A ready<->ready cycle could otherwise
    # remain "ready" under fixed-point propagation even though there is no valid
    # upstream assembly order.
    visiting=set()
    visited=set()
    stack=[]
    cycle_keys=set()
    def visit_cycle(sid):
        if sid in visited:
            return
        if sid in visiting:
            try:
                idx=stack.index(sid)
                cycle=stack[idx:]+[sid]
            except ValueError:
                cycle=[sid,sid]
            key=" -> ".join(cycle)
            if key not in cycle_keys:
                cycle_keys.add(key)
                errors.append({"type":"dependency_cycle","cycle":cycle})
            return
        visiting.add(sid);stack.append(sid)
        row=stage_map.get(sid)
        if row is not None:
            for dep_id in row.get("depends_on",[]):
                if dep_id in stage_map:
                    visit_cycle(dep_id)
        stack.pop();visiting.remove(sid);visited.add(sid)
    for sid in stage_map:
        visit_cycle(sid)

    changed=True
    while changed:
        changed=False
        for row in stages:
            for dep_id in row.get("depends_on",[]):
                dep=stage_map.get(dep_id)
                if dep is None:
                    if not any(e.get("stage")==row["id"] and e.get("type")=="dependency_stage_missing"
                               and e.get("dependency")==dep_id for e in errors):
                        errors.append({"stage":row["id"],"type":"dependency_stage_missing",
                                       "dependency":dep_id})
                    row["checks"].append({"type":"stage_dependency","dependency":dep_id,
                                          "ok":False,"actual":"MISSING"})
                    if row["ready"]:
                        row["ready"]=False;changed=True
                    continue
                # Add a single final dependency check for reporting.
                prior=next((c for c in row["checks"]
                            if c.get("type")=="stage_dependency" and c.get("dependency")==dep_id),None)
                if prior is None:
                    row["checks"].append({"type":"stage_dependency","dependency":dep_id,
                                          "ok":bool(dep["ready"]),
                                          "actual":"READY" if dep["ready"] else "BLOCKED"})
                else:
                    prior["ok"]=bool(dep["ready"])
                    prior["actual"]="READY" if dep["ready"] else "BLOCKED"
                if row["ready"] and not dep["ready"]:
                    row["ready"]=False;changed=True

    required = [s for s in stages if s["required"]]
    blocked_required = [s["id"] for s in required if not s["ready"]]
    direct_blocked_required = [s["id"] for s in required if not s.get("intrinsic_ready",False)]
    dependency_only_blocked_required = [
        s["id"] for s in required
        if s.get("intrinsic_ready",False) and not s["ready"]
    ]

    # P1 closeout scheduling is a second machine-readable surface. Keep it
    # synchronized with the *current* direct integration blockers so a retired
    # remediation cannot remain in closeout, and a new direct repair cannot be
    # silently omitted from the scheduler.
    closeout_sync={"checked":False,"ok":True,"expected":[],"actual":[]}
    backlog_path=project_root/"governance"/"RESEARCH_BACKLOG.json"
    if backlog_path.is_file():
        backlog=load_json(backlog_path)
        phase=backlog.get("phase_policy",{})
        if phase.get("closeout_mode"):
            spec_map={x["id"]:x for x in contract.get("stages",[])}
            expected=[]
            for sid in direct_blocked_required:
                spec=spec_map.get(sid,{})
                rid=spec.get("remediation_backlog_id") or spec.get("replication_backlog_id")
                if not rid:
                    lead=spec.get("lead_e0",{})
                    if lead.get("replication_required"):
                        rid=lead.get("replication_backlog_id")
                if rid:
                    expected.append(str(rid))
                else:
                    errors.append({"stage":sid,"type":"direct_blocker_without_closeout_path"})
            expected=sorted(set(expected))
            actual=sorted(set(str(x) for x in phase.get("closeout_required_backlog",[])))
            closeout_sync={"checked":True,"ok":expected==actual,
                           "expected":expected,"actual":actual}
            if expected!=actual:
                errors.append({"type":"closeout_backlog_drift",
                               "expected":expected,"actual":actual})

    report = {
        "schema": "xiaoyu-p1-integration-doctor-v1",
        "contract": str(contract_path),
        "candidate": str(candidate_path),
        "contract_errors": errors,
        "warnings": warnings,
        "stages": stages,
        "required_stage_count": len(required),
        "required_ready_count": len(required) - len(blocked_required),
        "blocked_required_stages": blocked_required,
        "direct_blocked_required_stages": direct_blocked_required,
        "dependency_only_blocked_required_stages": dependency_only_blocked_required,
        "closeout_sync": closeout_sync,
        "contract_healthy": not errors,
        "integration_ready": not errors and not blocked_required,
        "e2_claim_allowed": False,
        "note": (
            "P1 integration contract is ready; E2 remains disabled and this doctor does not grant scientific/product promotion."
            if (not errors and not blocked_required)
            else "integration_ready=false is expected while known P1 blockers remain. This doctor validates assembly discipline; it does not promote evidence."
        ),
    }
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    ap.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--require-ready", action="store_true")
    args = ap.parse_args()
    report = evaluate(args.contract, args.candidate, args.db)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["contract_healthy"]:
        raise SystemExit(2)
    if args.require_ready and not report["integration_ready"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
