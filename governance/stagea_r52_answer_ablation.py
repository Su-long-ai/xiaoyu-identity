#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json,re,shutil,sys,tempfile
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
RT=GOV/"budget50_halumem_dev_runtime_v1"
for p in (str(FROZEN),str(GOV),str(ROOT)):
    if p not in sys.path: sys.path.insert(0,p)

import r52_composition_candidate_v8 as v8
import r52_composition_candidate_v7 as v7
import r52_candidate_v7 as ref
import r52_qa_sufficiency_v7 as qa
import stagea_exact_retrieval_diagnostic as d1

QA=d1.load(RT/"QA_INPUTS_POST_SEAL.json")["rows"]
QBY={x["qa_case_id"]:x for x in QA}
PRE=d1.load(GOV/"STAGEA_PREWINDOW_EVIDENCE_AUDIT.json")
PREBY={x["qa_case_id"]:x for x in PRE["rows"]}

RANK={"user_state":0,"user_history":1,"user_source_history":2,"derived_history":3,
      "user_conflict":4,"conversation_history":5}

def relevance(query,row):
    qt=set(ref._query_tokens(query)); tt=set(ref._query_tokens(str(row.get("text") or "")))
    return len(qt&tt)

def collect_wide(comp,query):
    rows=[];seen=set()
    def add(item):
        key=(item.get("text"),item.get("authority"),item.get("source_id"))
        if key in seen:return
        seen.add(key);rows.append(dict(item))
    for x in v7.R52Composition.retrieve(comp,query,limit=40):
        add(x)
    by_sid={x["source_message_id"]:x for x in comp.store.source_history()}
    by_conv_seq={(str(x["conversation_id"]),int(x["message_seq"])):x for x in comp.store.source_history()}
    def add_src(src,channel):
        if not src:return
        auth="conversation_history" if src["source_role"]=="assistant" else "user_source_history"
        add({"text":src["source_text"],"authority":auth,
             "source_id":comp._external_sid(src["source_message_id"]),
             "channel":channel,"source_role":src["source_role"],
             "effective_at":int(src["effective_at"])})
    for hit in ref._raw_source_hits(comp.store,query,36):
        src=by_sid.get(hit["source_message_id"]);add_src(src,"raw_source_hit")
        if src:
            conv=str(src["conversation_id"]);seq=int(src["message_seq"])
            add_src(by_conv_seq.get((conv,seq-1)),"adjacent_turn")
            add_src(by_conv_seq.get((conv,seq+1)),"adjacent_turn")
    return rows

def retrieve_variant(comp,question,name):
    if name=="baseline":
        return comp.retrieve(question,limit=7)
    rows=collect_wide(comp,question)
    if name=="wide_authority":
        rows.sort(key=lambda x:(RANK.get(str(x.get("authority") or ""),9),
                                -relevance(question,x),str(x.get("source_id") or ""),str(x.get("text") or "")))
    else:
        rows.sort(key=lambda x:(-relevance(question,x),
                                RANK.get(str(x.get("authority") or ""),9),
                                str(x.get("source_id") or ""),str(x.get("text") or "")))
    return rows[:12]

FIRST_PERSON_STRONG=re.compile(
    r"^\s*(?:i\b|i['’]m\b|i['’]ve\b|i['’]d\b|i['’]ll\b|my\b|we\b|we['’]re\b|we['’]ve\b)",
    re.I,
)
CHANGE_MARKERS=re.compile(
    r"\b(?:no longer|used to|reconsider|reconsidered|starting to|started to|began to|"
    r"plan to|planning to|want to|decided|decide|changed|change|switch|switched|"
    r"prefer|preference|like|dislike|incorporate|include|eliminate|avoid|find|found)\b",
    re.I,
)

def relaxed_raw_support(question,row,allow_choice):
    text=str(row.get("text") or ""); auth=str(row.get("authority") or "")
    if auth!="user_source_history":return False
    if not FIRST_PERSON_STRONG.search(text):return False
    if text.strip().endswith("?"):return False
    if qa._nonassertive(text) or qa._possessive_subject_mismatch(question,text):return False
    choice=qa._choice_question(question)
    if choice:
        if not allow_choice:return False
        if qa._subject_overlap(question,text)<=0:return False
        return bool(CHANGE_MARKERS.search(text))
    return qa._lexical_overlap(question,text)>0

def select_variant(question,rr,name):
    admitted=rr if qa._assistant_action_question(question) else [
        r for r in rr if str(r.get("authority") or "")!="conversation_history"
    ]
    base=qa.select_supported(question,admitted)
    if base or name not in ("wide_rel_raw","wide_rel_raw_choice"):
        return base
    relaxed=[r for r in admitted if relaxed_raw_support(
        question,r,allow_choice=(name=="wide_rel_raw_choice")
    )]
    relaxed.sort(key=lambda x:(-relevance(question,x),RANK.get(str(x.get("authority") or ""),9),
                               str(x.get("source_id") or ""),str(x.get("text") or "")))
    return relaxed

def is_goldlike(text,evidence):
    return any(d1.gold_similarity(str(text or ""),str(e.get("memory_content") or ""))["gold_like"]
               for e in evidence)

def main():
    variants=["baseline","wide_authority","wide_relevance","wide_rel_raw","wide_rel_raw_choice"]
    metrics={v:{"evidence_n":0,"unknown_n":0,"answered_evidence":0,"goldlike_retrieved":0,
                "goldlike_supported":0,"first_supported_goldlike":0,"unknown_abstain":0,
                "unknown_false_answer":0,"reachable_evidence_n":0,"reachable_first_supported_goldlike":0,
                "by_variant":defaultdict(lambda:defaultdict(int))} for v in variants}
    cases=[]

    for pp in sorted((RT/"predictions").glob("*.json")):
        pred=d1.load(pp); stream=pp.stem; variant=pred["variant"];pref=pred["uuid_hash_prefix"]
        for li,sess in enumerate(pred["sessions"]):
            cp=RT/"state_checkpoints"/stream/f"session-{li+1:03d}.sqlite3"
            with tempfile.TemporaryDirectory(prefix="r52-ablate-") as td:
                db=Path(td)/"state.sqlite3";shutil.copy2(cp,db)
                comp=v8.R52Composition(db,identity_id="ablate:"+stream)
                try:
                    d1.bind_current_session_external_ids(comp,variant,pref,int(sess["session_index"]))
                    for qrec in sess.get("questions") or []:
                        q=QBY[qrec["qa_case_id"]]; evidence=q.get("evidence") or []
                        unknown=d1.is_gold_unknown(q)
                        prewindow=bool(PREBY[q["qa_case_id"]].get("all_evidence_pre_window_only"))
                        case={"qa_case_id":q["qa_case_id"],"variant":variant,"unknown":unknown,
                              "prewindow_only":prewindow,"results":{}}
                        for name in variants:
                            rr=retrieve_variant(comp,q["question"],name)
                            sup=select_variant(q["question"],rr,name)
                            m=metrics[name]; bv=m["by_variant"][variant]
                            if unknown:
                                m["unknown_n"]+=1;bv["unknown_n"]+=1
                                if sup:m["unknown_false_answer"]+=1;bv["unknown_false_answer"]+=1
                                else:m["unknown_abstain"]+=1;bv["unknown_abstain"]+=1
                            else:
                                m["evidence_n"]+=1;bv["evidence_n"]+=1
                                if not prewindow:m["reachable_evidence_n"]+=1;bv["reachable_evidence_n"]+=1
                                if sup:m["answered_evidence"]+=1;bv["answered_evidence"]+=1
                                gr=any(is_goldlike(r.get("text"),evidence) for r in rr)
                                gs=any(is_goldlike(r.get("text"),evidence) for r in sup)
                                fg=bool(sup and is_goldlike(sup[0].get("text"),evidence))
                                if gr:m["goldlike_retrieved"]+=1;bv["goldlike_retrieved"]+=1
                                if gs:m["goldlike_supported"]+=1;bv["goldlike_supported"]+=1
                                if fg:
                                    m["first_supported_goldlike"]+=1;bv["first_supported_goldlike"]+=1
                                    if not prewindow:m["reachable_first_supported_goldlike"]+=1;bv["reachable_first_supported_goldlike"]+=1
                            case["results"][name]={
                                "retrieved_n":len(rr),"supported_n":len(sup),
                                "first_supported":sup[0]["text"] if sup else None,
                                "first_supported_authority":sup[0].get("authority") if sup else None,
                                "first_supported_goldlike":bool(sup and evidence and is_goldlike(sup[0].get("text"),evidence)),
                            }
                        cases.append(case)
                finally:comp.close()

    serial={}
    for name,m in metrics.items():
        x={k:v for k,v in m.items() if k!="by_variant"}
        x["by_variant"]={vk:dict(vv) for vk,vv in m["by_variant"].items()}
        if x["reachable_evidence_n"]:
            x["reachable_first_supported_goldlike_rate"]=x["reachable_first_supported_goldlike"]/x["reachable_evidence_n"]
        if x["evidence_n"]:
            x["first_supported_goldlike_rate_all_evidence"]=x["first_supported_goldlike"]/x["evidence_n"]
        serial[name]=x
    out={"schema":"xiaoyu-stagea-r52-answer-ablation-v1","metrics":serial,"cases":cases}
    (GOV/"STAGEA_R52_ANSWER_ABLATION.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps({"metrics":serial},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
