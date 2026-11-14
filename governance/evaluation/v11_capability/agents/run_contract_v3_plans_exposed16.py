# -*- coding: utf-8 -*-
"""Question-only v3 answer-contract planner with explicit preconditions."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time
ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_V3_PRECONDITION_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_contract_mvp import planner_messages,validate_contract

def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p);return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def decode(s):
 t=str(s).strip();f=chr(96)*3
 if t.startswith(f):t=t.replace(f+"json","").replace(f,"").strip()
 return json.loads(t)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cfg():
 c=dict(PROVIDERS["qwen"]);c.update({"provider":"qwen","model":"qwen3.8-flash",
  "temperature":0,"enable_thinking":False,"response_format":{"type":"json_object"},
  "_capture_finish_reason":True});return c

def main():
 P.mkdir(parents=True,exist_ok=True)
 ids=load(P0/"CASE_IDS.json")["case_ids"]
 suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
 scope_path=P/"SCOPE.json"
 if scope_path.exists():scope=load(scope_path)
 else:
  with sqlite3.connect(A/"TASKS.sqlite3",timeout=30) as db:
   nums=[int(x[0][4:]) for x in db.execute("select id from tasks where id like 'M2-X%'") if x[0][4:].isdigit()]
   tid=f"M2-X{max(nums)+1:03d}"
   db.execute("""insert into tasks(id,role,track,priority,title,acceptance,inputs,status,owner,artifact,updated_at)
    values(?,?,?,?,?,?,?,?,?,?,?)""",(tid,"MAINLINE","M2",1,
    "Answer-contract v3 explicit-precondition planner exposed16",
    "Question-only; explicit preconditions; <=2CNY; no gold/evidence in planning; no fresh credit",
    str(P0/"CASE_IDS.json"),"ACTIVE","xy-single-owner-20261114",str(P/"CONTRACTS.jsonl"),time.time()))
   db.commit()
  scope={"schema":"xiaoyu-answer-contract-v3-plan-scope-v1","task":tid,"fresh_capability_credit":False}
  scope_path.write_text(json.dumps(scope,ensure_ascii=False,indent=2)+"\n","utf-8")
 task=scope["task"]
 out=P/"CONTRACTS.jsonl";done={x["case_id"]:x for x in jl(out)}
 for cid in ids:
  if cid in done:continue
  q=suite[cid]["question"]
  wire,usage=cached_chat(cfg(),planner_messages(q),max_tokens=900,timeout=100,
    namespace="answer-contract-v3-precondition-planner-v1",budget_scope=task,cache_only=False)
  raw=decode(wire);contract=validate_contract(q,raw)
  item={"case_id":cid,"contract":contract,"raw_contract":raw,
        "finish_reason":usage.get("_finish_reason")}
  append(out,item);done[cid]=item
  print("CONTRACT_V3",len(done),"/16",cid,
        "pre",len(contract.get("preconditions") or []),
        "hist",contract["history_need"],flush=True)
 if len(done)!=16:raise RuntimeError("incomplete")
 seal=P/"CONTRACTS_SEAL.json"
 seal.write_text(json.dumps({"schema":"xiaoyu-answer-contract-v3-precondition-seal-v1",
  "n":16,"contracts_sha256":sha(out),"question_only":True,"gold_loaded":False,
  "evidence_loaded":False,"planner":"qwen3.8-flash non-thinking",
  "preconditions_enabled":True,"fresh_capability_credit":False},
  ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
             (str(seal),time.time(),task));db.commit()
 print("SEALED",task,sha(seal),flush=True)

if __name__=="__main__":main()
