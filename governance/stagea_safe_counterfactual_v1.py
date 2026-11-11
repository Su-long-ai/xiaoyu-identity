#!/usr/bin/env python3
from __future__ import annotations
import json,re,shutil,tempfile,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
RUNTIME=GOV/"budget50_halumem_dev_runtime_v1"
for p in (str(FROZEN),str(GOV),str(ROOT)):
    if p not in sys.path: sys.path.insert(0,p)

import r52_composition_candidate_v8 as r52
import r52_qa_sufficiency_v7 as qa
from stagea_exact_retrieval_diagnostic import (
    load,stable,gold_similarity,is_gold_unknown,bind_current_session_external_ids
)

QA_INPUTS=RUNTIME/"QA_INPUTS_POST_SEAL.json"
PRED_DIR=RUNTIME/"predictions"
CP_ROOT=RUNTIME/"state_checkpoints"
OUT=GOV/"STAGEA_SAFE_COUNTERFACTUAL_V1.json"

USER_ASSERT_RE=re.compile(
    r"\b(?:"
    r"i(?:'m| am| was| have| had| plan| intend| want| like| love| dislike| hate| "
    r"find| found| feel| felt| learned| realized| appreciate| enjoy| recently| now| "
    r"used to| stopped| started| became| transitioned| set| decided)|"
    r"my\s+"
    r")",
    re.I,
)
USER_CHOICE_RE=re.compile(
    r"\b(?:i\s+(?:plan|intend|will|decided|decide|chose|selected|picked|"
    r"confirmed|booked|reserved|set|stopped|started)|"
    r"my\s+.{1,40}\s+(?:choice|decision|selection|preference)\s+is\b)",
    re.I,
)

def candidate_supports(question,row,relax=False):
    if qa.evidence_supports(question,row):
        return True
    if not relax:
        return False
    text=str(row.get("text") or "")
    auth=str(row.get("authority") or "")
    if auth!="user_source_history" or not text.strip():
        return False

    # Preserve every existing common fail-closed guard.
    if qa._choice_question(question):
        if qa._subject_overlap(question,text)<=0:
            return False
    elif qa._lexical_overlap(question,text)<=0:
        return False
    if qa._nonassertive(text):
        return False
    if qa._possessive_subject_mismatch(question,text):
        return False
    if qa._assistant_action_question(question):
        return False

    low=" ".join(text.casefold().replace("’","'").split())
    if qa._choice_question(question):
        _explicit, unresolved_without_later=qa._resolved_choice_structure(low,auth)
        if unresolved_without_later:
            return False
        return bool(USER_CHOICE_RE.search(low))

    # Only explicit first-person / possessive user assertions. No assistant evidence,
    # no third-person mention, no generic lexical-match-only admission.
    return bool(USER_ASSERT_RE.search(low))

def select_candidate(question,rows,relax=False):
    xs=[r for r in rows if candidate_supports(question,r,relax)]
    if qa._choice_question(question) and xs:
        choice_rank={"user_state":0,"user_history":1,"user_source_history":2,
                     "conversation_history":3,"derived_history":4,"user_conflict":5}
        best=min(choice_rank.get(str(r.get("authority") or ""),9) for r in xs)
        xs=[r for r in xs if choice_rank.get(str(r.get("authority") or ""),9)==best]
        distinct={" ".join(str(r.get("text") or "").casefold().split()) for r in xs}
        if len(distinct)>1:
            return []
        xs.sort(key=lambda r:(-qa._lexical_overlap(question,str(r.get("text") or "")),
                              str(r.get("source_id") or ""),str(r.get("text") or "")))
        return xs
    rank={"user_state":0,"user_history":1,"conversation_history":2,"user_source_history":3,
          "derived_history":4,"user_conflict":5}
    xs.sort(key=lambda r:(rank.get(str(r.get("authority") or ""),9),
                          -qa._lexical_overlap(question,str(r.get("text") or "")),
                          str(r.get("source_id") or ""),str(r.get("text") or "")))
    return xs

def best_goldlike(text,evidence):
    sims=[gold_similarity(text,str(ev.get("memory_content") or "")) for ev in evidence if ev.get("memory_content")]
    if not sims:
        return {"gold_like":False,"evidence_coverage":0.0,"jaccard":0.0,"intersection":0}
    return max(sims,key=lambda x:(x["gold_like"],x["evidence_coverage"],x["jaccard"],x["intersection"]))

def main():
    qa_rows=load(QA_INPUTS)["rows"]
    qa_by_id={x["qa_case_id"]:x for x in qa_rows}
    configs=[(7,False),(14,False),(20,False),(7,True),(14,True),(20,True)]
    stats={f"k{k}_{'relax' if relax else 'base'}":{
        "known_n":0,"unknown_n":0,"answered_known":0,"goldlike_known":0,
        "nongoldlike_known":0,"unknown_false_positive":0,"abstain_known":0,
        "selected_authority":{},"details":[]
    } for k,relax in configs}

    for pp in sorted(PRED_DIR.glob("*.json")):
        pred=load(pp); variant=pred["variant"]; pref=pred["uuid_hash_prefix"]; stream_key=pp.stem
        for local_idx,sess in enumerate(pred.get("sessions") or []):
            global_si=int(sess["session_index"])
            cp=CP_ROOT/stream_key/f"session-{local_idx+1:03d}.sqlite3"
            with tempfile.TemporaryDirectory(prefix="stagea-cf-") as td:
                db=Path(td)/"state.sqlite3"; shutil.copy2(cp,db)
                comp=r52.R52Composition(db,identity_id=f"budget50-dev:{stream_key}")
                try:
                    bind_current_session_external_ids(comp,variant,pref,global_si)
                    for qrec in sess.get("questions") or []:
                        qid=qrec["qa_case_id"]; gold=qa_by_id[qid]; q=qrec["question"]
                        unknown=is_gold_unknown(gold); evidence=gold.get("evidence") or []
                        for k,relax in configs:
                            key=f"k{k}_{'relax' if relax else 'base'}"; st=stats[key]
                            st["unknown_n" if unknown else "known_n"]+=1
                            rr=comp.retrieve(q,limit=k)
                            admitted=rr if qa._assistant_action_question(q) else [
                                x for x in rr if str(x.get("authority") or "")!="conversation_history"
                            ]
                            sel=select_candidate(q,admitted,relax)
                            chosen=sel[0] if sel else None
                            if unknown:
                                if chosen is not None:
                                    st["unknown_false_positive"]+=1
                            else:
                                if chosen is None:
                                    st["abstain_known"]+=1
                                else:
                                    st["answered_known"]+=1
                                    sim=best_goldlike(str(chosen.get("text") or ""),evidence)
                                    if sim["gold_like"]: st["goldlike_known"]+=1
                                    else: st["nongoldlike_known"]+=1
                                    auth=str(chosen.get("authority") or "")
                                    st["selected_authority"][auth]=st["selected_authority"].get(auth,0)+1
                                    st["details"].append({
                                        "qa_case_id":qid,"variant":variant,"k":k,"relax":relax,
                                        "question":q,"reference_answer":gold.get("answer"),
                                        "chosen_text":chosen.get("text"),"authority":auth,
                                        "gold_similarity":sim,
                                    })
                finally:
                    comp.close()

    # Compact summary; details remain for audit.
    out={"schema":"xiaoyu-stagea-safe-counterfactual-v1","provider_calls":0,
         "assistant_history_user_fact_admission":False,"configs":stats}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),"utf-8")
    summary={}
    for k,st in stats.items():
        summary[k]={x:st[x] for x in (
            "known_n","unknown_n","answered_known","goldlike_known","nongoldlike_known",
            "abstain_known","unknown_false_positive","selected_authority"
        )}
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
