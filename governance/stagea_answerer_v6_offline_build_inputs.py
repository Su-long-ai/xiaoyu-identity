#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Stage-A V6 offline counterfactual contexts.

Zero-provider / dev-only.

V6 does NOT consume benchmark reference answers or evidence to construct contexts.
It adds one generic lane to V5:
- cross-history direct-fact retrieval over USER-authored raw dialogue only;
- caller-owned historical upper bound enforced before candidate ranking;
- question-derived field vocabulary (not answer values);
- direct factual questions reserve more context slots for this lane;
- all model-visible authorities remain user_state/user_history/user_source_history.

The two known system-only monthly-income gold items are not special-cased in the
builder; because the exact new value is absent from user dialogue, V6 should still
not fabricate it.
"""
from __future__ import annotations
import hashlib,json,re,sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUN=GOV/"budget50_halumem_dev_runtime_v1"
for p in (str(GOV),str(ROOT)):
    if p not in sys.path: sys.path.insert(0,p)

import stagea_answerer_dev_v4_build_inputs as b4
import stagea_answerer_dev_v5_build_inputs as v5

V5=GOV/"stagea_answerer_v5_full_inputs.json"
QA=RUN/"QA_INPUTS_POST_SEAL.json"
OUT=GOV/"stagea_answerer_v6_offline_inputs.json"

SYSTEM=(
"You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. "
"Never use external facts, guesses, assistant-only claims, or memories outside the supplied list. "
"If the authorized memories do not directly support a reliable answer, output exactly "
"{\"answer\":\"I don't know.\"}. "
"For direct What/Who/Which/current/as-of questions, answer with the shortest directly supported value, "
"name, state, preference, object, or noun phrase. Do not append background unless the question requires it. "
"For numeric current/updated fields, answer only when an explicit user-authored memory states the requested post-update value; never carry an older number forward across an unspecified increase or decrease. For preference-update questions, state the direction of change explicitly when supported (for example, "
"now likes / now dislikes / no longer dislikes), instead of vague words such as reconsidering. "
"For Who questions, preserve the most complete directly supported person name. "
"For historical questions, obey the supplied caller-owned time boundary. "
"For multi-aspect health questions, include every directly supported requested component. "
"For yes/no questions, start with Yes or No and give only the minimum directly supported reason needed. "
"For How/Why/might questions, provide at most two short grounded clauses and do not add optional themes, "
"examples, motivations, or plausible consequences not explicitly supported. "
"Every factual clause must be directly entailed by at least one supplied memory. "
"Return exactly one JSON object with one string field named answer and no other text."
)

STOP={
"the","a","an","is","was","are","were","be","been","to","of","in","on","at","for","and","or",
"her","his","their","she","he","they","what","which","who","how","might","did","does","do",
"has","have","had","as","current","updated","update","jennifer","martin","susan","thompson"
}

FIELD_LEX={
 "income":{"monthly","income","salary","pay","earnings","compensation","raise","financial"},
 "career":{"job","title","career","role","profession","occupation","employment","employed","unemployed","retired","self-employed"},
 "support":{"support","emotional","friend","stressful","challenging","grounded"},
 "beverage":{"beverage","drink","diet","coffee","caffeine","tea","water","eliminate","cutting","avoid"},
 "book":{"book","books","reading","literature","self-help","discover","found","stress","management"},
 "reading_pref":{"reading","preference","books","novels","like","dislike","relax"},
 "travel_pref":{"travel","preference","transport","transportation","transit","mobility","reliable","trip","trips"},
 "clothing_pref":{"clothing","attire","dress","formal","suit","suits","professional","preference"},
 "health":{"health","physical","mental","symptom","symptoms","stress","stressed","anxiety","bloating","fatigue","wellness"},
 "music":{"music","genre","genres","track","tracks","routine","emotional","well-being"},
 "film":{"film","films","movie","movies","genre","drama","appreciation"},
 "workshop":{"workshop","workshops","strategy","strategies","wellness","health","mindfulness","relaxation"},
 "decor":{"decor","home","environment","tranquil","calming","fish","relaxation"},
}

def load(p): return json.loads(Path(p).read_text("utf-8"))

def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def toks(s):
    return {x for x in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?",str(s).casefold()) if len(x)>1 and x not in STOP}

def fields(question):
    q=str(question).casefold()
    out=[]
    if "income" in q or "salary" in q: out.append("income")
    if any(z in q for z in ("job title","career status","employment","profession","occupation","retire")): out.append("career")
    if "emotional support" in q or ("who" in q and "support" in q): out.append("support")
    if any(z in q for z in ("beverage","drink","diet")): out.append("beverage")
    if "book" in q or "reading" in q: out.append("book")
    if "reading preference" in q: out.append("reading_pref")
    if "travel" in q: out.append("travel_pref")
    if "clothing" in q or "attire" in q: out.append("clothing_pref")
    if any(z in q for z in ("health","symptom","stress","wellness")): out.append("health")
    if "music" in q or "genre" in q: out.append("music")
    if "film" in q or "movie" in q: out.append("film")
    if "workshop" in q or "workshops" in q: out.append("workshop")
    if "decor" in q or ("home" in q and "fish" in q): out.append("decor")
    return list(dict.fromkeys(out))

def qkeys(question):
    keys=toks(question)
    fs=fields(question)
    for f in fs: keys.update(FIELD_LEX[f])
    return keys,fs

def bound_ok(question,timestamp):
    b=b4.question_upper_bound(question)
    if b is None:return True
    ts=b4.parse_dt(timestamp)
    if ts is None:return False
    d=ts.date()
    return d < b["date"] if b["relation"]=="before" else d <= b["date"]

def direct_question(question):
    q=str(question).strip().casefold()
    return bool(re.match(r"^(what|who|which)\b",q)) or " as of " in q or "updated to" in q

def candidate_score(text,question,keys,fs,session_index,current_session):
    tt=toks(text); overlap=len(tt & keys)
    if overlap==0:return 0
    low=str(text).casefold()
    score=overlap*5
    # Generic field-shape bonuses. These do not contain answer values.
    if "income" in fs and any(z in low for z in ("monthly income","salary","pay","earnings","salary increase")): score+=18
    if "career" in fs and any(z in low for z in ("my role as","i am currently","i'm retired","i am retired","career as","working as")): score+=16
    if "support" in fs and "support" in low and ("friend" in low or "helping me" in low or "grounded" in low): score+=16
    if "beverage" in fs and any(z in low for z in ("coffee","drink","beverage","caffeine","diet")): score+=14
    if "book" in fs and "book" in low: score+=14
    if "reading_pref" in fs and ("novel" in low or "reading" in low) and any(z in low for z in ("dislike","like","preference","relax")): score+=14
    if "travel_pref" in fs and any(z in low for z in ("travel","transport","ride-sharing","reliable")): score+=14
    if "clothing_pref" in fs and any(z in low for z in ("attire","suit","clothing")): score+=14
    if "health" in fs and any(z in low for z in ("health","stress","anxiety","bloating","fatigue","symptom")): score+=12
    if "music" in fs and any(z in low for z in ("music","track","genre","techno")): score+=12
    if "film" in fs and any(z in low for z in ("film","movie","drama")): score+=12
    if "workshop" in fs and "workshop" in low: score+=12
    if "decor" in fs and any(z in low for z in ("home","decor","environment","fish","tranquil")): score+=12
    # Prefer newer evidence within the legal time window for current/as-of/update questions,
    # but relevance remains dominant.
    if direct_question(question):
        score += max(0,min(8,session_index))
    if session_index==current_session: score+=2
    return score

def cross_history_pack(qa):
    rec=b4.record(qa["variant"],qa["uuid"])
    keys,fs=qkeys(qa["question"])
    qlow=str(qa["question"]).casefold()
    # Event-relative bounds without an explicit date are not safely orderable by the current caller-owned temporal parser.
    # Fail closed rather than importing evidence from after the referenced event.
    if "before retirement" in qlow or "after retirement" in qlow:
        return [],fs
    if not fs:
        return [],fs
    if not (direct_question(qa["question"]) or "health status" in qlow):
        return [],fs
    current=int(qa["session_index"])
    candidates=[]
    for si,sess in enumerate(rec.get("sessions") or []):
        for ti,turn in enumerate(sess.get("dialogue") or []):
            if turn.get("role")!="user":continue
            if not bound_ok(qa["question"],turn.get("timestamp")):continue
            text=str(turn.get("content") or "")
            sc=candidate_score(text,qa["question"],keys,fs,si,current)
            if sc<=0:continue
            ts=b4.parse_dt(turn.get("timestamp"))
            m=re.match(r"hm-([ml])-q-([0-9a-f]+)-",qa["qa_case_id"])
            candidates.append({
                "authority":"user_source_history",
                "timestamp":ts.isoformat() if ts else None,
                "effective_at":None,
                "source_id":f"hm:{m.group(1)}:{m.group(2)}:s{si}:t{ti}",
                "channel":"cross_history_direct_fact",
                "text":text,
                "_score":sc,
                "_session":si,
            })
    candidates.sort(key=lambda x:(-x["_score"],-x["_session"],x["source_id"]))
    return candidates,fs

def main():
    base=load(V5)
    qas=load(QA)["rows"]
    qm={x["qa_case_id"]:x for x in qas}
    rows=[]
    for old in base["rows"]:
        qa=qm[old["qa_case_id"]]
        direct,fs=cross_history_pack(qa)
        # Reserve more direct-fact slots for direct field questions; composition questions
        # retain more V5 context.
        quota=10 if direct_question(qa["question"]) else 6
        chosen=[];seen=set()
        def add(m):
            k=(m.get("authority"),m.get("source_id")," ".join(str(m.get("text","")).split()))
            if k in seen:return False
            seen.add(k); mm=dict(m); mm.pop("_score",None); mm.pop("_session",None); chosen.append(mm); return True
        n=0
        for m in direct:
            if add(m): n+=1
            if n>=quota:break
        for m in old["authorized_memories"]:
            if len(chosen)>=20:break
            add(m)
        # Backfill remaining direct candidates only if there is room.
        for m in direct:
            if len(chosen)>=20:break
            add(m)
        lines=[]
        for i,m in enumerate(chosen,1):
            md=f"authority={m['authority']}"
            if m.get("timestamp"):md+=f" timestamp={m['timestamp']}"
            lines.append(f"[{i}] {md}\n{m['text']}")
        messages=[
            {"role":"system","content":SYSTEM},
            {"role":"user","content":"AUTHORIZED MEMORIES:\n"+("\n\n".join(lines) if lines else "(none)")+"\n\nQUESTION:\n"+qa["question"]}
        ]
        rows.append({
            **{k:v for k,v in old.items() if k not in ("case_id","authorized_memories","authorized_memory_count","messages","request_messages_sha256","selection_prior_label")},
            "case_id":"ansv6off-"+hashlib.sha256(old["qa_case_id"].encode()).hexdigest()[:16],
            "selection_group":"offline_counterfactual",
            "selection_prior_label":None,
            "authorized_memories":chosen,
            "authorized_memory_count":len(chosen),
            "retrieval_meta":{**old.get("retrieval_meta",{}),"v6_fields":fs,"cross_history_candidate_n":len(direct),"cross_history_quota":quota},
            "messages":messages,
            "request_messages_sha256":stable(messages),
        })
    out={
        "schema":"xiaoyu-stagea-answerer-v6-offline-inputs-v1",
        "status":"OFFLINE_COUNTERFACTUAL_ONLY",
        "case_count":len(rows),
        "uniform_algorithm_for_all_qa":True,
        "uses_gold_for_construction":False,
        "assistant_authority_allowed":False,
        "context_cap":20,
        "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({
        "case_count":len(rows),
        "sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "direct_questions":sum(direct_question(x["question"]) for x in rows),
        "cross_history_used":sum(any(m.get("channel")=="cross_history_direct_fact" for m in x["authorized_memories"]) for x in rows),
        "max_context":max(x["authorized_memory_count"] for x in rows),
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
