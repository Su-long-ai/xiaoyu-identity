#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 closeout doctor. Local metadata only; never calls a model/network."""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path
import p1_integration_doctor as p1

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
DEFAULT_CONTRACT=GOV/"P2_INTEGRATION_CONTRACT.json"
DEFAULT_DB=GOV/"registry.sqlite3"

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def stage_status(con,spec):
    src=spec.get("source")
    if src=="fixed_submission":
        row=con.execute("""select s.submission_id,s.decision,s.evidence_label,
          l.family,l.lineage,l.agent_id,l.lease_id
          from submissions s join leases l on l.lease_id=s.lease_id
          where s.submission_id=?""",(spec["submission_id"],)).fetchone()
        if row is None:
            return {"ready":False,"status":"MISSING_SUBMISSION"}
        d=dict(row)
        scope_ok=(d["family"]==spec.get("expected_family") and d["lineage"]==spec.get("expected_lineage"))
        return {"ready":d["decision"]=="ACCEPT_E1" and scope_ok,
                "status":d["decision"],"scope_ok":scope_ok,"submission":d}
    if src=="fixed_or_remediation":
        row=con.execute("""select s.submission_id,s.decision,s.evidence_label,
          l.family,l.lineage,l.agent_id,l.lease_id
          from submissions s join leases l on l.lease_id=s.lease_id
          where s.submission_id=?""",(spec["submission_id"],)).fetchone()
        original=dict(row) if row is not None else None
        original_ok=bool(original and original["decision"]=="ACCEPT_E1"
                         and original["family"]==spec.get("expected_family")
                         and original["lineage"]==spec.get("expected_lineage"))
        if original_ok:
            return {"ready":True,"status":"ACCEPT_E1","submission":original,
                    "resolution":"original"}
        rows=con.execute("""select s.submission_id,s.decision,s.at,l.family,l.lineage,
          l.agent_id,l.lease_id,l.state
          from leases l left join submissions s on s.lease_id=l.lease_id
          where l.family=? and l.lineage=? order by l.claimed_at,s.at""",
          (spec["remediation_family"],spec["remediation_lineage"])).fetchall()
        accepted=[dict(r) for r in rows if r["decision"]=="ACCEPT_E1"]
        active=[dict(r) for r in rows if r["state"]=="ACTIVE"]
        pending=[dict(r) for r in rows if r["decision"]=="PENDING"]
        if accepted:
            return {"ready":True,"status":"REMEDIATED_ACCEPT_E1",
                    "original":original,"remediation":accepted[-1],
                    "resolution":"remediation"}
        if pending:
            return {"ready":False,"status":"REMEDIATION_PENDING",
                    "original":original,"pending":pending}
        if active:
            return {"ready":False,"status":"REMEDIATION_ACTIVE",
                    "original":original,"active":active}
        return {"ready":False,
                "status":(original["decision"] if original else "MISSING"),
                "original":original,"remediation":"MISSING"}
    if src=="accepted_family":
        rows=con.execute("""select s.submission_id,s.decision,s.at,l.family,l.lineage,
          l.agent_id,l.lease_id,l.state
          from leases l left join submissions s on s.lease_id=l.lease_id
          where l.family=? and l.lineage=? order by l.claimed_at,s.at""",
          (spec["family"],spec["lineage"])).fetchall()
        accepted=[dict(r) for r in rows if r["decision"]=="ACCEPT_E1"]
        active=[dict(r) for r in rows if r["state"]=="ACTIVE"]
        if accepted:
            return {"ready":True,"status":"ACCEPT_E1","accepted":accepted[-1],"active":active}
        if active:
            return {"ready":False,"status":"ACTIVE","active":active}
        pending=[dict(r) for r in rows if r["decision"]=="PENDING"]
        if pending:
            return {"ready":False,"status":"PENDING","pending":pending}
        return {"ready":False,"status":"MISSING"}
    return {"ready":False,"status":"INVALID_STAGE_SOURCE"}

def evaluate(contract_path=DEFAULT_CONTRACT,db_path=DEFAULT_DB):
    c=load(contract_path);errors=[];warnings=[]
    if c.get("schema")!="xiaoyu-p2-integration-contract-v1":
        errors.append({"type":"contract_schema"})
    stages=c.get("stages",[])
    ids=[x.get("id") for x in stages]
    if len(ids)!=len(set(ids)): errors.append({"type":"duplicate_stage_id"})
    base=c.get("p1_baseline",{})
    hash_checks={}
    for key,sha_key in (("contract","contract_sha256"),("candidate","candidate_sha256")):
        path=ROOT/base[key]
        got=sha(path) if path.is_file() else None
        exp=base.get(sha_key)
        hash_checks[key]={"path":str(path),"expected":exp,"actual":got,"ok":got==exp}
        if got!=exp: errors.append({"type":"p1_baseline_hash_drift","file":key,"expected":exp,"actual":got})
    try:
        p1r=p1.evaluate()
        p1_ready=bool(p1r.get("integration_ready"))
    except Exception as exc:
        p1r={"error":type(exc).__name__+":"+str(exc)};p1_ready=False
    if not p1_ready: errors.append({"type":"p1_not_integration_ready"})
    con=sqlite3.connect(db_path);con.row_factory=sqlite3.Row
    out=[]
    try:
        for spec in stages:
            s=stage_status(con,spec)
            out.append({"id":spec.get("id"),"required":bool(spec.get("required")),
                        "note":spec.get("note"),**s})
    finally: con.close()
    req=[x for x in out if x["required"]]
    blocked=[x["id"] for x in req if not x["ready"]]
    return {
      "schema":"xiaoyu-p2-integration-doctor-v1",
      "contract":str(contract_path),
      "p1_baseline_hashes":hash_checks,
      "p1_integration_ready":p1_ready,
      "contract_errors":errors,
      "warnings":warnings,
      "stages":out,
      "required_stage_count":len(req),
      "required_ready_count":len(req)-len(blocked),
      "blocked_required_stages":blocked,
      "contract_healthy":not errors,
      "p2_closeout_ready":not errors and not blocked,
      "e2_claim_allowed":False,
      "note":"P2 closeout readiness does not unlock E2; a separate frozen prospective E2 protocol is required."
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--contract",type=Path,default=DEFAULT_CONTRACT)
    ap.add_argument("--db",type=Path,default=DEFAULT_DB)
    ap.add_argument("--require-ready",action="store_true")
    a=ap.parse_args()
    r=evaluate(a.contract,a.db)
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if not r["contract_healthy"]: raise SystemExit(2)
    if a.require_ready and not r["p2_closeout_ready"]: raise SystemExit(3)
if __name__=="__main__":main()
