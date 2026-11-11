# -*- coding: utf-8 -*-
"""Fail-closed E2 confirmatory-prefreeze research-closeout finalizer for R52.

This script does not audit R52 and does not unlock confirmatory execution.
It only synchronizes an already independently ACCEPT_E1'd exact R52 submission
into RESEARCH_BACKLOG.json after registry, receipt, reviewer and exact-byte checks.
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
sys.path.insert(0,str(GOV))
from control import Governance

DEFAULT_SUBMISSION="sub-0cc4e587fc8a46d4"
EXPECTED_BACKLOG="R52"
EXPECTED_FAMILY="pipeline.halumem.open_domain_composition"
EXPECTED_CANDIDATE="57f7a955f724c99c8c25451801681124b2b58b7348d0d02e8a921845590d4e71"
REQUIRED_DONE={"R47","R48","R49","R50","R51"}

def atomic_json(path:Path,obj):
    data=(json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def check_registry(root:Path,submission_id:str):
    con=sqlite3.connect(root/"governance"/"registry.sqlite3"); con.row_factory=sqlite3.Row
    try:
        sub=con.execute(
          """select s.*,l.agent_id as author,l.family,l.backlog_id,l.workspace
             from submissions s join leases l on l.lease_id=s.lease_id
             where s.submission_id=?""",(submission_id,)).fetchone()
        if sub is None: raise RuntimeError("R52 submission not found")
        if sub["evidence_label"]!="LEAD_READY": raise RuntimeError("R52 submission is not LEAD_READY")
        if sub["family"]!=EXPECTED_FAMILY or sub["backlog_id"]!=EXPECTED_BACKLOG:
            raise RuntimeError("Submission is not the exact R52 backlog claim")
        if sub["decision"]!="ACCEPT_E1": raise RuntimeError("R52 is not ACCEPT_E1")
        reviewer=sub["decided_by"]
        if not reviewer or reviewer==sub["author"]: raise RuntimeError("Independent reviewer missing")
        agent=con.execute("select role from agents where agent_id=?",(reviewer,)).fetchone()
        if agent is None or agent["role"]!="auditor": raise RuntimeError("Reviewer is not registered auditor")
        review=con.execute(
          """select * from reviews where submission_id=? and reviewer_id=? and decision='ACCEPT_E1'
             order by at desc""",(submission_id,reviewer)).fetchone()
        if review is None: raise RuntimeError("ACCEPT_E1 review row missing")
        if int(review["material_count"] or 0)!=0: raise RuntimeError("Review has material findings")
        manifest=json.loads(Path(sub["manifest_path"]).read_text(encoding="utf-8"))
        actual=(manifest.get("hashes") or {}).get("composition_v8")
        if actual!=EXPECTED_CANDIDATE:
            raise RuntimeError("R52 exact composition_v8 SHA mismatch")
        if int(manifest.get("provider_calls") or 0)!=0:
            raise RuntimeError("R52 unexpectedly used provider calls")
        if int(manifest.get("confirmatory_users_read") or 0)!=0:
            raise RuntimeError("R52 unexpectedly read confirmatory users")
        if manifest.get("confirmatory_execution_allowed") is not False:
            raise RuntimeError("R52 manifest unexpectedly authorizes confirmatory execution")
        return dict(sub),dict(review),manifest
    finally:
        con.close()

def finalize(root:Path,submission_id:str,dry_run=False):
    sub,review,manifest=check_registry(root,submission_id)
    g=Governance(root)
    try: receipt=g.verify_receipt(submission_id)
    finally: g.close()
    if receipt.get("integrity")!="PASS": raise RuntimeError("R52 receipt integrity is not PASS")

    bp=root/"governance"/"RESEARCH_BACKLOG.json"
    backlog=json.loads(bp.read_text(encoding="utf-8"))
    rows={x["id"]:x for x in backlog.get("candidates",[])}
    r52=rows.get(EXPECTED_BACKLOG)
    if r52 is None: raise RuntimeError("R52 backlog row missing")
    if r52.get("status")=="done" and r52.get("completion_submission")==submission_id:
        return {"status":"ALREADY_FINALIZED","submission_id":submission_id,
                "review_id":review["review_id"],"receipt_integrity":"PASS"}
    if r52.get("status")!="active":
        raise RuntimeError("R52 is not active at finalization: "+str(r52.get("status")))

    for bid in REQUIRED_DONE:
        row=rows.get(bid)
        if row is None or row.get("status")!="done" or row.get("completion_level")!="ACCEPT_E1":
            raise RuntimeError(f"Required predecessor {bid} is not done/ACCEPT_E1")

    phase=backlog.get("phase_policy",{})
    if phase.get("current_phase")!="E2_PILOT":
        raise RuntimeError("Current phase is not E2_PILOT")
    if sorted(phase.get("closeout_required_backlog",[]))!=[EXPECTED_BACKLOG]:
        raise RuntimeError("E2 closeout backlog is not exactly R52")
    if phase.get("e2_confirmatory_calls_allowed") is not False:
        raise RuntimeError("Confirmatory calls unexpectedly already allowed")

    r52["status"]="done"
    r52["completion_submission"]=submission_id
    r52["completion_level"]="ACCEPT_E1"
    r52["completion_review"]=review["review_id"]
    r52["completion_note"]=(
      "Independent exact-byte R52 full-dialogue composition audit ACCEPT_E1. "
      "Receipt integrity and 53/53 original artifact SHA bindings verified; "
      "hardening 128/128, runtime authority 130/130, insufficient-evidence "
      "24/24 + 8/8 controls, prospective 48/48, ambiguity 30/30 and exact "
      "restart/replay reproduced with zero provider calls and zero confirmatory "
      "user reads. One nonblocking P3 clerical advisory remains: transitive "
      "evidence index omitted byte-size fields although its SHA bindings are intact."
    )
    phase["closeout_required_backlog"]=[]
    phase["auto_assign_plans"]=[]
    phase["closeout_reason"]=(
      "All direct E2 confirmatory pre-freeze research blockers through R52 are "
      "independently ACCEPT_E1. Research remains closed while Lead binds exact "
      "accepted bytes into final runners/judge/scorer and obtains the final independent v2 re-audit."
    )
    phase["closeout_unlock"]=(
      "Lead may perform deterministic confirmatory integration/freeze work only. "
      "No confirmatory record read or paid confirmatory call is allowed until exact "
      "runner/judge/scorer bindings pass the final independent v2 re-audit."
    )
    phase["e2_pilot_research_closeout_complete"]=True
    phase["e2_confirmatory_calls_allowed"]=False

    out={
      "status":"READY_TO_FINALIZE" if dry_run else "FINALIZED",
      "submission_id":submission_id,
      "reviewer":sub["decided_by"],
      "review_id":review["review_id"],
      "material_findings":int(review["material_count"] or 0),
      "advisory_findings":int(review["advisory_count"] or 0),
      "candidate_sha256":EXPECTED_CANDIDATE,
      "receipt_integrity":receipt["integrity"],
      "required_done":sorted(REQUIRED_DONE),
      "confirmatory_calls_allowed":False,
    }
    if dry_run: return out
    atomic_json(bp,backlog)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--submission-id",default=DEFAULT_SUBMISSION)
    ap.add_argument("--dry-run",action="store_true")
    args=ap.parse_args()
    try: out=finalize(ROOT,args.submission_id,args.dry_run)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False,indent=2))
        raise SystemExit(2)
    print(json.dumps({"ok":True,"result":out},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
