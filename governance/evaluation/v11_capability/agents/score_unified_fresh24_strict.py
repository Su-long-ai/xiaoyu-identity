# -*- coding: utf-8 -*-
"""Post-seal strict paired scoring for unified answer-contract fresh24.

Must not run before both baseline/candidate prediction seals exist and match.
Reference is authoritative. Judge sees only question/reference/A/B, no dataset
background or retrieval labels. Retrieval labels are opened only after all
semantic judgments have been fixed.
"""
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_UNIFIED_FRESH24_20261114"
EXT=ROOT/"governance/evaluation/external_suite"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_outcome_gate import (
 inspect_answer,missing_requested_fields,count_contradiction
)
TASK="M2-X341"
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p);return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def decode(s):
 t=str(s).strip();ticks=chr(96)*3
 if t.startswith(ticks):t=t.replace(ticks+"json","").replace(ticks+"JSON","").replace(ticks,"").strip()
 i=t.find("{");j=t.rfind("}")
 if i<0 or j<i:raise ValueError("json missing")
 return json.loads(t[i:j+1])
def main():
 suitep=P/"FRESH24_FROZEN_NO_GOLD.json";suite=load(suitep)
 bs=load(P/"BASELINE_PREDICTION_SEAL.json");cs=load(P/"CANDIDATE_PREDICTION_SEAL.json")
 if bs["suite_sha256"]!=sha(suitep) or cs["suite_sha256"]!=sha(suitep):raise RuntimeError("seal suite mismatch")
 if bs.get("gold_loaded") is not False or cs.get("gold_loaded") is not False:raise RuntimeError("prediction seal invalid")
 if bs["answers_sha256"]!=sha(P/"BASELINE_ANSWERS.jsonl"):raise RuntimeError("baseline bytes drift")
 if cs["answers_sha256"]!=sha(P/"CANDIDATE_ANSWERS.jsonl"):raise RuntimeError("candidate bytes drift")
 cases={x["case_id"]:x for x in suite["cases"]}
 ids=list(cases)
 baseline={x["case_id"]:x for x in jl(P/"BASELINE_ANSWERS.jsonl")}
 candidate={x["case_id"]:x for x in jl(P/"CANDIDATE_ANSWERS.jsonl")}
 # Gold is opened only here, after both prediction seals.
 gold={x["case_id"]:x for x in jl(EXT/"normalized/rhelm_cases.jsonl") if x["case_id"] in set(ids)}
 if len(gold)!=24:raise RuntimeError("gold coverage")
 cfg=dict(PROVIDERS["qwen"]);cfg.update({"provider":"qwen","model":"qwen3.8-flash","temperature":0,
   "enable_thinking":False,"response_format":{"type":"json_object"},"_capture_finish_reason":True})
 jf=P/"STRICT_JUDGMENTS.jsonl";done={x["case_id"]:x for x in jl(jf)}
 for cid in ids:
  if cid in done:continue
  q=cases[cid]["question"];ref=gold[cid]["gold_answer"]
  pair=[("baseline",baseline[cid]["answer"]),("candidate",candidate[cid]["answer"])]
  if int(hashlib.sha256(("unified-f24-strict|"+cid).encode()).hexdigest(),16)%2:pair.reverse()
  prompt=f"""You are a strict evaluator. The REFERENCE ANSWER is authoritative.
Do NOT use outside knowledge, dataset familiarity, guessed hidden context, or retrieval labels.
A candidate is correct only if it gives the substance required by the reference and does not contradict it.
If it says the answer is unknown when the reference gives a definite answer, mark false.
A wrong date/person/count/item is false even if related details are mentioned.
Facts explicitly supplied by the user in QUESTION are current-turn premises; do not demand memory proof for them unless the reference itself corrects them.
For misleading/action/drafting questions, merely complying is false when the reference requires surfacing a material personal constraint/correction.
For lists/counts/multi-part requests, missing a required item/field is false.
Return JSON only:
{{"A_correct":bool,"B_correct":bool,
"A_failure_type":"none|source_conflict|temporal_reasoning|general_reasoning|answer_incomplete",
"B_failure_type":"none|source_conflict|temporal_reasoning|general_reasoning|answer_incomplete",
"reason":"<=180 chars"}}

QUESTION:
{q}

REFERENCE ANSWER:
{ref}

ANSWER A:
{pair[0][1]}

ANSWER B:
{pair[1][1]}"""
  wire,u=cached_chat(cfg,[{"role":"system","content":"Strict reference-only paired evaluator. JSON only."},
                          {"role":"user","content":prompt}],
    max_tokens=420,timeout=100,namespace="unified-fresh24-strict-judge-v1",
    budget_scope=TASK,cache_only=False)
  o=decode(wire);mapped={}
  for lab,(arm,_) in zip(("A","B"),pair):
   mapped[arm]={"correct":bool(o[lab+"_correct"]),"failure_type":str(o.get(lab+"_failure_type") or "none")}
  row={"case_id":cid,"order":[x[0] for x in pair],
       "baseline_correct":mapped["baseline"]["correct"],"candidate_correct":mapped["candidate"]["correct"],
       "baseline_failure_type":mapped["baseline"]["failure_type"],
       "candidate_failure_type":mapped["candidate"]["failure_type"],
       "reason":str(o.get("reason") or "")[:500],"finish_reason":u.get("_finish_reason")}
  append(jf,row);done[cid]=row
  print("JUDGE",len(done),"/24",cid,row["baseline_correct"],row["candidate_correct"],flush=True)

 # Deterministic veto + final metrics.
 wins=losses=both=neither=0;bycat=defaultdict(lambda:{"n":0,"wins":0,"losses":0,"baseline_correct":0,"candidate_correct":0})
 failure=Counter();rows=[]
 for cid in ids:
  c=cases[cid];ref=gold[cid]["gold_answer"];j=done[cid]
  ba=baseline[cid]["answer"];ca=candidate[cid]["answer"]
  bi=inspect_answer(ba,baseline[cid].get("finish_reason"));ci=inspect_answer(ca,candidate[cid].get("finish_reason"))
  bf=missing_requested_fields(c["question"],ref,ba);cf=missing_requested_fields(c["question"],ref,ca)
  bc=count_contradiction(c["question"],ref,ba);cc=count_contradiction(c["question"],ref,ca)
  bok=bool(j["baseline_correct"]) and bi["status"]=="valid" and not bf.get("missing") and not bc["contradiction"]
  cok=bool(j["candidate_correct"]) and ci["status"]=="valid" and not cf.get("missing") and not cc["contradiction"]
  if bok and cok:both+=1
  elif cok and not bok:wins+=1
  elif bok and not cok:losses+=1
  else:neither+=1
  z=bycat[c["category"]];z["n"]+=1;z["wins"]+=int(cok and not bok);z["losses"]+=int(bok and not cok)
  z["baseline_correct"]+=int(bok);z["candidate_correct"]+=int(cok)
  ft="none"
  if not cok:
   ft="answer_incomplete" if cf.get("missing") else j["candidate_failure_type"]
   # Post-seal retrieval-source diagnosis: required source IDs, not answer generation.
  rows.append({"case_id":cid,"category":c["category"],"question":c["question"],"reference":ref,
    "baseline_correct":bool(bok),"candidate_correct":bool(cok),
    "baseline_answer":ba,"candidate_answer":ca,
    "candidate_failure_type":ft,"judge_reason":j["reason"],
    "supplemental_source_keys":candidate[cid].get("supplemental_source_keys") or [],
    "fallback_to_baseline":bool(candidate[cid].get("fallback_to_baseline")),
    "repair_used":bool(candidate[cid].get("repair_used"))})
  if ft!="none":failure[ft]+=1

 result={"schema":"xiaoyu-unified-answer-contract-fresh24-strict-verdict-v1",
  "status":"FRESH_DISJOINT_PAIRED_FINAL_ANSWER_EVIDENCE",
  "n":24,"scope_type":"broad",
  "baseline_correct":both+losses,"candidate_correct":both+wins,
  "wins":wins,"losses":losses,"both_correct":both,"both_wrong":neither,
  "net_final_correct":wins-losses,"by_category":dict(bycat),
  "candidate_failure_type_counts":dict(failure),
  "candidate_freeze_sha256":sha(P/"CANDIDATE_FREEZE.json"),
  "orchestration_lock_sha256":sha(P/"ORCHESTRATION_LOCK.json"),
  "suite_sha256":sha(suitep),"baseline_prediction_seal_sha256":sha(P/"BASELINE_PREDICTION_SEAL.json"),
  "candidate_prediction_seal_sha256":sha(P/"CANDIDATE_PREDICTION_SEAL.json"),
  "strict_judgments_sha256":sha(jf),
  "fresh_disjoint":True,"gold_opened_after_prediction_seals":True,
  "supplement_trigger_count":sum(bool(x.get("supplemental_source_keys")) for x in candidate.values()),
  "fallback_count":sum(bool(x.get("fallback_to_baseline")) for x in candidate.values()),
  "repair_count":sum(bool(x.get("repair_used")) for x in candidate.values()),
  "final_answer_gate_pass":wins-losses>0,
  "rows":rows}
 out=P/"FRESH24_STRICT_VERDICT.json";out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3") as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",(str(out),time.time(),TASK));db.commit()
 print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
