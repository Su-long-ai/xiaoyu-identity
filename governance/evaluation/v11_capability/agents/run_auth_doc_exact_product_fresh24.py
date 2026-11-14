# -*- coding: utf-8 -*-
"""Frozen X355 exact-product fresh24 runner. Gold/reference never loaded."""
from __future__ import annotations
import argparse,collections,hashlib,json,os,re,shutil,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
HOME=A/"results/product_integration/LEAD_AUTH_DOCUMENT_ANSWER_CONTRACT_FRESH24_20261114"
CACHE=HOME/"source_runtime_cache"
CAND=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_20261114"
RC=CAND/"AUTH_DOCUMENT_INGRESS_RC"
MAN=CAND/"AUTH_DOCUMENT_INGRESS_MANIFEST.json"
RROOT=ROOT/"external/benchmarks/rhelm"
SUITE=HOME/"FRESH24_FROZEN_NO_GOLD.json"
FREEZE=HOME/"FRESH24_FREEZE_SEAL.json"
SCOPE=json.loads((HOME/"SCOPES.json").read_text("utf-8"))

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jl(p):
 p=Path(p);return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,o):
 with Path(p).open("a",encoding="utf-8") as f:
  f.write(json.dumps(o,ensure_ascii=False)+"\n");f.flush();os.fsync(f.fileno())
def cost(scope):
 with sqlite3.connect(A/".api_small_20261106.sqlite3",timeout=15) as db:
  return float(db.execute("""select coalesce(sum(case when status='DONE' then actual_cny else reserved_cny end),0)
    from request_costs where scope=?""",(scope,)).fetchone()[0] or 0)

def _date(s):
 x=str(s or "").strip()
 if re.match(r"^\d{4}-\d{2}-\d{2}",x):return x[:10]
 return ""

def persona_documents(persona):
 docs=[]
 for fp in sorted((RROOT/"conversations"/persona).glob("*.json")):
  o=json.loads(fp.read_text("utf-8"));date=str(o.get("date") or "")
  for t in o.get("conversation") or []:
   sid=f"{date}:{int(t['turn'])}"
   ts=str(t.get("timestamp") or date)
   docs.append({"source_key":sid,
      "text":f"[SOURCE {sid}]\nUser: {t.get('user','')}\nAssistant: {t.get('assistant','')}",
      "known_at":ts,"valid_at":ts,
      "lineage_key":f"rhelm:{persona}:conversation:{date}"})
 by=collections.defaultdict(list)
 for fp in sorted((RROOT/"emails"/persona).glob("*.txt")):
  m=re.search(r"(\d{4})_(\d{2})_(\d{2})",fp.name)
  if m:by["-".join(m.groups())].append(fp)
 for d,ps in sorted(by.items()):
  sid=f"Emails_{d}"
  docs.append({"source_key":sid,
    "text":"[SOURCE "+sid+"]\n"+"\n\n".join(
       f"### {fp.name}\n"+fp.read_text("utf-8",errors="replace") for fp in ps),
    "known_at":d,"valid_at":d,"lineage_key":f"rhelm:{persona}:email:{d}"})
 for fp in sorted((RROOT/"attachments"/persona).glob("*")):
  if fp.is_file():
   sid=fp.name
   docs.append({"source_key":sid,
     "text":f"[SOURCE {sid}]\n"+fp.read_text("utf-8",errors="replace"),
     "known_at":"","valid_at":None,"lineage_key":None})
 if len({x["source_key"] for x in docs})!=len(docs):
  raise RuntimeError("duplicate_source_key:"+persona)
 return docs

def verify_manifest():
 m=json.loads(MAN.read_text("utf-8"))
 if m.get("default_off") is not True or m.get("auto_release") is not False:
  raise RuntimeError("candidate_not_default_off")
 for rel,dig in m["files_sha256"].items():
  if sha(RC/rel)!=dig:raise RuntimeError("candidate_drift:"+rel)
 freeze=json.loads(FREEZE.read_text("utf-8"));suite=json.loads(SUITE.read_text("utf-8"))
 if freeze["candidate_manifest_sha256"]!=sha(MAN) or freeze["suite_sha256"]!=sha(SUITE):
  raise RuntimeError("fresh_freeze_binding_invalid")
 if suite.get("candidate_rc_frozen_before_suite_selection") is not True:
  raise RuntimeError("candidate_not_frozen_before_selection")
 if suite.get("gold_not_loaded") is not True or suite.get("fresh_disjoint") is not True:
  raise RuntimeError("suite_not_fresh_gold_free")

def _safe(s):
 return re.sub(r"[^A-Za-z0-9_.-]+","_",str(s))

def _cache_for(persona):
 base=CACHE/_safe(persona)
 sealp=base/"CACHE_SEAL.json";local=base/"RC"
 if not sealp.exists() or not local.is_dir():
  raise RuntimeError("persona_runtime_cache_missing:"+persona)
 seal=json.loads(sealp.read_text("utf-8"))
 if seal.get("candidate_manifest_sha256")!=sha(MAN):
  raise RuntimeError("persona_cache_candidate_mismatch:"+persona)
 if seal.get("gold_loaded") is not False or seal.get("question_loaded") is not False:
  raise RuntimeError("persona_cache_not_gold_question_free:"+persona)
 for name,dig in (seal.get("runtime_sqlite_sha256") or {}).items():
  fp=local/"runtime"/name
  if not fp.is_file() or sha(fp)!=dig:
   raise RuntimeError("persona_cache_runtime_drift:"+persona+":"+name)
 return local,seal

def child(variant,persona):
 scope=SCOPE[variant+"_task"]
 if cost(scope)>=2:raise RuntimeError("scope_budget_exhausted")
 os.environ["XY_G107_VARIANT"]="G117";os.environ["XY_G107_SCOPE"]=scope
 suite=json.loads(SUITE.read_text("utf-8"))
 cases=[x for x in suite["cases"] if x["scope_id"]==persona]
 if not cases:return
 out=HOME/(variant.upper()+"_ANSWERS.jsonl")
 done={x["case_id"]:x for x in jl(out)}
 if all(c["case_id"] in done for c in cases):return

 local,cache_seal=_cache_for(persona)
 sys.path.insert(0,str(local))
 try:
  from unified_runtime import UnifiedTextRuntime
  from g18_chronology_gateway import ChronologyAnswerGateway
  from answer_outcome_gate import inspect_answer
  rt=UnifiedTextRuntime()
  try:
   stats=rt.sync_read_index()
   if stats.get("active_documents")!=int(cache_seal["document_count"]):
    raise RuntimeError("cached_document_projection_count_mismatch")
   gw=ChronologyAnswerGateway(
      rt,evaluation_scope=scope,answer_contract_trial=(variant=="on"))
   for c in cases:
    cid=c["case_id"]
    if cid in done:continue
    result=gw.answer(c["question"],arm="R",allow_paid=True,recent_context=[])
    if result.get("status")!="ANSWERED":
     raise RuntimeError("answer_status:"+cid+":"+str(result.get("status"))+":"+str(result.get("error"))[:200])
    ans=str(result.get("final_answer") or "").strip()
    usage=dict(result.get("provider_usage") or {})
    finish=usage.get("_finish_reason")
    integ=inspect_answer(ans,finish)
    if integ["status"]=="invalid":
     raise RuntimeError("invalid_output:"+cid+":"+str(integ["errors"]))
    ac=(result.get("read_context") or {}).get("answer_contract_product_rc")
    row={"case_id":cid,"scope_id":persona,"category":c["category"],
      "question":c["question"],"answer":ans,"finish_reason":finish,
      "answer_integrity":integ,"variant":variant,"trial_enabled":variant=="on",
      "answer_origin":result.get("answer_origin"),
      "answer_contract":ac,"tool_executions":result.get("tool_executions") or [],
      "new_provider_requests":result.get("new_provider_requests"),
      "provider_usage":{k:v for k,v in usage.items() if k in
        ("prompt_tokens","completion_tokens","total_tokens","_finish_reason")},
      "persona_document_count":int(cache_seal["document_count"]),
      "persona_corpus_sha256":cache_seal["corpus_sha256"],
      "candidate_manifest_sha256":sha(MAN),"suite_sha256":sha(SUITE)}
    append(out,row);done[cid]=row
    print("AUTHDOC",variant,persona,len(done),"/24",cid,
          "origin",row["answer_origin"],
          "ac",bool(ac and ac.get("activated")),
          "fallback",bool(ac and ac.get("fallback")),
          "cost",round(cost(scope),6),flush=True)
  finally:
   rt.close()
 finally:
  sys.path=[x for x in sys.path if x!=str(local)]

def parent(variant):
 verify_manifest()
 scope=SCOPE[variant+"_task"]
 if cost(scope)>=2:raise RuntimeError("scope_budget_exhausted")
 suite=json.loads(SUITE.read_text("utf-8"))
 out=HOME/(variant.upper()+"_ANSWERS.jsonl")
 done={x["case_id"]:x for x in jl(out)}
 personas=[]
 for c in suite["cases"]:
  if c["case_id"] not in done and c["scope_id"] not in personas:personas.append(c["scope_id"])
 for persona in personas:
  cp=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--child",
      "--variant",variant,"--persona",persona],
      cwd=A,encoding="utf-8",errors="replace")
  if cp.returncode!=0:raise RuntimeError("persona_child_failed:"+persona+":"+str(cp.returncode))
 rows={x["case_id"]:x for x in jl(out)}
 if len(rows)!=24:raise RuntimeError("prediction_incomplete:"+str(len(rows)))
 seal=HOME/(variant.upper()+"_PREDICTION_SEAL.json")
 seal.write_text(json.dumps({
  "schema":"xiaoyu-auth-doc-exact-product-fresh24-prediction-seal-v1",
  "variant":variant,"n":24,"answers_sha256":sha(out),
  "suite_sha256":sha(SUITE),"candidate_manifest_sha256":sha(MAN),
  "gold_loaded":False,"same_product_manifest":True,
  "trial_enabled":variant=="on","cost_proxy_cny":round(cost(scope),6),
  "all_output_integrity_noninvalid":all(x["answer_integrity"]["status"]!="invalid" for x in rows.values()),
  "answer_contract_activated_n":sum(bool((x.get("answer_contract") or {}).get("activated")) for x in rows.values()),
  "answer_contract_fallback_n":sum(bool((x.get("answer_contract") or {}).get("fallback")) for x in rows.values()),
  "all_used_canonical_document_ingress":all(int(x.get("persona_document_count") or 0)>0 for x in rows.values())
 },ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
    (str(seal),time.time(),scope));db.commit()
 print("SEALED",variant,sha(seal),"cost",round(cost(scope),6),flush=True)

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--variant",choices=("off","on"),required=True)
 ap.add_argument("--child",action="store_true");ap.add_argument("--persona")
 x=ap.parse_args()
 if x.child:
  if not x.persona:raise RuntimeError("persona_required")
  child(x.variant,x.persona)
 else:parent(x.variant)

if __name__=="__main__":main()
