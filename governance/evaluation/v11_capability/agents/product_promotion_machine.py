# -*- coding:utf-8 -*-
"""The machine-enforced extension to the existing promotion queue.

No new queue or product state store. Research P0 does not erase useful
hypotheses; default-on, external QQ and V1 release are never performed.
"""
from __future__ import annotations
import hashlib,json,re,time
from pathlib import Path
from collections import Counter
import product_benefit_gate as portfolio

ROOT=Path(__file__).resolve().parent
CATALOG=ROOT/"results/product_promotion/REJECTED_WITH_VALUE_SIGNALS_20261106.json"
def init(c):
 c.execute("""CREATE TABLE IF NOT EXISTS product_portfolio_receipts(
 candidate_id TEXT PRIMARY KEY,receipt_path TEXT NOT NULL,
 receipt_sha256 TEXT NOT NULL,candidate_manifest_sha256 TEXT NOT NULL,
 policy TEXT NOT NULL,recorded_at REAL NOT NULL)""")
 c.execute("""CREATE TABLE IF NOT EXISTS product_historical_rescue(
 source_task TEXT PRIMARY KEY,status TEXT NOT NULL,reason TEXT NOT NULL,
 artifact_sha256 TEXT,original_negative_retained INTEGER NOT NULL DEFAULT 1,
 updated_at REAL NOT NULL)""")
def record(c,candidate_id,receipt_path):
 from product_promotion_loop import init as parent_init
 parent_init(c)
 if c.execute("SELECT 1 FROM product_candidates WHERE id=?",(candidate_id,)).fetchone() is None:
  raise ValueError("unknown_product_candidate")
 path=Path(receipt_path).resolve()
 report=portfolio.load_and_assess(path)
 if report["candidate_id"]!=candidate_id:raise ValueError("candidate_id_mismatch")
 c.execute("""INSERT INTO product_portfolio_receipts VALUES(?,?,?,?,?,?)
 ON CONFLICT(candidate_id) DO UPDATE SET
 receipt_path=excluded.receipt_path,receipt_sha256=excluded.receipt_sha256,
 candidate_manifest_sha256=excluded.candidate_manifest_sha256,
 policy=excluded.policy,recorded_at=excluded.recorded_at""",
 (candidate_id,str(path),report["receipt_sha256"],
  report["candidate"]["manifest_sha256"],report["policy"],time.time()))
 return report
def current(c,candidate_id):
 init(c)
 r=c.execute("SELECT receipt_path,receipt_sha256,candidate_manifest_sha256 FROM product_portfolio_receipts WHERE candidate_id=?",
             (candidate_id,)).fetchone()
 if r is None:return None
 p=Path(r[0])
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=r[1]:
  return {"verdict":"HOLD_MACHINE_RECEIPT_DRIFT","error":"receipt_bytes_changed"}
 try:
  val=portfolio.load_and_assess(p)
  if val["candidate_id"]!=candidate_id or val["candidate"]["manifest_sha256"]!=r[2]:
   raise ValueError("receipt_candidate_sha_mismatch")
  return val
 except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
  return {"verdict":"HOLD_MACHINE_RECEIPT_INVALID","error":str(exc)[:200]}
def _done_sha(c,x,sha):
 from product_promotion_loop import audit_disposition,task
 for tid in (x["integration_task"],x["answer_task"],x["audit_task"]):
  r=task(c,tid)
  if not r or r["status"]!="DONE" or not r["artifact"]:
   return False
  p=Path(r["artifact"])
  if not p.is_file() or sha.lower() not in p.read_text("utf8",errors="replace").lower():
   return False
 return audit_disposition(task(c,x["audit_task"]))=="PASS"
def positive(c,candidate_id):
 r=current(c,candidate_id)
 return bool(r and r.get("net_final_correct",0)>0
   and r.get("raw_paired_evidence_verified")
   and r.get("source_and_route_proven")
   and r.get("material_p0")==0 and not r.get("verdict","").startswith("HOLD_"))
def stage(c,x):
 r=current(c,x["id"])
 if r is None:return "WAIT_MACHINE_PORTFOLIO_RECEIPT"
 verdict=r.get("verdict","HOLD_MACHINE_MISSING")
 if verdict.startswith("HOLD_"):return "HOLD_MACHINE_"+verdict
 if verdict=="PILOT_REVIEW_READY_NO_AUTO_RELEASE":
  if not _done_sha(c,x,r["candidate"]["manifest_sha256"]):
   return "WAIT_EXACT_SHA_M1_M2_A1_EVIDENCE"
  return "MACHINE_PARETO_PILOT_REVIEW_READY"
 if verdict=="PARETO_TRIAL_KEEP_COLLECT_EVIDENCE":return "MACHINE_PARETO_KEEP_TRIAL_OFF"
 if verdict=="CONDITIONAL_PARETO_RESCUE":return "MACHINE_CONDITIONAL_RESCUE_TRIAL_OFF"
 return "MACHINE_"+str(verdict)
def rescue(c,limit_new=16):
 from product_promotion_loop import (init as parent_init,source_evidence,
     measured_research_value,scoped_risk_hint,register_task)
 parent_init(c)
 if not CATALOG.is_file():return {"total":0,"new_registered":0,"reasons":{}}
 items=json.loads(CATALOG.read_text("utf8"))
 if not isinstance(items,list):raise ValueError("rescue_catalog_must_be_list")
 statuses=Counter();new=0
 for item in items:
  ident=str(item.get("id") or "")
  if not re.fullmatch(r"(?:D[1-6]|M[1-3])-X\d{3}",ident):continue
  title=str(item.get("title") or "")
  summary=str(item.get("summary") or "")
  flags=item.get("signals") or {}
  sha=source_evidence(c,ident)
  risk=scoped_risk_hint(title)
  measured=measured_research_value(summary)
  h=summary.upper()
  # Real P0 only; NO_DURABLE_P0 / P0=0 are not a true P0.
  h=re.sub(r"NO_(?:DURABLE|MATERIAL|PRIVACY|AUTHORITY)_P0|P0\s*[=:]\s*0\b","CLOSED_SAFETY",h)
  p0=bool(flags.get("p0")) or bool(re.search(
      r"(?:MATERIAL|DURABLE|PRIVACY|AUTHORITY|ADMISSIBILITY)[ _-]{0,15}P0\b",h))
  existing=bool(c.execute("SELECT 1 FROM product_candidates WHERE source_task=?",(ident,)).fetchone())
  if not sha:status="WAIT_ORIGINAL_DONE_ARTIFACT"
  elif p0:status="HOLD_OLD_P0_REPAIR_SUBMECHANISM_ONLY"
  elif existing:status="ALREADY_REGISTERED_REVIEW_OR_TRIAL"
  elif not measured:status="REVIEW_NO_MEASURED_BENEFIT"
  elif risk=="unknown":status="HISTORICAL_PARETO_SCOPE_REVIEW"
  elif new>=limit_new:status="HISTORICAL_PARETO_QUEUE_BOUNDED"
  else:
   result=register_task(c,ident,value=summary[:390],priority=38,risk=risk)
   status=("RESCUED_ISOLATED_PRODUCT_TRIAL" if
           result.get("status") in ("REGISTERED_OR_ALREADY_PRESENT","ALREADY_REGISTERED_SOURCE")
           else "WAIT_ORIGINAL_DONE_ARTIFACT")
   new+=int(status=="RESCUED_ISOLATED_PRODUCT_TRIAL")
  statuses[status]+=1
  c.execute("""INSERT INTO product_historical_rescue VALUES(?,?,?,?,1,?)
 ON CONFLICT(source_task) DO UPDATE SET
 status=excluded.status,reason=excluded.reason,
 artifact_sha256=excluded.artifact_sha256,
 original_negative_retained=1,updated_at=excluded.updated_at""",
 (ident,status,"Original rejection/loss preserved; conditional net benefit prioritized; never auto release"
 if measured else "Original result preserved; no measured global value proven",sha,time.time()))
 return {"total":sum(statuses.values()),"new_registered":new,
         "reasons":dict(statuses),"old_rejection_unchanged":True,"default_on":False}
def summary(c):
 init(c)
 return {"policy":portfolio.POLICY,
         "receipt_count":c.execute("SELECT count(*) FROM product_portfolio_receipts").fetchone()[0],
         "historical_rescue_count":c.execute("SELECT count(*) FROM product_historical_rescue").fetchone()[0],
         "rescue_states":dict(c.execute("SELECT status,count(*) FROM product_historical_rescue GROUP BY status"))}
