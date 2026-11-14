# -*- coding: utf-8 -*-
"""Gold-free gap plans over exposed16, followed by post-seal retrieval diagnostics."""
from pathlib import Path
import collections,hashlib,json,re,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_GAP_ANALYZER_20261114"
V2=A/"results/product_integration/LEAD_ANSWER_CONTRACT_MVP_V2_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
RROOT=ROOT/"external/benchmarks/rhelm"
RC=A/"results/product_integration/LEAD_G144_PRODUCT_ARTIFACT_BRIDGE_20261113/G144_STAGE_DEFAULT_OFF_RC"
sys.path[:0]=[str(RC),str(ROOT),str(A)]

from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.evidence_gap_analyzer import gap_messages,validate_gap_plan
from governance.evaluation.v11_capability.agents.contract_evidence_completion import supplement_gap_queries
from g144_artifact_bridge_rank import ranked_artifact_owner_sources

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
 c=dict(PROVIDERS["qwen"]);c.update({"provider":"qwen","model":"qwen3.8-flash","temperature":0,
   "enable_thinking":False,"response_format":{"type":"json_object"},"_capture_finish_reason":True});return c

def pool_docs(persona):
 out=[]
 for p in sorted((RROOT/"conversations"/persona).glob("*.json")):
  o=json.loads(p.read_text("utf-8"));date=str(o.get("date") or "")
  for t in o.get("conversation") or []:
   sid=f"{date}:{int(t['turn'])}";txt=f"User: {t.get('user','')}\nAssistant: {t.get('assistant','')}"
   out.append({"id":sid,"source_key":sid,"raw":txt,"text":"owner: "+txt,"valid_at":date})
 by=collections.defaultdict(list)
 for p in sorted((RROOT/"emails"/persona).glob("*.txt")):
  m=re.search(r"(\d{4})_(\d{2})_(\d{2})",p.name)
  if m:by["-".join(m.groups())].append(p)
 for d,ps in sorted(by.items()):
  txt="\n\n".join(f"### {p.name}\n"+p.read_text("utf-8",errors="replace") for p in ps)
  out.append({"id":f"Emails_{d}","source_key":f"Emails_{d}","raw":txt,"text":"owner: "+txt,"valid_at":d})
 for p in sorted((RROOT/"attachments"/persona).glob("*")):
  if p.is_file():
   txt=p.read_text("utf-8",errors="replace")
   out.append({"id":p.name,"source_key":p.name,"raw":txt,"text":"owner: "+txt,"valid_at":None})
 return out

def visible_evidence(messages):
 marker="AUTHORIZED EXTERNAL PUBLIC EVIDENCE:\n"
 text="\n".join(str(m.get("content") or "") for m in messages)
 return text.split(marker,1)[1] if marker in text else text

def main():
 P.mkdir(parents=True,exist_ok=True)
 ids=load(P0/"CASE_IDS.json")["case_ids"]
 suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
 contracts={x["case_id"]:x["contract"] for x in jl(V2/"CONTRACTS.jsonl")}
 assert len(ids)==len(contracts)==16

 scope_path=P/"SCOPE.json"
 if scope_path.exists():scope=load(scope_path)
 else:
  with sqlite3.connect(A/"TASKS.sqlite3",timeout=30) as db:
   nums=[int(x[0][4:]) for x in db.execute("select id from tasks where id like 'M2-X%'") if x[0][4:].isdigit()]
   tid=f"M2-X{max(nums)+1:03d}"
   db.execute("""insert into tasks(id,role,track,priority,title,acceptance,inputs,status,owner,artifact,updated_at)
    values(?,?,?,?,?,?,?,?,?,?,?)""",(tid,"MAINLINE","M2",1,
    "Answer-contract evidence gap analyzer exposed16",
    "Question+contract+visible evidence only; <=3 unresolved-node queries; <=2CNY; gold loaded only after plan seal",
    str(P0/"CASE_IDS.json"),"ACTIVE","xy-single-owner-20261114",str(P/"GAP_PLANS.jsonl"),time.time()))
   db.commit()
  scope={"schema":"xiaoyu-gap-analyzer-exposed16-scope-v1","task":tid,"fresh_capability_credit":False}
  scope_path.write_text(json.dumps(scope,ensure_ascii=False,indent=2)+"\n","utf-8")
 task=scope["task"]

 plans=P/"GAP_PLANS.jsonl";done={x["case_id"]:x for x in jl(plans)}
 for cid in ids:
  if cid in done:continue
  c=suite[cid];ev=visible_evidence(c["baseline_messages"])
  wire,usage=cached_chat(cfg(),gap_messages(c["question"],contracts[cid],ev),
    max_tokens=700,timeout=100,namespace="answer-contract-gap16-v1",
    budget_scope=task,cache_only=False)
  raw=decode(wire);plan=validate_gap_plan(contracts[cid],raw)
  item={"case_id":cid,"plan":plan,"finish_reason":usage.get("_finish_reason"),
        "visible_evidence_sha256":hashlib.sha256(ev.encode("utf-8")).hexdigest()}
  append(plans,item);done[cid]=item
  print("GAP",len(done),"/16",cid,"stop",plan["stop"],"queries",len(plan["search_queries"]),flush=True)
 if len(done)!=16:raise RuntimeError("incomplete")
 seal=P/"GAP_PLAN_SEAL.json"
 seal.write_text(json.dumps({"schema":"xiaoyu-gap-plan-seal-v1","n":16,
   "plans_sha256":sha(plans),"gold_loaded":False,"max_queries":3,
   "planner":"qwen3.8-flash non-thinking","fresh_capability_credit":False},
   ensure_ascii=False,indent=2)+"\n","utf-8")

 # Gold/evidence labels are loaded only after all plans are sealed.
 report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
 cache={};rows=[]
 for cid in ids:
  c=suite[cid];person=c["scope_id"];docs=cache.setdefault(person,pool_docs(person))
  out=supplement_gap_queries(done[cid]["plan"],docs,c["baseline_source_keys"],
                             ranked_artifact_owner_sources,max_extra=3,per_query=2)
  req=set(report[cid].get("resolved_evidence_ids") or [])
  b=set(c["baseline_source_keys"]);z=set(out["source_keys"])
  rows.append({"case_id":cid,"required":sorted(req),
    "baseline_complete":bool(req) and req<=b,"candidate_complete":bool(req) and req<=z,
    "baseline_hits":len(req&b),"candidate_hits":len(req&z),"required_n":len(req),
    "extra_source_keys":out["extra_source_keys"],"query_trace":out["queries"],
    "gap_plan":done[cid]["plan"]})
 result={"schema":"xiaoyu-gap-analyzer-retrieval-diagnostic-v1",
   "status":"EXPOSED_DEV_POST_SEAL_DIAGNOSTIC_ONLY","n":16,
   "mechanism_gold_free":True,"plans_sealed_before_labels":True,
   "baseline_complete":sum(x["baseline_complete"] for x in rows),
   "candidate_complete":sum(x["candidate_complete"] for x in rows),
   "baseline_hits":sum(x["baseline_hits"] for x in rows),
   "candidate_hits":sum(x["candidate_hits"] for x in rows),
   "required_total":sum(x["required_n"] for x in rows),
   "triggered":sum(bool(x["extra_source_keys"]) for x in rows),"rows":rows}
 (P/"POSTSEAL_RETRIEVAL_DIAGNOSTIC.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
             (str(P/"POSTSEAL_RETRIEVAL_DIAGNOSTIC.json"),time.time(),task));db.commit()
 print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
