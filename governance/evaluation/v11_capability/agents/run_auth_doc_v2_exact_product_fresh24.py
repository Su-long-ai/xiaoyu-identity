# -*- coding: utf-8 -*-
"""Exact product-route OFF/ON predictions for frozen X360/X361.

No gold/reference material is loaded. Each arm copies the same sealed persona
source runtime into an isolated temporary RC. The only product behavior delta
is answer_contract_trial False vs True.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
HOME=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_FRESH24_20261114"
CAND=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_20261114"
RC=CAND/"AUTH_DOCUMENT_INGRESS_RC_V2"
MAN=CAND/"AUTH_DOCUMENT_INGRESS_V2_MANIFEST.json"
CACHE=HOME/"source_runtime_cache"
SUITE=HOME/"FRESH24_FROZEN_NO_GOLD.json"
FREEZE=HOME/"FRESH24_FREEZE_SEAL.json"
SCOPES=json.loads((HOME/"SCOPES.json").read_text("utf-8"))

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def safe(s):return re.sub(r"[^A-Za-z0-9_.-]+","_",str(s))
def jl(p):
 p=Path(p)
 return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,o):
 with Path(p).open("a",encoding="utf-8") as f:
  f.write(json.dumps(o,ensure_ascii=False)+"\n");f.flush();os.fsync(f.fileno())
def cost(scope):
 with sqlite3.connect(A/".api_small_20261106.sqlite3",timeout=15) as db:
  return float(db.execute("""SELECT COALESCE(SUM(
      CASE WHEN status='DONE' THEN actual_cny ELSE reserved_cny END),0)
      FROM request_costs WHERE scope=?""",(scope,)).fetchone()[0] or 0)

def candidate_manifest():
 m=json.loads(MAN.read_text("utf-8"))
 if m.get("default_off") is not True or m.get("auto_release") is not False:
  raise RuntimeError("candidate_not_default_off")
 for rel,dig in m["files_sha256"].items():
  fp=RC/rel
  if not fp.is_file() or sha(fp)!=dig:
   raise RuntimeError("candidate_drift:"+rel)
 return m

def verify_global():
 candidate_manifest()
 suite=json.loads(SUITE.read_text("utf-8"))
 freeze=json.loads(FREEZE.read_text("utf-8"))
 if freeze["suite_sha256"]!=sha(SUITE):
  raise RuntimeError("suite_bytes_drift")
 if freeze["candidate_manifest_sha256"]!=sha(MAN):
  raise RuntimeError("candidate_freeze_drift")
 if suite.get("candidate_frozen_before_suite_selection") is not True:
  raise RuntimeError("candidate_not_frozen_first")
 if suite.get("gold_not_loaded") is not True or suite.get("fresh_disjoint") is not True:
  raise RuntimeError("suite_not_gold_free_disjoint")
 cache_index=CACHE/"CACHE_INDEX.json"
 if not cache_index.is_file():
  raise RuntimeError("source_cache_index_missing")
 ci=json.loads(cache_index.read_text("utf-8"))
 if ci.get("candidate_manifest_sha256")!=sha(MAN):
  raise RuntimeError("source_cache_candidate_mismatch")
 if not (ci.get("all_gold_loaded_false") and
         ci.get("all_question_loaded_false") and
         ci.get("all_model_calls_zero")):
  raise RuntimeError("source_cache_blindness_invalid")
 return suite

def cache_rc(persona):
 base=CACHE/safe(persona)
 sealp=base/"CACHE_SEAL.json";cached=base/"RC"
 if not sealp.is_file() or not cached.is_dir():
  raise RuntimeError("persona_cache_missing:"+persona)
 seal=json.loads(sealp.read_text("utf-8"))
 if seal.get("candidate_manifest_sha256")!=sha(MAN):
  raise RuntimeError("persona_cache_candidate_mismatch:"+persona)
 if seal.get("gold_loaded") is not False or seal.get("question_loaded") is not False:
  raise RuntimeError("persona_cache_not_blind:"+persona)
 for name,dig in (seal.get("runtime_sqlite_sha256") or {}).items():
  fp=cached/"runtime"/name
  if not fp.is_file() or sha(fp)!=dig:
   raise RuntimeError("persona_cache_runtime_drift:"+persona+":"+name)
 # Product code in the cache must also remain the exact frozen candidate.
 m=candidate_manifest()
 for rel,dig in m["files_sha256"].items():
  fp=cached/rel
  if not fp.is_file() or sha(fp)!=dig:
   raise RuntimeError("persona_cache_code_drift:"+persona+":"+rel)
 return cached,seal

def child(variant,persona):
 scope=SCOPES[variant+"_task"]
 if cost(scope)>=2:raise RuntimeError("scope_budget_exhausted")
 os.environ["XY_G107_VARIANT"]="G117"
 os.environ["XY_G107_SCOPE"]=scope
 suite=json.loads(SUITE.read_text("utf-8"))
 cases=[x for x in suite["cases"] if x["scope_id"]==persona]
 if not cases:return
 out=HOME/(variant.upper()+"_ANSWERS.jsonl")
 done={x["case_id"]:x for x in jl(out)}
 if all(x["case_id"] in done for x in cases):return

 cached,cache_seal=cache_rc(persona)
 tmp=Path(tempfile.mkdtemp(prefix="run_"+variant+"_"+safe(persona)+"_",dir=str(A/"results/product_integration")))
 local=tmp/"RC"
 try:
  shutil.copytree(cached,local,ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
  sys.path.insert(0,str(local))
  from unified_runtime import UnifiedTextRuntime
  from g18_chronology_gateway import ChronologyAnswerGateway
  from answer_outcome_gate import inspect_answer
  rt=UnifiedTextRuntime()
  try:
   sync=rt.sync_read_index()
   if sync.get("active_documents")!=int(cache_seal["document_count"]):
    raise RuntimeError("cached_document_count_mismatch")
   if sync["document_projection"].get("changed")!=0:
    raise RuntimeError("cached_runtime_not_idempotent")
   gw=ChronologyAnswerGateway(
      rt,evaluation_scope=scope,answer_contract_trial=(variant=="on"))
   for c in cases:
    cid=c["case_id"]
    if cid in done:continue
    result=gw.answer(c["question"],arm="R",allow_paid=True,recent_context=[])
    if result.get("status")!="ANSWERED":
     raise RuntimeError("answer_status:"+cid+":"+str(result.get("status"))+
                        ":"+str(result.get("error"))[:240])
    ans=str(result.get("final_answer") or "").strip()
    usage=dict(result.get("provider_usage") or {})
    finish=usage.get("_finish_reason")
    integ=inspect_answer(ans,finish)
    if not ans or integ["status"]=="invalid":
     raise RuntimeError("invalid_answer:"+cid+":"+str(integ.get("errors")))
    ac=(result.get("read_context") or {}).get("answer_contract_product_rc")
    row={"case_id":cid,"scope_id":persona,"category":c["category"],
      "question":c["question"],"answer":ans,"finish_reason":finish,
      "answer_integrity":integ,"variant":variant,
      "trial_enabled":variant=="on",
      "answer_origin":result.get("answer_origin"),
      "answer_contract":ac,
      "tool_executions":result.get("tool_executions") or [],
      "new_provider_requests":result.get("new_provider_requests"),
      "provider_usage":{k:v for k,v in usage.items() if k in
        ("prompt_tokens","completion_tokens","total_tokens","_finish_reason")},
      "persona_document_count":int(cache_seal["document_count"]),
      "persona_corpus_sha256":cache_seal["corpus_sha256"],
      "source_runtime_cache_seal_sha256":sha(CACHE/safe(persona)/"CACHE_SEAL.json"),
      "candidate_manifest_sha256":sha(MAN),"suite_sha256":sha(SUITE)}
    append(out,row);done[cid]=row
    print("V2",variant,len(done),"/24",cid,
          "origin",row["answer_origin"],
          "ac",bool(ac and ac.get("activated")),
          "fallback",bool(ac and ac.get("fallback")),
          "cost",round(cost(scope),6),flush=True)
  finally:
   rt.close()
 finally:
  sys.path=[x for x in sys.path if x!=str(local)]
  shutil.rmtree(tmp,ignore_errors=True)

def parent(variant):
 suite=verify_global()
 scope=SCOPES[variant+"_task"]
 if cost(scope)>=2:raise RuntimeError("scope_budget_exhausted")
 out=HOME/(variant.upper()+"_ANSWERS.jsonl")
 done={x["case_id"]:x for x in jl(out)}
 personas=[]
 for c in suite["cases"]:
  if c["case_id"] not in done and c["scope_id"] not in personas:
   personas.append(c["scope_id"])
 for persona in personas:
  cp=subprocess.run([sys.executable,str(Path(__file__).resolve()),
      "--child","--variant",variant,"--persona",persona],
      cwd=A,encoding="utf-8",errors="replace")
  if cp.returncode!=0:
   raise RuntimeError("persona_child_failed:"+persona+":"+str(cp.returncode))
 rows={x["case_id"]:x for x in jl(out)}
 if len(rows)!=24:raise RuntimeError("prediction_incomplete:"+str(len(rows)))
 seal=HOME/(variant.upper()+"_PREDICTION_SEAL.json")
 seal.write_text(json.dumps({
   "schema":"xiaoyu-auth-document-v2-exact-product-fresh24-prediction-seal-v1",
   "variant":variant,"n":24,"answers_sha256":sha(out),
   "suite_sha256":sha(SUITE),"candidate_manifest_sha256":sha(MAN),
   "source_cache_index_sha256":sha(CACHE/"CACHE_INDEX.json"),
   "gold_loaded":False,"same_product_manifest":True,
   "same_source_cache_family":True,
   "trial_enabled":variant=="on","cost_proxy_cny":round(cost(scope),6),
   "all_output_integrity_noninvalid":all(
      x["answer_integrity"]["status"]!="invalid" for x in rows.values()),
   "all_used_canonical_document_ingress":all(
      int(x.get("persona_document_count") or 0)>0 for x in rows.values()),
   "answer_contract_activated_n":sum(
      bool((x.get("answer_contract") or {}).get("activated")) for x in rows.values()),
   "answer_contract_fallback_n":sum(
      bool((x.get("answer_contract") or {}).get("fallback")) for x in rows.values()),
 },ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("UPDATE tasks SET status='DONE',artifact=?,updated_at=? WHERE id=?",
             (str(seal),time.time(),scope));db.commit()
 print("SEALED",variant,sha(seal),"cost",round(cost(scope),6),flush=True)

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--variant",choices=("off","on"),required=True)
 ap.add_argument("--child",action="store_true");ap.add_argument("--persona")
 x=ap.parse_args()
 if x.child:
  if not x.persona:raise RuntimeError("persona_required")
  child(x.variant,x.persona)
 else:parent(x.variant)
if __name__=="__main__":main()
