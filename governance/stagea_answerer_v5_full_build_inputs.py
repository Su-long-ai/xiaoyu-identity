#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the bounded full-51 Stage-A dev inputs for the V5 answerer.

No provider calls. No benchmark answer/evidence/judge text is placed in model
messages. All 51 questions use the same algorithm:
- V4 caller-owned temporal filtering + accepted R52 retrieval;
- question-keyed packing of user-authored turns from the question's own session;
- V5 minimal-sufficient-answer prompt.
No known/unknown label changes retrieval behavior.
"""
from __future__ import annotations
import hashlib,json,re,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUN=GOV/"budget50_halumem_dev_runtime_v1"
if str(GOV) not in sys.path: sys.path.insert(0,str(GOV))
import stagea_answerer_dev_v4_build_inputs as b4
import stagea_answerer_dev_v5_build_inputs as v5

QA=RUN/"QA_INPUTS_POST_SEAL.json"
OUT=GOV/"stagea_answerer_v5_full_inputs.json"

def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def qid_prefix(qid):
    m=re.match(r"hm-([ml])-q-([0-9a-f]+)-",str(qid))
    if not m: raise ValueError("bad qid "+str(qid))
    return m.group(1),m.group(2)

def turn_valid(question,timestamp):
    bound=b4.question_upper_bound(question)
    if bound is None:return True
    ts=b4.parse_dt(timestamp)
    if ts is None:return False
    day=ts.date()
    return day < bound["date"] if bound["relation"]=="before" else day <= bound["date"]

def repack(qa,base_ctx):
    rec=b4.record(qa["variant"],qa["uuid"])
    si=int(qa["session_index"])
    session=rec["sessions"][si]
    keys=v5.query_keys(qa["question"])
    variant,hp=qid_prefix(qa["qa_case_id"])
    extra=[]
    for di,turn in enumerate(session.get("dialogue") or []):
        if str(turn.get("role"))!="user":continue
        if not turn_valid(qa["question"],turn.get("timestamp")):continue
        text=str(turn.get("content") or "")
        sc=v5.score(text,keys)
        if sc<=0:continue
        ts=b4.parse_dt(turn.get("timestamp"))
        extra.append({
            "authority":"user_source_history",
            "timestamp":ts.isoformat() if ts else None,
            "effective_at":None,
            "source_id":f"hm:{variant}:{hp}:s{si}:t{di}",
            "channel":"same_session_question_pack",
            "text":text,
            "_score":sc,
        })
    merged=[];seen=set()
    for m in list(base_ctx)+extra:
        key=(m.get("authority"),m.get("source_id")," ".join(str(m.get("text","")).split()))
        if key in seen:continue
        seen.add(key)
        mm=dict(m)
        mm["_score"]=max(int(mm.get("_score") or 0),v5.score(mm.get("text",""),keys))
        merged.append(mm)
    ar={"user_state":0,"user_source_history":1,"user_history":2}
    merged.sort(key=lambda m:(-int(m.get("_score") or 0),ar.get(str(m.get("authority")),9),str(m.get("source_id"))))
    out=merged[:20]
    for m in out:m.pop("_score",None)
    return out,{"same_session_candidate_n":len(extra)}

def main():
    qas=json.loads(QA.read_text("utf-8"))["rows"]
    loc={}
    for pp in sorted((RUN/"predictions").glob("*.json")):
        pred=json.loads(pp.read_text("utf-8"))
        for li,sess in enumerate(pred.get("sessions") or []):
            for q in sess.get("questions") or []:
                loc[q["qa_case_id"]]=(pp,pred,li,sess)
    rows=[]
    for qa in qas:
        qid=qa["qa_case_id"]
        pp,pred,li,sess=loc[qid]
        cp=RUN/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
        base_ctx,meta=b4.build_context(qa,pred,sess,cp)
        ctx,pack=repack(qa,base_ctx)
        lines=[]
        for i,m in enumerate(ctx,1):
            md=f"authority={m['authority']}"
            if m.get("timestamp"):md+=f" timestamp={m['timestamp']}"
            lines.append(f"[{i}] {md}\n{m['text']}")
        user="AUTHORIZED MEMORIES:\n"+("\n\n".join(lines) if lines else "(none)")+"\n\nQUESTION:\n"+qa["question"]
        messages=[{"role":"system","content":v5.SYSTEM},{"role":"user","content":user}]
        rows.append({
            "case_id":"ansv5full-"+hashlib.sha256(qid.encode()).hexdigest()[:16],
            "qa_case_id":qid,
            "variant":qa["variant"],
            "selection_group":"full_dev",
            "selection_prior_label":None,
            "selection_gold_unknown":False,
            "question":qa["question"],
            "historical_upper_bound":meta["upper_bound"],
            "authorized_memory_count":len(ctx),
            "authorized_memories":ctx,
            "retrieval_meta":{**meta,**pack},
            "messages":messages,
            "request_messages_sha256":stable(messages),
        })
    out={
      "schema":"xiaoyu-stagea-answerer-v5-full-inputs-v1",
      "status":"DEV_ONLY",
      "case_count":len(rows),
      "prompt_contains_reference_answer":False,
      "prompt_contains_benchmark_evidence":False,
      "prompt_contains_judge_label":False,
      "assistant_history_allowed_for_user_fact":False,
      "uniform_algorithm_for_all_qa":True,
      "context_cap":20,
      "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({
      "case_count":len(rows),
      "sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
      "max_context":max(x["authorized_memory_count"] for x in rows),
      "same_session_added_cases":sum(x["retrieval_meta"]["same_session_candidate_n"]>0 for x in rows),
      "message_bytes":sum(len(json.dumps(x["messages"],ensure_ascii=False).encode()) for x in rows)
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
