# -*- coding: utf-8 -*-
"""Exact product-route fresh24 OFF/ON runner for frozen answer-contract RC.

Gold/reference answers are never loaded. Each persona runs in an isolated child
process and fresh temporary product RC. The full public RHELM persona history is
ingested through XiaoYu's canonical native runtime. OFF/ON differ only by the
trusted answer_contract_trial constructor flag on the same frozen manifest.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, os, re, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
HOME=A/"results/product_integration/LEAD_ANSWER_CONTRACT_PRODUCT_FRESH24_20261114"
PRC=A/"results/product_integration/LEAD_ANSWER_CONTRACT_PRODUCT_RC_20261114"
RC=PRC/"ANSWER_CONTRACT_DEFAULT_OFF_RC"
MAN=PRC/"ANSWER_CONTRACT_DEFAULT_OFF_MANIFEST.json"
RROOT=ROOT/"external/benchmarks/rhelm"
SCOPE=json.loads((HOME/"SCOPES.json").read_text("utf-8"))
SUITE=HOME/"FRESH24_FROZEN_NO_GOLD.json"
FREEZE=HOME/"FRESH24_FREEZE_SEAL.json"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jl(p):
 p=Path(p)
 return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,o):
 with Path(p).open("a",encoding="utf-8") as f:
  f.write(json.dumps(o,ensure_ascii=False)+"\n");f.flush();os.fsync(f.fileno())
def cost(scope):
 with sqlite3.connect(A/".api_small_20261106.sqlite3",timeout=15) as db:
  return float(db.execute("""select coalesce(sum(case when status='DONE' then actual_cny else reserved_cny end),0)
    from request_costs where scope=?""",(scope,)).fetchone()[0] or 0)

def _ts(date, fallback="2024-01-01T12:00:00+00:00"):
 s=str(date or "").strip()
 if not s:return fallback
 if "T" in s:return s
 if re.fullmatch(r"\d{4}-\d{2}-\d{2}",s):return s+"T12:00:00+00:00"
 return fallback

def _chunks(text,limit=1100):
 text=str(text or "")
 if len(text)<=limit:return [text]
 parts=[];rest=text
 while rest:
  if len(rest)<=limit:
   parts.append(rest);break
  cut=rest.rfind("\n",0,limit+1)
  if cut<limit//2:cut=rest.rfind(" ",0,limit+1)
  if cut<limit//2:cut=limit
  parts.append(rest[:cut].rstrip());rest=rest[cut:].lstrip()
 return [x for x in parts if x]

def persona_turns(persona):
 raw=[]
 # Match external source granularity first, then respect XiaoYu's product
 # memory-ingress limit by losslessly chunking long public sources.
 for fp in sorted((RROOT/"conversations"/persona).glob("*.json")):
  o=json.loads(fp.read_text("utf-8"));date=str(o.get("date") or "")
  for t in o.get("conversation") or []:
   sid=f"{date}:{int(t['turn'])}"
   text=f"[SOURCE {sid}]\nUser: {t.get('user','')}\nAssistant: {t.get('assistant','')}"
   raw.append((sid,_ts(t.get("timestamp") or date),text))
 by=collections.defaultdict(list)
 for fp in sorted((RROOT/"emails"/persona).glob("*.txt")):
  m=re.search(r"(\d{4})_(\d{2})_(\d{2})",fp.name)
  if m:by["-".join(m.groups())].append(fp)
 for d,ps in sorted(by.items()):
  sid=f"Emails_{d}"
  text="[SOURCE "+sid+"]\n"+"\n\n".join(
    f"### {fp.name}\n"+fp.read_text("utf-8",errors="replace") for fp in ps)
  raw.append((sid,_ts(d),text))
 for fp in sorted((RROOT/"attachments"/persona).glob("*")):
  if fp.is_file():
   sid=fp.name
   text=f"[SOURCE {sid}]\n"+fp.read_text("utf-8",errors="replace")
   raw.append((sid,"2024-01-01T12:00:00+00:00",text))
 if len({x[0] for x in raw})!=len(raw):raise RuntimeError("duplicate_source_ids:"+persona)
 out=[]
 for sid,ts,text in raw:
  pieces=_chunks(text,1100)
  for j,ch in enumerate(pieces,1):
   tag=sid if len(pieces)==1 else f"{sid} part {j}/{len(pieces)}"
   payload=ch if len(pieces)==1 else f"[SOURCE {sid} part {j}/{len(pieces)}]\n"+ch
   out.append((tag,ts,payload))
 return out

def child(variant,persona):
 scope=SCOPE[variant+"_task"]
 if cost(scope)>2:raise RuntimeError("scope_budget_exhausted")
 os.environ["XY_G107_VARIANT"]="G117"
 os.environ["XY_G107_SCOPE"]=scope
 # Import only after the registered scope is in the environment.
 sys.path.insert(0,str(A/"results/product_integration/LEAD_G107_TIMLMEM_EXTERNAL_20261113"))
 from xiaoyu_timl_native_adapter import NativeAdapter
 import xiaoyu_timl_native_adapter as src
 src.RC=RC

 suite=json.loads(SUITE.read_text("utf-8"))
 cases=[x for x in suite["cases"] if x["scope_id"]==persona]
 if not cases:return
 out=HOME/(variant.upper()+"_ANSWERS.jsonl")
 done={x["case_id"]:x for x in jl(out)}
 if all(x["case_id"] in done for x in cases):return

 turns=persona_turns(persona)
 session={"session_id":"rhelm-"+persona,
          "started_at":"2024-01-01T00:00:00+00:00","turns":[]}
 for i,(sid,ts,text) in enumerate(turns,1):
  session["turns"].append({"turn_id":f"src-{i:05d}","speaker_role":"user",
    "speaker_id":"owner","timestamp":ts,"text":text})

 adapter=NativeAdapter()
 try:
  adapter.handle({"request_type":"reset"})
  got=adapter.handle({"request_type":"ingest_session","session":session})
  if not got.get("ok"):raise RuntimeError("ingest_failed")
  adapter.rt.sync_read_index()
  # Replace only the gateway flag, preserving exact product runtime/source tool.
  from g18_chronology_gateway import ChronologyAnswerGateway
  adapter.gw=ChronologyAnswerGateway(
    adapter.rt,evaluation_scope=scope,answer_contract_trial=(variant=="on"))
  for c in cases:
   cid=c["case_id"]
   if cid in done:continue
   result=adapter.gw.answer(c["question"],arm="R",allow_paid=True,recent_context=[])
   if result.get("status")!="ANSWERED":
    raise RuntimeError("answer_status:"+cid+":"+str(result.get("status"))+":"+str(result.get("error"))[:200])
   ans=str(result.get("final_answer") or "").strip()
   if not ans:raise RuntimeError("empty_answer:"+cid)
   usage=dict(result.get("provider_usage") or {})
   finish=usage.get("_finish_reason")
   sys.path.insert(0,str(A))
   from answer_outcome_gate import inspect_answer
   integ=inspect_answer(ans,finish)
   if integ["status"]=="invalid":raise RuntimeError("invalid_output:"+cid+":"+str(integ["errors"]))
   ac=(result.get("read_context") or {}).get("answer_contract_product_rc")
   row={"case_id":cid,"scope_id":persona,"category":c["category"],"question":c["question"],
     "answer":ans,"finish_reason":finish,"answer_integrity":integ,
     "variant":variant,"trial_enabled":variant=="on",
     "answer_origin":result.get("answer_origin"),
     "answer_contract":ac,"tool_executions":result.get("tool_executions") or [],
     "new_provider_requests":result.get("new_provider_requests"),
     "provider_usage":{k:v for k,v in usage.items()
       if k in ("prompt_tokens","completion_tokens","total_tokens","_finish_reason")},
     "persona_source_count":len(turns),"manifest_sha256":sha(MAN),
     "suite_sha256":sha(SUITE)}
   append(out,row);done[cid]=row
   print("PRODUCT",variant,persona,len(done),"/24",cid,
         "origin",row["answer_origin"],"ac",bool(ac and ac.get("activated")),
         "fallback",bool(ac and ac.get("fallback")),"cost",round(cost(scope),6),flush=True)
 finally:
  adapter.cleanup()

def parent(variant):
 manifest=json.loads(MAN.read_text("utf-8"));freeze=json.loads(FREEZE.read_text("utf-8"))
 suite=json.loads(SUITE.read_text("utf-8"));scope=SCOPE[variant+"_task"]
 if manifest.get("default_off") is not True or manifest.get("auto_release") is not False:
  raise RuntimeError("manifest_not_default_off")
 if freeze["manifest_sha256"]!=sha(MAN) or freeze["suite_sha256"]!=sha(SUITE):
  raise RuntimeError("freeze_binding_invalid")
 if suite.get("gold_not_loaded") is not True or suite.get("fresh_disjoint") is not True:
  raise RuntimeError("fresh_suite_invalid")
 for rel,dig in manifest["files_sha256"].items():
  if sha(RC/rel)!=dig:raise RuntimeError("manifest_member_drift:"+rel)
 if cost(scope)>2:raise RuntimeError("scope_budget_exhausted")
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
  "schema":"xiaoyu-answer-contract-exact-product-fresh24-prediction-seal-v1",
  "variant":variant,"n":24,"answers_sha256":sha(out),
  "suite_sha256":sha(SUITE),"manifest_sha256":sha(MAN),
  "gold_loaded":False,"same_product_manifest":True,
  "trial_enabled":variant=="on","cost_proxy_cny":round(cost(scope),6),
  "all_output_integrity_noninvalid":all(x["answer_integrity"]["status"]!="invalid" for x in rows.values()),
  "answer_contract_activated_n":sum(bool((x.get("answer_contract") or {}).get("activated")) for x in rows.values()),
  "answer_contract_fallback_n":sum(bool((x.get("answer_contract") or {}).get("fallback")) for x in rows.values())
 },ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
             (str(seal),time.time(),scope));db.commit()
 print("SEALED",variant,sha(seal),"cost",cost(scope),flush=True)

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--variant",choices=("off","on"),required=True)
 ap.add_argument("--child",action="store_true");ap.add_argument("--persona")
 a=ap.parse_args()
 if a.child:
  if not a.persona:raise RuntimeError("persona_required")
  child(a.variant,a.persona)
 else:parent(a.variant)

if __name__=="__main__":main()
