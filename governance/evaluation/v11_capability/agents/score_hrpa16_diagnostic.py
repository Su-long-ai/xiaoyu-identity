# -*- coding: utf-8 -*-
from pathlib import Path
from collections import Counter, defaultdict
import hashlib, json, sqlite3, sys, time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_outcome_gate import (
    inspect_answer, missing_requested_fields, count_contradiction,
    classify_delivery_trace,
)

def load(p): return json.loads(Path(p).read_text("utf-8"))
def jl(p):
    p=Path(p)
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
    with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def decode(t):
    s=str(t).strip(); fence=chr(96)*3
    if s.startswith(fence):
        s=s.replace(fence+"json","").replace(fence,"").strip()
    return json.loads(s)

def main():
    scope=load(P/"SCOPES.json")
    cases=load(P/"CASE_IDS.json")["case_ids"]
    select={x["case_id"]:x for x in load(P/"SELECTION_DIAGNOSTIC.json")}
    suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
    base={x["case_id"]:x for x in jl(P/"BASELINE_REUSED_ANSWERS.jsonl")}
    manual={x["case_id"]:x for x in jl(P/"MANUAL_ANSWERS.jsonl")}
    evidence={x["case_id"]:x for x in jl(P/"MANUAL_EVIDENCE.jsonl")}
    gold={x["case_id"]:x for x in jl(EXT/"normalized/rhelm_cases.jsonl") if x["case_id"] in set(cases)}
    bind=load(P/"BASELINE_BINDING.json")
    seal=load(P/"MANUAL_ANSWERS.jsonl.seal.json")
    assert len(cases)==len(base)==len(manual)==len(evidence)==len(gold)==16
    assert bind["reused_subset_sha256"]==sha(P/"BASELINE_REUSED_ANSWERS.jsonl")
    assert seal["answers_sha256"]==sha(P/"MANUAL_ANSWERS.jsonl") and seal["gold_loaded"] is False

    # Exact H/R/P diagnostics from frozen public evidence, not model self-report.
    delivery={}
    for cid in cases:
        c=suite[cid]; e=evidence[cid]; req=list(dict.fromkeys(e["source_refs"]))
        retrieved=set(c["baseline_source_keys"])
        prompt="\n".join(str(m.get("content") or "") for m in c["baseline_messages"])
        full_texts=[]
        # MANUAL_EVIDENCE is rendered as [SOURCE key]\nraw text blocks.
        ev=e["evidence_text"]
        for i,k in enumerate(req):
            marker=f"[SOURCE {k}]\n"
            start=ev.find(marker)
            assert start>=0,(cid,k)
            start+=len(marker)
            next_starts=[ev.find(f"\n\n[SOURCE {k2}]\n",start) for k2 in req[i+1:]]
            next_starts=[z for z in next_starts if z>=0]
            end=min(next_starts) if next_starts else len(ev)
            full_texts.append((k,ev[start:end]))
        r_ok=all(k in retrieved for k in req)
        p_ok=all(txt in prompt for _,txt in full_texts)
        delivery[cid]={"history_sufficient":True,"retrieval_sufficient":r_ok,
                       "prompt_sufficient":p_ok,"required_sources":req,
                       "full_required_sources_in_prompt":[k for k,txt in full_texts if txt in prompt]}

    jfile=P/"JUDGMENTS.jsonl"; judged={x["case_id"]:x for x in jl(jfile)}
    cfg=dict(PROVIDERS["qwen"]);cfg.update({"provider":"qwen","model":"qwen3.8-flash",
        "temperature":0,"enable_thinking":False,"response_format":{"type":"json_object"},
        "_capture_finish_reason":True})
    for cid in cases:
        if cid in judged: continue
        q=suite[cid]["question"]; g=gold[cid]["gold_answer"]
        reverse=int(hashlib.sha256(("hrpa16-blind|"+cid).encode()).hexdigest(),16)%2==1
        pair=[("baseline",base[cid]["answer"]),("manual",manual[cid]["answer"])]
        if reverse: pair.reverse()
        ev=evidence[cid]["evidence_text"]
        prompt=("QUESTION:\n"+q+"\n\nREFERENCE ANSWER:\n"+g+
          "\n\nCOMPLETE AUTHORIZED RAW EVIDENCE:\n"+ev+
          "\n\nANSWER A:\n"+pair[0][1]+"\n\nANSWER B:\n"+pair[1][1]+
          "\n\nReturn strict JSON: A_correct, B_correct booleans; "
          "A_failure_type and B_failure_type each one of none/source_conflict/temporal_reasoning/"
          "general_reasoning/answer_incomplete; reason <=180 chars. "
          "Judge semantic correctness and every explicitly requested field. "
          "If an incorrect answer merely omits a supported requested field use answer_incomplete; "
          "use temporal_reasoning only for time/order/version mistakes; otherwise general_reasoning.")
        wire,usage=cached_chat(cfg,[{"role":"system","content":"Blinded paired answer evaluator. Strict JSON only."},
          {"role":"user","content":prompt}],max_tokens=500,timeout=100,
          namespace="hrpa16-qwen-judge-v1",budget_scope=scope["judge_task"],cache_only=False)
        o=decode(wire)
        mapped={}
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
        append(jfile,item);judged[cid]=item
        print("JUDGE",len(judged),"/16",cid,item["baseline_correct"],item["manual_correct"],flush=True)

    rows=[];bc=mc=gain=loss=0;stage_b=Counter();stage_m=Counter()
    groups=defaultdict(lambda:{"n":0,"baseline_correct":0,"manual_correct":0,"gain":0,"loss":0})
    for cid in cases:
        q=suite[cid]["question"];g=gold[cid]["gold_answer"];j=judged[cid]
        # Deterministic output vetoes remain stronger than semantic judge.
        bfields=missing_requested_fields(q,g,base[cid]["answer"])
        mfields=missing_requested_fields(q,g,manual[cid]["answer"])
        bcount=count_contradiction(q,g,base[cid]["answer"]);mcount=count_contradiction(q,g,manual[cid]["answer"])
        bi=inspect_answer(base[cid]["answer"],base[cid].get("finish_reason"))
        mi=inspect_answer(manual[cid]["answer"],manual[cid].get("finish_reason"))
        bok=bool(j["baseline_correct"]) and not bfields.get("missing") and not bcount["contradiction"] and bi["status"]=="valid"
        mok=bool(j["manual_correct"]) and not mfields.get("missing") and not mcount["contradiction"] and mi["status"]=="valid"

        d=delivery[cid]
        btrace={"basis":"deterministic","history_sufficient":True,
                "retrieval_sufficient":d["retrieval_sufficient"],
                "prompt_sufficient":d["prompt_sufficient"]}
        if not bok and d["prompt_sufficient"]:
            ft=("answer_incomplete" if mfields.get("missing") and False else
                ("answer_incomplete" if bfields.get("missing") else j["baseline_failure_type"]))
            if ft=="temporal_reasoning":
                btrace.update(temporal_required=True,temporal_reasoning_correct=False)
            elif ft=="source_conflict":
                btrace.update(source_conflict_present=True,source_conflict_resolved=False)
            elif ft=="answer_incomplete":
                btrace.update(required_output_complete=False)
            else:
                btrace.update(general_reasoning_correct=False)
        mtrace={"basis":"deterministic","history_sufficient":True,
                "retrieval_sufficient":True,"prompt_sufficient":True}
        if not mok:
            ft="answer_incomplete" if mfields.get("missing") else j["manual_failure_type"]
            if ft=="temporal_reasoning":
                mtrace.update(temporal_required=True,temporal_reasoning_correct=False)
            elif ft=="source_conflict":
                mtrace.update(source_conflict_present=True,source_conflict_resolved=False)
            elif ft=="answer_incomplete":
                mtrace.update(required_output_complete=False)
            else:
                mtrace.update(general_reasoning_correct=False)
        bs="none" if bok else classify_delivery_trace(btrace)["stage"]
        ms="none" if mok else classify_delivery_trace(mtrace)["stage"]
        if not bok: stage_b[bs]+=1
        if not mok: stage_m[ms]+=1

        bc+=int(bok);mc+=int(mok);gain+=int(mok and not bok);loss+=int(bok and not mok)
        prior=select[cid]["prior_baseline_failure_stage"]
        group="prior_complete_wrong" if select[cid]["prior_baseline_evidence_complete"] else "prior_evidence_incomplete"
        z=groups[group];z["n"]+=1;z["baseline_correct"]+=int(bok);z["manual_correct"]+=int(mok)
        z["gain"]+=int(mok and not bok);z["loss"]+=int(bok and not mok)
        rows.append({"case_id":cid,"category":suite[cid]["category"],"question":q,"reference":g,
          "prior_failure_stage":prior,"prior_baseline_evidence_complete":select[cid]["prior_baseline_evidence_complete"],
          "baseline_retrieval_sufficient":d["retrieval_sufficient"],
          "baseline_full_required_raw_in_prompt":d["prompt_sufficient"],
          "baseline_correct":bok,"manual_correct":mok,
          "baseline_failure_stage":bs,"manual_failure_stage":ms,
          "manual_evidence_source_refs":evidence[cid]["source_refs"],
          "baseline_answer":base[cid]["answer"],"manual_answer":manual[cid]["answer"],
          "judge_reason":j["reason"]})

    net=gain-loss
    after_full_wrong=16-mc
    supply_rescue=gain
    result={"schema":"xiaoyu-hrpa16-manual-full-evidence-diagnostic-v1",
      "status":"EXPOSED_DEV_DIAGNOSTIC_NOT_FRESH_OR_RELEASE","n":16,
      "baseline_correct":bc,"manual_full_evidence_correct":mc,
      "gains":gain,"losses":loss,"net":net,
      "supply_or_packaging_rescues":supply_rescue,
      "consumption_failures_after_full_evidence":after_full_wrong,
      "baseline_failure_stages_reclassified":dict(stage_b),
      "manual_failure_stages":dict(stage_m),
      "groups":dict(groups),
      "baseline_reused_same_model":True,"manual_full_raw_evidence":True,
      "actual_model_messages_recorded":True,"actual_model_input_sha_bound":True,
      "fresh_capability_credit":False,
      "diagnostic_interpretation":(
        "SUPPLY_DOMINANT" if supply_rescue>=8 and after_full_wrong<=4 else
        "MIXED_SUPPLY_AND_CONSUMPTION" if supply_rescue>=4 and after_full_wrong>=4 else
        "CONSUMPTION_DOMINANT" if after_full_wrong>=8 else
        "WEAK_OR_MIXED_SIGNAL"),
      "rows":rows}
    (P/"DIAGNOSTIC_VERDICT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
        db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
                   (str(P/"MANUAL_ANSWERS.jsonl.seal.json"),time.time(),scope["answer_task"]))
        db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
                   (str(P/"DIAGNOSTIC_VERDICT.json"),time.time(),scope["judge_task"]))
        db.commit()
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
