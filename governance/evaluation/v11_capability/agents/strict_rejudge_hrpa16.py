# -*- coding: utf-8 -*-
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_outcome_gate import (
    classify_delivery_trace, inspect_answer, missing_requested_fields, count_contradiction
)

TASK="M2-X335"
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p)
 return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def decode(s):
 t=str(s).strip();f=chr(96)*3
 if t.startswith(f):t=t.replace(f+"json","").replace(f,"").strip()
 return json.loads(t)

def main():
 old=load(P/"DIAGNOSTIC_VERDICT.json")
 rows={x["case_id"]:x for x in old["rows"]}
 outj=P/"STRICT_REJUDGE_JUDGMENTS.jsonl"
 done={x["case_id"]:x for x in jl(outj)}
 cfg=dict(PROVIDERS["qwen"]);cfg.update({
  "provider":"qwen","model":"qwen3.8-flash","temperature":0,
  "enable_thinking":False,"response_format":{"type":"json_object"},
  "_capture_finish_reason":True})
 for cid,r in rows.items():
  if cid in done:continue
  reverse=int(hashlib.sha256(("strict-v2|"+cid).encode()).hexdigest(),16)%2
  pair=[("baseline",r["baseline_answer"]),("manual",r["manual_answer"])]
  if reverse:pair.reverse()
  prompt=f"""You are a strict evaluator. The REFERENCE ANSWER below is authoritative for this item.
Do NOT use outside knowledge, dataset familiarity, guessed hidden context, or facts not in QUESTION/REFERENCE.
A candidate is correct only if it gives the substance required by the reference and does not contradict it.
If it refuses/hedges that the answer is unknown when the reference gives a definite answer, mark false.
If it gives a wrong date/person/count/item while also mentioning something related, mark false.
If the user supplies a premise in the QUESTION, do not demand memory evidence for that premise; evaluate whether the response handles it as the reference requires.
For multi-part/advice/correction questions, partial recognition without the reference's key corrective action is false.
Return JSON only:
{{"A_correct":bool,"B_correct":bool,
  "A_failure_type":"none|source_conflict|temporal_reasoning|general_reasoning|answer_incomplete",
  "B_failure_type":"none|source_conflict|temporal_reasoning|general_reasoning|answer_incomplete",
  "reason":"<=180 chars"}}

QUESTION:
{r["question"]}

REFERENCE ANSWER:
{r["reference"]}

ANSWER A:
{pair[0][1]}

ANSWER B:
{pair[1][1]}
"""
  wire,usage=cached_chat(cfg,[{"role":"system","content":"Strict reference-only paired evaluator. JSON only."},
                              {"role":"user","content":prompt}],
                         max_tokens=420,timeout=100,namespace="hrpa16-strict-rejudge-v2",
                         budget_scope=TASK,cache_only=False)
  o=decode(wire); mapped={}
  for lab,(arm,_) in zip(("A","B"),pair):
   mapped[arm]={"correct":bool(o[lab+"_correct"]),
                "failure_type":str(o.get(lab+"_failure_type") or "none")}
  item={"case_id":cid,"order":[x[0] for x in pair],
        "baseline_correct":mapped["baseline"]["correct"],
        "manual_correct":mapped["manual"]["correct"],
        "baseline_failure_type":mapped["baseline"]["failure_type"],
        "manual_failure_type":mapped["manual"]["failure_type"],
        "reason":str(o.get("reason") or "")[:500],
        "finish_reason":usage.get("_finish_reason")}
  append(outj,item);done[cid]=item
  print("STRICT",len(done),"/",len(rows),cid,item["baseline_correct"],item["manual_correct"],flush=True)

 # Rebuild diagnostic metrics using frozen H/R/P facts from old row fields.
 bc=mc=gain=loss=0;sb=Counter();sm=Counter()
 groups=defaultdict(lambda:{"n":0,"baseline_correct":0,"manual_correct":0,"gain":0,"loss":0})
 newrows=[]
 for cid,r in rows.items():
  j=done[cid];q=r["question"];g=r["reference"]
  bi=inspect_answer(r["baseline_answer"],"stop")
  mi=inspect_answer(r["manual_answer"],"stop")
  bf=missing_requested_fields(q,g,r["baseline_answer"]);mf=missing_requested_fields(q,g,r["manual_answer"])
  bcnt=count_contradiction(q,g,r["baseline_answer"]);mcnt=count_contradiction(q,g,r["manual_answer"])
  bok=bool(j["baseline_correct"]) and not bf.get("missing") and not bcnt["contradiction"] and bi["status"]=="valid"
  mok=bool(j["manual_correct"]) and not mf.get("missing") and not mcnt["contradiction"] and mi["status"]=="valid"

  btrace={"basis":"deterministic","history_sufficient":True,
          "retrieval_sufficient":r["baseline_retrieval_sufficient"],
          "prompt_sufficient":r["baseline_full_required_raw_in_prompt"]}
  if not bok and r["baseline_full_required_raw_in_prompt"]:
   ft="answer_incomplete" if bf.get("missing") else j["baseline_failure_type"]
   if ft=="source_conflict":btrace.update(source_conflict_present=True,source_conflict_resolved=False)
   elif ft=="temporal_reasoning":btrace.update(temporal_required=True,temporal_reasoning_correct=False)
   elif ft=="answer_incomplete":btrace.update(required_output_complete=False)
   else:btrace.update(general_reasoning_correct=False)
  mtrace={"basis":"deterministic","history_sufficient":True,"retrieval_sufficient":True,"prompt_sufficient":True}
  if not mok:
   ft="answer_incomplete" if mf.get("missing") else j["manual_failure_type"]
   if ft=="source_conflict":mtrace.update(source_conflict_present=True,source_conflict_resolved=False)
   elif ft=="temporal_reasoning":mtrace.update(temporal_required=True,temporal_reasoning_correct=False)
   elif ft=="answer_incomplete":mtrace.update(required_output_complete=False)
   else:mtrace.update(general_reasoning_correct=False)
  bs="none" if bok else classify_delivery_trace(btrace)["stage"]
  ms="none" if mok else classify_delivery_trace(mtrace)["stage"]
  if not bok:sb[bs]+=1
  if not mok:sm[ms]+=1
  bc+=bok;mc+=mok;gain+=mok and not bok;loss+=bok and not mok
  group="prior_complete_wrong" if r["prior_baseline_evidence_complete"] else "prior_evidence_incomplete"
  z=groups[group];z["n"]+=1;z["baseline_correct"]+=int(bok);z["manual_correct"]+=int(mok)
  z["gain"]+=int(mok and not bok);z["loss"]+=int(bok and not mok)
  nr=dict(r);nr.update({
    "baseline_correct":bool(bok),"manual_correct":bool(mok),
    "baseline_failure_stage":bs,"manual_failure_stage":ms,
    "strict_judge_reason":j["reason"]})
  newrows.append(nr)
 result={
  "schema":"xiaoyu-hrpa16-strict-reference-rejudge-v2",
  "status":"EXPOSED_DEV_DIAGNOSTIC_NOT_FRESH_OR_RELEASE",
  "n":len(newrows),"baseline_correct":int(bc),"manual_full_evidence_correct":int(mc),
  "gains":int(gain),"losses":int(loss),"net":int(gain-loss),
  "supply_or_packaging_rescues":int(gain),
  "consumption_failures_after_full_evidence":len(newrows)-int(mc),
  "baseline_failure_stages_reclassified":dict(sb),"manual_failure_stages":dict(sm),
  "groups":dict(groups),"fresh_capability_credit":False,
  "old_judge_disagreements":[cid for cid in rows if
     rows[cid]["baseline_correct"]!=next(x for x in newrows if x["case_id"]==cid)["baseline_correct"] or
     rows[cid]["manual_correct"]!=next(x for x in newrows if x["case_id"]==cid)["manual_correct"]],
  "diagnostic_interpretation":(
    "SUPPLY_DOMINANT" if gain>=8 and len(newrows)-mc<=4 else
    "MIXED_SUPPLY_AND_CONSUMPTION" if gain>=4 and len(newrows)-mc>=4 else
    "CONSUMPTION_DOMINANT" if len(newrows)-mc>=8 else "WEAK_OR_MIXED_SIGNAL"),
  "rows":newrows}
 (P/"STRICT_REJUDGE_VERDICT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
             (str(P/"STRICT_REJUDGE_VERDICT.json"),time.time(),TASK));db.commit()
 print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
