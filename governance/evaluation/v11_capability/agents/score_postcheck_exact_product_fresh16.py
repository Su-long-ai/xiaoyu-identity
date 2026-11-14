# -*- coding: utf-8 -*-
"""Strict post-seal paired scorer for postcheck RC exact product fresh16."""
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_POSTCHECK_FRESH16_20261115"
CAND=A/"results/product_integration/LEAD_ANSWER_CONTRACT_POSTCHECK_RC_20261114"
MAN=CAND/"ANSWER_CONTRACT_POSTCHECK_MANIFEST.json"
EXT=ROOT/"governance/evaluation/external_suite"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_outcome_gate import (
    inspect_answer,missing_requested_fields,count_contradiction
)
TASK=json.loads((P/"SCOPES.json").read_text("utf-8"))["judge_task"]

def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p)
 return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:
  f.write(json.dumps(x,ensure_ascii=False)+"\n");f.flush()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def decode(s):
 t=str(s).strip();ticks=chr(96)*3
 if t.startswith(ticks):
  t=t.replace(ticks+"json","").replace(ticks+"JSON","").replace(ticks,"").strip()
 i=t.find("{");j=t.rfind("}")
 if i<0 or j<i:raise ValueError("judge_json_missing")
 return json.loads(t[i:j+1])

def main():
 suitep=P/"FRESH16_FROZEN_NO_GOLD.json"
 suite=load(suitep);freeze=load(P/"FRESH16_FREEZE_SEAL.json")
 offseal=load(P/"OFF_PREDICTION_SEAL.json")
 onseal=load(P/"ON_PREDICTION_SEAL.json")
 cachep=P/"source_runtime_cache/CACHE_INDEX.json"
 if freeze["suite_sha256"]!=sha(suitep):
  raise RuntimeError("suite_freeze_drift")
 if freeze["candidate_manifest_sha256"]!=sha(MAN):
  raise RuntimeError("candidate_freeze_drift")
 for s in (offseal,onseal):
  if s["suite_sha256"]!=sha(suitep) or s["candidate_manifest_sha256"]!=sha(MAN):
   raise RuntimeError("prediction_binding_mismatch")
  if s.get("gold_loaded") is not False or s.get("same_product_manifest") is not True:
   raise RuntimeError("prediction_provenance_invalid")
  if s.get("source_cache_index_sha256")!=sha(cachep):
   raise RuntimeError("source_cache_binding_mismatch")
  if s.get("all_used_canonical_document_ingress") is not True:
   raise RuntimeError("document_ingress_not_proven")

 offp=P/"OFF_ANSWERS.jsonl";onp=P/"ON_ANSWERS.jsonl"
 if offseal["answers_sha256"]!=sha(offp) or onseal["answers_sha256"]!=sha(onp):
  raise RuntimeError("prediction_bytes_drift")
 off={x["case_id"]:x for x in jl(offp)}
 on={x["case_id"]:x for x in jl(onp)}
 cases={x["case_id"]:x for x in suite["cases"]};ids=list(cases)
 if len(off)!=16 or len(on)!=16 or set(off)!=set(ids) or set(on)!=set(ids):
  raise RuntimeError("prediction_case_coverage_invalid")

 # Gold is first opened here, after both product prediction seals.
 gold={x["case_id"]:x for x in jl(EXT/"normalized/rhelm_cases.jsonl")
       if x["case_id"] in set(ids)}
 if len(gold)!=16:raise RuntimeError("gold_coverage_invalid")

 cfg=dict(PROVIDERS["qwen"]);cfg.update({
   "provider":"qwen","model":"qwen3.8-flash","temperature":0,
   "enable_thinking":False,"response_format":{"type":"json_object"},
   "_capture_finish_reason":True})
 jf=P/"STRICT_JUDGMENTS.jsonl";done={x["case_id"]:x for x in jl(jf)}
 for cid in ids:
  if cid in done:continue
  q=cases[cid]["question"];ref=gold[cid]["gold_answer"]
  pair=[("off",off[cid]["answer"]),("on",on[cid]["answer"])]
  if int(hashlib.sha256(("postcheck-product-fresh16|"+cid).encode()).hexdigest(),16)%2:
   pair.reverse()
  prompt=f"""You are a strict evaluator. REFERENCE ANSWER is authoritative.
Use only QUESTION, REFERENCE ANSWER, ANSWER A, and ANSWER B.
Do not use outside knowledge, benchmark familiarity, guessed hidden context, or retrieval labels.
A candidate is correct only if it gives the substance required by the reference and does not contradict it.
If it says unknown when the reference gives a definite answer, mark false.
A wrong date/person/count/item is false even if related details are also mentioned.
Facts explicitly supplied in QUESTION are current-turn premises unless the REFERENCE corrects them.
For misleading/action/drafting questions, simple compliance is false when the REFERENCE requires surfacing a material personal constraint/correction.
For list/count/multi-part requests, missing a required item or requested field is false.
Extra detail absent from the REFERENCE is not by itself an error; mark it wrong only if it contradicts QUESTION/REFERENCE.
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
  wire,u=cached_chat(cfg,[
    {"role":"system","content":"Strict reference-only paired evaluator. JSON only."},
    {"role":"user","content":prompt}],
    max_tokens=420,timeout=100,namespace="postcheck-exact-product-fresh16-strict-v1",
    budget_scope=TASK,cache_only=False)
  o=decode(wire);mapped={}
  for lab,(arm,_) in zip(("A","B"),pair):
   mapped[arm]={"correct":bool(o[lab+"_correct"]),
                "failure_type":str(o.get(lab+"_failure_type") or "none")}
  invariant_fix=None
  if pair[0][1]==pair[1][1] and mapped["off"]["correct"]!=mapped["on"]["correct"]:
   # Conservative tie. It can reduce apparent accuracy but can never fabricate
   # a candidate gain or loss from identical visible answers.
   mapped["off"]["correct"]=False
   mapped["on"]["correct"]=False
   invariant_fix="identical_answer_disagreement_forced_false_tie"
  row={"case_id":cid,"order":[x[0] for x in pair],
       "off_correct":mapped["off"]["correct"],
       "on_correct":mapped["on"]["correct"],
       "pair_invariant_fix":invariant_fix,
       "off_failure_type":mapped["off"]["failure_type"],
       "on_failure_type":mapped["on"]["failure_type"],
       "reason":str(o.get("reason") or "")[:500],
       "finish_reason":u.get("_finish_reason")}
  append(jf,row);done[cid]=row
  print("POSTCHECK_JUDGE",len(done),"/16",cid,
        row["off_correct"],row["on_correct"],flush=True)

 wins=losses=both=neither=0
 bycat=defaultdict(lambda:{"n":0,"wins":0,"losses":0,
                           "off_correct":0,"on_correct":0})
 failure=Counter();rows=[]
 for cid in ids:
  c=cases[cid];ref=gold[cid]["gold_answer"];j=done[cid]
  oa=off[cid]["answer"];na=on[cid]["answer"]
  oi=inspect_answer(oa,off[cid].get("finish_reason"))
  ni=inspect_answer(na,on[cid].get("finish_reason"))
  of=missing_requested_fields(c["question"],ref,oa)
  nf=missing_requested_fields(c["question"],ref,na)
  oc=count_contradiction(c["question"],ref,oa)
  nc=count_contradiction(c["question"],ref,na)
  ook=bool(j["off_correct"]) and oi["status"]!="invalid" and not of.get("missing") and not oc["contradiction"]
  nok=bool(j["on_correct"]) and ni["status"]!="invalid" and not nf.get("missing") and not nc["contradiction"]
  if ook and nok:both+=1
  elif nok and not ook:wins+=1
  elif ook and not nok:losses+=1
  else:neither+=1
  z=bycat[c["category"]]
  z["n"]+=1;z["wins"]+=int(nok and not ook);z["losses"]+=int(ook and not nok)
  z["off_correct"]+=int(ook);z["on_correct"]+=int(nok)
  ft="none"
  if not nok:ft="answer_incomplete" if nf.get("missing") else j["on_failure_type"]
  if ft!="none":failure[ft]+=1
  ac=on[cid].get("answer_contract") or {}
  rows.append({"case_id":cid,"category":c["category"],
    "question":c["question"],"reference":ref,
    "off_correct":bool(ook),"on_correct":bool(nok),
    "off_answer":oa,"on_answer":na,"on_failure_type":ft,
    "judge_reason":j["reason"],
    "answer_contract_activated":bool(ac.get("activated")),
    "answer_contract_fallback":bool(ac.get("fallback")),
    "supplemental_source_ids":ac.get("supplemental_source_ids") or [],
    "off_answer_origin":off[cid].get("answer_origin"),
    "on_answer_origin":on[cid].get("answer_origin")})

 result={
  "schema":"xiaoyu-answer-contract-postcheck-exact-product-fresh16-verdict-v1",
  "status":"FRESH_DISJOINT_EXACT_PRODUCT_PAIRED_FINAL_ANSWER_EVIDENCE",
  "n":16,"scope_type":"broad_stage1",
  "off_correct":both+losses,"on_correct":both+wins,
  "wins":wins,"losses":losses,"both_correct":both,"both_wrong":neither,
  "net_final_correct":wins-losses,
  "by_category":dict(bycat),
  "on_failure_type_counts":dict(failure),
  "candidate_manifest_sha256":sha(MAN),
  "suite_sha256":sha(suitep),
  "source_cache_index_sha256":sha(cachep),
  "off_prediction_seal_sha256":sha(P/"OFF_PREDICTION_SEAL.json"),
  "on_prediction_seal_sha256":sha(P/"ON_PREDICTION_SEAL.json"),
  "strict_judgments_sha256":sha(jf),
  "fresh_disjoint":True,
  "candidate_frozen_before_suite_selection":True,
  "gold_opened_after_prediction_seals":True,
  "same_exact_product_manifest":True,
  "canonical_document_ingress":True,
  "answer_contract_activated_n":sum(
    bool((x.get("answer_contract") or {}).get("activated")) for x in on.values()),
  "answer_contract_fallback_n":sum(
    bool((x.get("answer_contract") or {}).get("fallback")) for x in on.values()),
  "supplement_trigger_n":sum(
    bool((x.get("answer_contract") or {}).get("supplemental_source_ids")) for x in on.values()),
  "pair_invariant_fix_n":sum(bool(x.get("pair_invariant_fix")) for x in done.values()),
  "final_answer_gate_pass":wins-losses>0,
  "product_pilot_auto_release":False,
  "rows":rows}
 out=P/"FRESH16_PRODUCT_VERDICT.json"
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("UPDATE tasks SET status='DONE',artifact=?,updated_at=? WHERE id=?",
             (str(out),time.time(),TASK));db.commit()
 print(json.dumps({k:v for k,v in result.items() if k!="rows"},
                  ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":main()
