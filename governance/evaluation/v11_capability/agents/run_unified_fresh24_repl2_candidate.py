# -*- coding: utf-8 -*-
from pathlib import Path
from collections import defaultdict
import collections,hashlib,json,os,re,sqlite3,sys,time
import numpy as np

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_UNIFIED_FRESH24_REPL2_20261114"
RROOT=ROOT/"external/benchmarks/rhelm"
G155=A/"results/product_integration/LEAD_G155_QUERY_CENTERED_EVIDENCE_20261114"
HY=ROOT/"governance/lead_prechecks"
sys.path[:0]=[str(G155),str(HY),str(ROOT),str(A)]

from prepare_g155 import query_view
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_contract_mvp import (
 planner_messages,validate_contract,executor_messages,validate_execution,
 repair_messages,render_execution,
)
from governance.evaluation.v11_capability.agents.evidence_gap_analyzer import (
 gap_messages,validate_gap_plan,repair_gap_plan,
)
from governance.evaluation.v11_capability.agents.answer_outcome_gate import inspect_answer
from hybrid_bge_rrf_retriever_candidate import LocalBGE,embed_documents,embed_question,hybrid_rank
import contract_metadata_gap_retriever_candidate as cm

TASK="M2-X345";MAX_SUPPLEMENT_CHARS=12000
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p);return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n");f.flush();os.fsync(f.fileno())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def decode(s):
 t=str(s).strip();ticks=chr(96)*3
 if t.startswith(ticks):t=t.replace(ticks+"json","").replace(ticks+"JSON","").replace(ticks,"").strip()
 i=t.find("{");j=t.rfind("}")
 if i<0 or j<i:raise ValueError("json_object_missing")
 return json.loads(t[i:j+1])
def cfg_qwen():
 c=dict(PROVIDERS["qwen"]);c.update({"provider":"qwen","model":"qwen3.8-flash","temperature":0,
   "enable_thinking":False,"response_format":{"type":"json_object"},"_capture_finish_reason":True});return c
def cfg_ds():
 c=dict(PROVIDERS["deepseek"]);c.update({"provider":"deepseek","model":"deepseek-flash","temperature":0,
   "reasoning_effort":"none","response_format":{"type":"json_object"},"_capture_finish_reason":True});return c

def pool_docs(persona):
 out=[]
 for p in sorted((RROOT/"conversations"/persona).glob("*.json")):
  o=json.loads(p.read_text("utf-8"));date=str(o.get("date") or "")
  for t in o.get("conversation") or []:
   sid=f"{date}:{int(t['turn'])}"
   out.append({"id":sid,"speaker":"","text":f"User: {t.get('user','')}\nAssistant: {t.get('assistant','')}"})
 by=collections.defaultdict(list)
 for p in sorted((RROOT/"emails"/persona).glob("*.txt")):
  m=re.search(r"(\d{4})_(\d{2})_(\d{2})",p.name)
  if m:by["-".join(m.groups())].append(p)
 for d,ps in sorted(by.items()):
  out.append({"id":f"Emails_{d}","speaker":"",
    "text":"\n\n".join(f"### {p.name}\n"+p.read_text("utf-8",errors="replace") for p in ps)})
 for p in sorted((RROOT/"attachments"/persona).glob("*")):
  if p.is_file():out.append({"id":p.name,"speaker":"","text":p.read_text("utf-8",errors="replace")})
 if len({x["id"] for x in out})!=len(out):raise RuntimeError("duplicate docs "+persona)
 return out

def docs_fp(docs):
 raw=json.dumps([{"id":d["id"],"text":d["text"]} for d in docs],ensure_ascii=False,
                sort_keys=True,separators=(",",":")).encode()
 return hashlib.sha256(raw).hexdigest()
def safe(s):return re.sub(r"[^A-Za-z0-9_.-]+","_",s)
def embeddings(model,persona,docs):
 cache=P/"bge_cache";cache.mkdir(exist_ok=True)
 fp=docs_fp(docs);mp=cache/(safe(persona)+".json");npyp=cache/(safe(persona)+".npy")
 if mp.exists() and npyp.exists():
  meta=load(mp)
  if meta.get("docs_sha")==fp:
   arr=np.load(npyp,mmap_mode="r")
   if arr.shape==(len(docs),384):
    print("BGE_CACHE",persona,len(docs),flush=True);return arr
 print("BGE_BUILD",persona,len(docs),flush=True)
 arr=embed_documents(model,docs).astype(np.float32,copy=False)
 with npyp.open("wb") as f:np.save(f,arr,allow_pickle=False)
 mp.write_text(json.dumps({"docs_sha":fp,"n":len(docs),"shape":list(arr.shape)},indent=2)+"\n","utf-8")
 return arr

def supplement(question,contract,gap,persona,current_keys,model,doc_cache,emb_cache):
 if gap.get("stop"):return [],[],[]
 if persona not in doc_cache:
  doc_cache[persona]=pool_docs(persona)
  emb_cache[persona]=embeddings(model,persona,doc_cache[persona])
 docs=doc_cache[persona];emb=np.asarray(emb_cache[persona]);by={d["id"]:d for d in docs}
 enriched=cm.enrich_documents(docs);ix=cm.filtered_indices(enriched,question)
 fd=[enriched[i] for i in ix];fe=emb[ix]
 selected=set(map(str,current_keys));extras=[];anchors=[];trace=[]
 for qrow in gap.get("search_queries") or []:
  q=str(qrow["query"]);ranked=hybrid_rank(fd,fe,embed_question(model,q),q,())
  hits=[]
  for sid in ranked:
   if sid in selected:continue
   hits.append(sid)
   if len(hits)>=2:break
  trace.append({"query":q,"node_ids":qrow.get("node_ids") or [],
                "pool_n":len(fd),"new_candidates":hits})
  for sid in hits:
   if sid in selected:continue
   selected.add(sid);extras.append(sid);anchors.append(sid)
   if len(extras)>=3:break
  if len(extras)>=3:break
 adj=[]
 if cm.needs_adjacency(contract):
  for sid in anchors:
   for aid in cm.adjacent_ids(docs,sid,radius=2):
    if aid not in selected:
     selected.add(aid);adj.append(aid)
    if len(adj)>=6:break
   if len(adj)>=6:break
 ids=extras+adj
 # Package with the already-frozen G155 query-centered raw view. No summaries.
 chunks=[];spent=0
 for sid in ids:
  raw=str(by[sid]["text"])
  view,_=query_view(question,raw,min(len(raw),5200))
  add=len(view)+len(sid)+36
  if chunks and spent+add>MAX_SUPPLEMENT_CHARS:continue
  chunks.append((sid,view));spent+=add
 return chunks,trace,{"ranked":extras,"adjacent":adj,
   "time_constraint":cm.explicit_time_constraint(question),
   "attachment_intent":cm.attachment_intent(question),"supplement_chars":spent}

def main():
 suitep=P/"FRESH24_FROZEN_NO_GOLD.json";suite=load(suitep);seal=load(P/"FRESH24_FREEZE_SEAL.json")
 freeze=load(P/"CANDIDATE_FREEZE.json")
 if seal["suite_sha256"]!=sha(suitep) or seal["candidate_freeze_sha256"]!=sha(P/"CANDIDATE_FREEZE.json"):
  raise RuntimeError("fresh freeze mismatch")
 # Verify all frozen component bytes before first prediction.
 for v in freeze["components"].values():
  if sha(v["path"])!=v["sha256"]:raise RuntimeError("candidate component drift: "+v["path"])
 base_seal=load(P/"BASELINE_PREDICTION_SEAL.json")
 if base_seal["suite_sha256"]!=sha(suitep) or base_seal.get("gold_loaded") is not False:
  raise RuntimeError("baseline seal missing/invalid")
 baseline={x["case_id"]:x for x in jl(P/"BASELINE_ANSWERS.jsonl")}
 if len(baseline)!=24:raise RuntimeError("baseline incomplete")

 out=P/"CANDIDATE_ANSWERS.jsonl";done={x["case_id"]:x for x in jl(out)}
 contracts=P/"CONTRACTS.jsonl";cdone={x["case_id"]:x for x in jl(contracts)}
 gaps=P/"GAP_PLANS.jsonl";gdone={x["case_id"]:x for x in jl(gaps)}
 bge=LocalBGE();doc_cache={};emb_cache={}
 for c in suite["cases"]:
  cid=c["case_id"]
  if cid in done:continue
  q=c["question"];initial=c["initial_evidence_text"];fallback=None
  contract=None;gap=None;raw_exec=None;checked=None;repair=False;sup=[];trace=[];rmeta={}
  planner_finish=gap_finish=exec_finish=None
  try:
   if cid in cdone:
    contract=validate_contract(q,cdone[cid]["raw_contract"]);planner_finish=cdone[cid].get("finish_reason")
   else:
    wire,u=cached_chat(cfg_qwen(),planner_messages(q),max_tokens=650,timeout=100,
      namespace="unified-fresh24-contract-v1",budget_scope=TASK,cache_only=False)
    planner_finish=u.get("_finish_reason");raw=decode(wire);contract=validate_contract(q,raw)
    rec={"case_id":cid,"raw_contract":raw,"contract":contract,"finish_reason":planner_finish}
    append(contracts,rec);cdone[cid]=rec
  except Exception as e:fallback="contract:"+type(e).__name__+":"+str(e)[:180]

  if fallback is None:
   try:
    if cid in gdone:
     gap=validate_gap_plan(contract,gdone[cid]["raw_gap"])
     gap_finish=gdone[cid].get("finish_reason")
    else:
     wire,u=cached_chat(cfg_qwen(),gap_messages(q,contract,initial),max_tokens=650,timeout=100,
       namespace="unified-fresh24-gap-v1",budget_scope=TASK,cache_only=False)
     gap_finish=u.get("_finish_reason");rawg=decode(wire)
     try:gap=validate_gap_plan(contract,rawg)
     except Exception:gap=validate_gap_plan(contract,repair_gap_plan(q,contract,rawg))
     rec={"case_id":cid,"raw_gap":rawg,"gap":gap,"finish_reason":gap_finish}
     append(gaps,rec);gdone[cid]=rec
   except Exception as e:fallback="gap:"+type(e).__name__+":"+str(e)[:180]

  combined=initial
  if fallback is None:
   try:
    sup,trace,rmeta=supplement(q,contract,gap,c["scope_id"],c["initial_source_keys"],bge,doc_cache,emb_cache)
    if sup:
     combined=initial+"\n\nSUPPLEMENTAL AUTHORIZED EVIDENCE:\n"+"\n\n".join("[SOURCE "+sid+"]\n"+txt for sid,txt in sup)
   except Exception as e:fallback="retrieval:"+type(e).__name__+":"+str(e)[:180]

  answer=baseline[cid]["answer"];finish=baseline[cid].get("finish_reason")
  if fallback is None:
   try:
    wire,u=cached_chat(cfg_ds(),executor_messages(q,combined,contract),max_tokens=1000,timeout=120,
      namespace="unified-fresh24-executor-v1",budget_scope=TASK,cache_only=False)
    exec_finish=u.get("_finish_reason");raw_exec=decode(wire);checked=validate_execution(contract,raw_exec)
    if not checked["valid"]:
     repair=True
     wire,u=cached_chat(cfg_ds(),repair_messages(q,combined,contract,raw_exec,checked["errors"]),
       max_tokens=1000,timeout=120,namespace="unified-fresh24-repair-v1",
       budget_scope=TASK,cache_only=False)
     exec_finish=u.get("_finish_reason");raw_exec=decode(wire);checked=validate_execution(contract,raw_exec)
    if not checked["valid"]:fallback="execution:"+";".join(checked["errors"])[:280]
    else:
     answer=render_execution(contract,checked);finish=exec_finish
     if not answer.strip():fallback="render_empty"
   except Exception as e:fallback="executor:"+type(e).__name__+":"+str(e)[:180]
  if fallback:
   answer=baseline[cid]["answer"];finish=baseline[cid].get("finish_reason")

  item={"case_id":cid,"answer":answer,"finish_reason":finish,"integrity":inspect_answer(answer,finish),
   "fallback_to_baseline":bool(fallback),"fallback_reason":fallback,
   "planner_finish_reason":planner_finish,"gap_finish_reason":gap_finish,"executor_finish_reason":exec_finish,
   "repair_used":repair,"contract":contract,"gap_plan":gap,
   "supplemental_source_keys":[sid for sid,_ in sup],"retrieval_trace":trace,"retrieval_meta":rmeta,
   "initial_evidence_sha256":hashlib.sha256(initial.encode()).hexdigest(),
   "combined_evidence_sha256":hashlib.sha256(combined.encode()).hexdigest(),
   "baseline_answer_sha256":hashlib.sha256(baseline[cid]["answer"].encode()).hexdigest(),
   "raw_execution":raw_exec,"checked_execution":checked}
  append(out,item);done[cid]=item
  print("CAND",len(done),"/24",cid,"sup",len(sup),"fallback",bool(fallback),"repair",repair,flush=True)

 if len(done)!=24:raise RuntimeError("candidate incomplete")
 pred=P/"CANDIDATE_PREDICTION_SEAL.json"
 pred.write_text(json.dumps({"schema":"xiaoyu-unified-fresh24-candidate-seal-v1","n":24,
  "suite_sha256":sha(suitep),"candidate_freeze_sha256":sha(P/"CANDIDATE_FREEZE.json"),
  "answers_sha256":sha(out),"contracts_sha256":sha(contracts),"gap_plans_sha256":sha(gaps),
  "baseline_answers_sha256":sha(P/"BASELINE_ANSWERS.jsonl"),"gold_loaded":False,
  "fallback_count":sum(bool(x.get("fallback_to_baseline")) for x in done.values()),
  "repair_count":sum(bool(x.get("repair_used")) for x in done.values()),
  "supplement_trigger_count":sum(bool(x.get("supplemental_source_keys")) for x in done.values()),
  "all_integrity_valid":all(x["integrity"]["status"]=="valid" for x in done.values())},
  ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3") as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",(str(pred),time.time(),TASK))
  db.execute("update tasks set status='ACTIVE',updated_at=? where id='M2-X341'",(time.time(),));db.commit()
 print("SEALED",sha(pred),flush=True)
if __name__=="__main__":main()
