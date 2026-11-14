# -*- coding: utf-8 -*-
from pathlib import Path
import hashlib,json,sqlite3,sys,time
ROOT=Path(r"D:\dsh-fish");A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_UNIFIED_FRESH24_20261114"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_outcome_gate import inspect_answer
TASK="M2-X339"
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p);return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def main():
 suitep=P/"FRESH24_FROZEN_NO_GOLD.json";suite=load(suitep);seal=load(P/"FRESH24_FREEZE_SEAL.json")
 if seal["suite_sha256"]!=sha(suitep) or not seal["gold_not_loaded"]:raise RuntimeError("suite seal invalid")
 cfg=dict(PROVIDERS["deepseek"]);cfg.update({"provider":"deepseek","model":"deepseek-flash",
   "temperature":0,"reasoning_effort":"none","_capture_finish_reason":True})
 out=P/"BASELINE_ANSWERS.jsonl";done={x["case_id"]:x for x in jl(out)}
 for c in suite["cases"]:
  cid=c["case_id"]
  if cid in done:continue
  ans,usage=cached_chat(cfg,c["baseline_messages"],max_tokens=900,timeout=120,
    namespace="answer-contract-unified-fresh24-baseline-v1",budget_scope=TASK,cache_only=False)
  finish=usage.get("_finish_reason");ans=str(ans).strip()
  item={"case_id":cid,"answer":ans,"finish_reason":finish,"integrity":inspect_answer(ans,finish),
    "model_input_sha256":hashlib.sha256(json.dumps(c["baseline_messages"],ensure_ascii=False,
      sort_keys=True,separators=(",",":")).encode()).hexdigest(),
    "api_cache_hit":bool(usage.get("_api_cache_hit"))}
  append(out,item);done[cid]=item
  print("BASE",len(done),"/24",cid,finish,"cache",item["api_cache_hit"],flush=True)
 if len(done)!=24:raise RuntimeError("baseline incomplete")
 pred=P/"BASELINE_PREDICTION_SEAL.json"
 pred.write_text(json.dumps({"schema":"xiaoyu-unified-fresh24-baseline-seal-v1","n":24,
  "suite_sha256":sha(suitep),"answers_sha256":sha(out),"gold_loaded":False,
  "model":"deepseek-flash","reasoning_effort":"none",
  "all_integrity_valid":all(x["integrity"]["status"]=="valid" for x in done.values())},
  ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3") as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",(str(pred),time.time(),TASK));db.commit()
 print("SEALED",sha(pred))
if __name__=="__main__":main()
