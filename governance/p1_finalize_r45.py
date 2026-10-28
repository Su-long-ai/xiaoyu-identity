# -*- coding: utf-8 -*-
"""Fail-closed P1 closeout finalizer for R45.

This script never audits evidence. It only synchronizes the already-frozen
P1 contract/candidate/backlog after an independent auditor has ACCEPT_E1'd the
exact R45 submission with zero material findings.

Until then it exits nonzero without modifying project files.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
sys.path.insert(0,str(GOV))
from control import Governance

DEFAULT_SUBMISSION="sub-a650809e040046aa"
EXPECTED_BACKLOG="R45"
EXPECTED_FAMILY="privacy.erasure.provenance_context_separation"
EXPECTED_STAGE="erasure_restore_reconciliation"

def atomic_json(path:Path,obj):
    data=(json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass

def check(root:Path,submission_id:str):
    db=root/"governance"/"registry.sqlite3"
    con=sqlite3.connect(db);con.row_factory=sqlite3.Row
    try:
        sub=con.execute(
          """select s.*,l.agent_id as author,l.role as author_role,l.family,l.backlog_id,l.workspace
             from submissions s join leases l on l.lease_id=s.lease_id
            where s.submission_id=?""",(submission_id,)).fetchone()
        if sub is None:
            raise RuntimeError("R45 submission not found")
        if sub["evidence_label"]!="LEAD_READY":
            raise RuntimeError("R45 submission is not LEAD_READY")
        if sub["family"]!=EXPECTED_FAMILY or sub["backlog_id"]!=EXPECTED_BACKLOG:
            raise RuntimeError("Submission is not the frozen R45 backlog claim")
        if sub["decision"]!="ACCEPT_E1":
            raise RuntimeError("R45 is not independently ACCEPT_E1: "+str(sub["decision"]))
        reviewer=sub["decided_by"]
        if not reviewer or reviewer==sub["author"]:
            raise RuntimeError("Independent auditor identity missing or equals author")
        agent=con.execute("select role from agents where agent_id=?",(reviewer,)).fetchone()
        if agent is None or agent["role"]!="auditor":
            raise RuntimeError("R45 decision was not made by a registered auditor")
        reviews=con.execute(
          """select * from reviews where submission_id=? and reviewer_id=? and decision='ACCEPT_E1'
             order by at desc""",(submission_id,reviewer)).fetchall()
        if not reviews:
            raise RuntimeError("Independent ACCEPT_E1 review row missing")
        review=reviews[0]
        if int(review["material_count"] or 0)!=0:
            raise RuntimeError("ACCEPT_E1 review still contains material findings")
        return dict(sub),dict(review)
    finally:
        con.close()

def finalize(root:Path,submission_id:str,dry_run=False):
    sub,review=check(root,submission_id)

    # Receipt verification is delegated to the existing governance authority.
    g=Governance(root)
    try:
        receipt=g.verify_receipt(submission_id)
    finally:
        g.close()
    if receipt.get("integrity")!="PASS":
        raise RuntimeError("R45 receipt integrity is not PASS")

    cp=root/"governance"/"P1_INTEGRATION_CONTRACT.json"
    ip=root/"governance"/"P1_INTEGRATION_CANDIDATE.json"
    bp=root/"governance"/"RESEARCH_BACKLOG.json"
    contract=json.loads(cp.read_text(encoding="utf-8"))
    candidate=json.loads(ip.read_text(encoding="utf-8"))
    backlog=json.loads(bp.read_text(encoding="utf-8"))

    stages={x["id"]:x for x in contract["stages"]}
    stage=stages.get(EXPECTED_STAGE)
    if stage is None:
        raise RuntimeError("P1 erasure stage missing")
    if stage.get("remediation_backlog_id")!=EXPECTED_BACKLOG:
        raise RuntimeError("P1 contract no longer points erasure stage at R45")

    required_integration=[]
    for item in stage.get("supporting_lead_e0",[]):
        if not isinstance(item,dict) or not item.get("required_for_finalization"):
            continue
        rel=item.get("metrics")
        expected_schema=item.get("expected_schema")
        if not isinstance(rel,str) or not rel:
            raise RuntimeError("Required integration E0 has no metrics path")
        mp=root/rel
        if not mp.is_file():
            raise RuntimeError("Required integration E0 metrics missing: "+rel)
        try:
            metrics=json.loads(mp.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("Required integration E0 metrics unreadable: "+rel) from exc
        if expected_schema and metrics.get("schema")!=expected_schema:
            raise RuntimeError("Required integration E0 schema mismatch: "+rel)
        if metrics.get("pass") is not True:
            raise RuntimeError("Required integration E0 is not PASS: "+rel)
        required_integration.append({
          "metrics":rel,"schema":metrics.get("schema"),"pass":True,
        })
    if not required_integration:
        raise RuntimeError("P1 erasure stage has no required integration E0 gate")

    if stage.get("status") not in ("blocked_no_e1","pending_e1"):
        # Idempotent only if already pinned to this exact submission.
        if stage.get("status")=="ready_e1" and stage.get("accepted_submission")==submission_id:
            return {"status":"ALREADY_FINALIZED","submission_id":submission_id,
                    "reviewer":sub["decided_by"],"receipt":receipt}
        raise RuntimeError("Unexpected erasure-stage status: "+str(stage.get("status")))

    rows={x["id"]:x for x in backlog["candidates"]}
    r45=rows.get(EXPECTED_BACKLOG)
    if r45 is None:
        raise RuntimeError("R45 backlog row missing")
    if r45.get("status")!="active":
        raise RuntimeError("R45 backlog is not active at finalization: "+str(r45.get("status")))
    phase=backlog.get("phase_policy",{})
    if sorted(phase.get("closeout_required_backlog",[]))!=[EXPECTED_BACKLOG]:
        raise RuntimeError("P1 closeout backlog is not exactly R45")

    accepted_scope=(
      "R45 ACCEPT_E1: validated raw evidence_quote/source plaintext remain sealed non-model-visible provenance; "
      "model-visible canonical memory exposes event-local op/slot/value semantics plus opaque quote/source hashes. "
      "Fresh frozen Research evidence and independent audit support that representation boundary. P1 integration "
      "also requires the frozen Lead event-local-history bridge: untouched source history may retain the existing "
      "raw representation, but a source touched by event-level erasure/invalidation becomes raw-provenance-only "
      "and exposes surviving event-local history semantics selected by trusted erasure lineage. Together these "
      "close R44 wide/adjacent quote resurrection and the message-level raw-history partial-erasure path while "
      "preserving trusted effective_at stale-rekey rejection, restart, surviving SET/CLEAR semantics and genuine "
      "newer cross-conversation reaffirmation. No physical source/backup erase or low-entropy hash secrecy claim."
    )

    stage["status"]="ready_e1"
    stage["accepted_submission"]=submission_id
    stage["integration_rule"]=accepted_scope
    stage["audit"]={
      "reviewer":sub["decided_by"],
      "review_id":review["review_id"],
      "material_findings":int(review["material_count"] or 0),
      "advisory_findings":int(review["advisory_count"] or 0),
      "reason":review["reason"],
    }
    stage["required_integration_e0_verified"]=required_integration

    candidate["stage_pins"][EXPECTED_STAGE]={
      "submission":submission_id,
      "implementation":"provenance_context_separation",
      "accepted_scope":"sealed raw provenance; model-visible event-local semantics + opaque provenance hashes",
      "audit_reviewer":sub["decided_by"],
      "known_predecessor_needs_work":["sub-7247623e964946bd","sub-a22bcd5d53de47fb"],
      "integration_adapter":{
        "kind":"event_local_history_after_partial_erasure",
        "verified":required_integration,
      },
      "nonclaims":[
        "physical deletion of raw source/backups",
        "offline secrecy of low-entropy plaintext represented by deterministic hashes",
        "direct model visibility of partially erased multi-fact raw SOURCE/history",
      ],
    }

    r45["status"]="done"
    r45["completion_submission"]=submission_id
    r45["completion_level"]="ACCEPT_E1"
    r45["completion_note"]="Independent R45 audit accepted; pinned into the P1 erasure/provenance-context stage."
    phase["closeout_required_backlog"]=[]
    phase["closeout_reason"]="All required P1 integration stages have accepted evidence pinned. Keep closeout mode until Lead verifies Integration Doctor; this does not unlock E2."
    phase["p1_research_closeout_complete"]=True

    result={
      "status":"READY_TO_FINALIZE" if dry_run else "FINALIZED",
      "submission_id":submission_id,
      "reviewer":sub["decided_by"],
      "review_id":review["review_id"],
      "material_findings":int(review["material_count"] or 0),
      "advisory_findings":int(review["advisory_count"] or 0),
      "receipt_integrity":receipt["integrity"],
      "required_integration_e0":required_integration,
    }
    if dry_run:
        return result
    atomic_json(cp,contract)
    atomic_json(ip,candidate)
    atomic_json(bp,backlog)
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--submission-id",default=DEFAULT_SUBMISSION)
    ap.add_argument("--dry-run",action="store_true")
    args=ap.parse_args()
    try:
        out=finalize(ROOT,args.submission_id,args.dry_run)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False,indent=2))
        raise SystemExit(2)
    print(json.dumps({"ok":True,"result":out},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
