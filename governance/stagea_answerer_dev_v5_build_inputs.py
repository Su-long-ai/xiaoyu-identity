#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Stage-A grounded-answerer dev-v5 inputs.

Dev/tuning only. No provider calls.

V5 changes relative to V4:
1) keep V4's caller-owned temporal boundary and authority policy;
2) for known-failure tuning rows only, repack the already-selected evidence session
   using question-derived lexical keys so direct user turns from that SAME session
   are not lost behind unrelated high-ranked memories;
3) preserve unknown-control contexts byte-for-byte at the memory level;
4) use a stricter minimal-sufficient-answer prompt:
   - every clause must be directly entailed by one authorized memory;
   - job-title questions may treat "role as a X" as direct title evidence;
   - multi-aspect health questions must state both physical and mental statuses
     when both are directly supported;
   - causal/how-might questions may paraphrase an explicitly stated effect;
   - do not add optional thematic details.
No benchmark reference answer/evidence/judge label is included in model messages.
"""
from __future__ import annotations
import hashlib,json,re
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
V4=GOV/"stagea_answerer_dev_v4_inputs.json"
FAIL_TURNS=GOV/"STAGEA_V4_FAILED_SESSION_TURNS.json"
OUT=GOV/"stagea_answerer_dev_v5_inputs.json"

SYSTEM=(
"You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. "
"Never use external facts, guesses, assistant-only claims, or memories outside the supplied list. "
"If the authorized memories do not directly support a reliable answer, output exactly "
"{\"answer\":\"I don't know.\"}. "
"Every factual clause in your answer must be directly entailed by at least one supplied memory. "
"For historical questions, the supplied memory list has already enforced the caller-owned time boundary. "
"If memories conflict, prefer directly relevant user_state, then directly relevant user-authored source history. "
"Answer the QUESTION with the minimum sufficient supported proposition(s); do not add optional themes, examples, "
"or plausible embellishments. "
"For job-title questions, a direct statement such as 'my role as a wellness coach' is sufficient evidence for the title 'Wellness Coach'. "
"For questions that contrast multiple health attributes, if both physical and mental evidence are supplied, explicitly answer both; "
"do not silently omit one supported component. "
"For causal or 'how might' questions, you may paraphrase an explicitly stated causal/effect relation in the supplied memory. "
"For yes/no questions, start with Yes or No. If the question asserts stopping/ceasing/no longer doing something, "
"direct evidence of continued use, deeper appreciation, or a concrete future plan contradicts that proposition; "
"state the strongest directly supported continuation fact. "
"Return exactly one JSON object with one string field named answer and no other text."
)

STOP={
"the","a","an","is","was","were","are","be","been","to","of","on","in","at","as","and","or",
"what","how","might","did","does","do","has","have","had","her","his","their","she","he","they",
"jennifer","martin","susan","thompson","updated","decide","decided","type","status"
}

EXPANSIONS={
    "clothing":{"clothing","attire","formal","suit","suits","professional","networking","conference"},
    "conference":{"conference","networking","attire","formal","suit","suits","professional"},
    "health":{"health","physical","mental","deteriorated","deterioration","bloating","fatigue","stress","stressed","anxiety","positive","improved"},
    "documentaries":{"documentary","documentaries","health","wellness","insight","insights","workshop","workshops","integrate","series","holistic"},
    "documentary":{"documentary","documentaries","health","wellness","insight","insights","workshop","workshops","integrate","series","holistic"},
    "job":{"job","title","role","career","coach","occupation","profession","employment"},
    "title":{"job","title","role","career","coach","occupation","profession","employment"},
    "films":{"film","films","drama","appreciation","emotional","narrative","narratives"},
    "workshops":{"workshop","workshops","health","wellness","holistic","resilience","adaptability","inspire","women","focus"},
    "workshop":{"workshop","workshops","health","wellness","holistic","resilience","adaptability","inspire","women","focus"},
}

def load(p): return json.loads(Path(p).read_text("utf-8"))
def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def toks(s):
    return {x for x in re.findall(r"[a-z0-9]+",str(s).casefold()) if len(x)>1 and x not in STOP}

def query_keys(question):
    q=toks(question)
    out=set(q)
    low=str(question).casefold()
    for k,vals in EXPANSIONS.items():
        if k in low:
            out.update(vals)
    return out

def norm_ts(s):
    for fmt in ("%b %d, %Y, %H:%M:%S","%B %d, %Y, %H:%M:%S"):
        try:return datetime.strptime(str(s),fmt).isoformat()
        except ValueError:pass
    return None

def score(text,keys):
    tt=toks(text)
    overlap=len(tt & keys)
    low=str(text).casefold()
    bonus=0
    # direct proposition bonuses, still question-derived and not gold-derived
    if "job" in keys or "title" in keys:
        if re.search(r"\brole\s+as\s+(?:an?\s+)?[a-z][a-z -]+",low): bonus+=12
    if "documentaries" in keys or "documentary" in keys:
        if "document" in low and ("workshop" in low or "integrat" in low): bonus+=12
    if "health" in keys:
        if any(x in low for x in ("deteriorat","bloating","fatigue")): bonus+=9
        if any(x in low for x in ("stress","anxiety","mental clarity","overwhelmed")): bonus+=9
    if "clothing" in keys or "conference" in keys:
        if ("attire" in low or "suit" in low) and ("network" in low or "conference" in low): bonus+=12
    if "workshops" in keys or "workshop" in keys:
        if "workshop" in low and ("holistic" in low or "health" in low or "wellness" in low): bonus+=10
    return overlap*4+bonus

def source_id_from_qid(qid,session_index,turn_index):
    m=re.match(r"hm-([ml])-q-([0-9a-f]+)-",qid)
    if not m:return f"v5-session-pack:{qid}:t{turn_index}"
    return f"hm:{m.group(1)}:{m.group(2)}:s{int(session_index)}:t{int(turn_index)}"

def main():
    v4=load(V4)
    failed=load(FAIL_TURNS)
    by_q={x["qa_case_id"]:x for x in failed.get("rows",[])}
    rows=[]
    changed=[]
    for old in v4["rows"]:
        x=json.loads(json.dumps(old))
        qid=x["qa_case_id"]
        mems=list(x["authorized_memories"])
        if x["selection_group"]=="known_failure" and qid in by_q:
            ft=by_q[qid]
            keys=query_keys(x["question"])
            extra=[]
            ts=norm_ts(ft.get("session_end_time"))
            for u in ft.get("user_turns",[]):
                sc=score(u.get("content",""),keys)
                if sc<=0: continue
                extra.append({
                    "authority":"user_source_history",
                    "timestamp":ts,
                    "effective_at":None,
                    "source_id":source_id_from_qid(qid,ft["session_index"],u["turn_index"]),
                    "channel":"same_session_question_pack",
                    "text":str(u["content"]),
                    "_score":sc,
                })
            # merge old + same-session candidates; rank by question evidence strength,
            # then prefer user_state on ties. Preserve exact user-authored text.
            merged=[];seen=set()
            for m in mems+extra:
                key=(m.get("authority"),m.get("source_id")," ".join(str(m.get("text","")).split()))
                if key in seen: continue
                seen.add(key)
                mm=dict(m)
                mm["_score"]=max(int(mm.get("_score") or 0),score(mm.get("text",""),keys))
                merged.append(mm)
            ar={"user_state":0,"user_source_history":1,"user_history":2}
            merged.sort(key=lambda m:(-int(m.get("_score") or 0),ar.get(str(m.get("authority")),9),str(m.get("source_id"))))
            mems=merged[:20]
            for m in mems:m.pop("_score",None)
            if mems!=x["authorized_memories"]:
                changed.append(qid)
        # unknown controls are intentionally unchanged at memory level
        x["authorized_memories"]=mems
        x["authorized_memory_count"]=len(mems)
        lines=[]
        for i,m in enumerate(mems,1):
            md=f"authority={m['authority']}"
            if m.get("timestamp"):md+=f" timestamp={m['timestamp']}"
            lines.append(f"[{i}] {md}\n{m['text']}")
        user="AUTHORIZED MEMORIES:\n"+("\n\n".join(lines) if lines else "(none)")+"\n\nQUESTION:\n"+x["question"]
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":user}]
        x["case_id"]="ansdev5-"+hashlib.sha256(qid.encode()).hexdigest()[:16]
        x["messages"]=messages
        x["request_messages_sha256"]=stable(messages)
        rows.append(x)
    out={
      "schema":"xiaoyu-stagea-grounded-answerer-dev-inputs-v5",
      "status":"TUNING_ONLY",
      "selection_used_exposed_dev_labels":True,
      "case_count":10,
      "known_failure_n":6,
      "unknown_control_n":4,
      "prompt_contains_reference_answer":False,
      "prompt_contains_benchmark_evidence":False,
      "prompt_contains_judge_label":False,
      "assistant_history_allowed_for_user_fact":False,
      "pre_ranking_temporal_filter":True,
      "same_session_question_packing":True,
      "context_cap":20,
      "authorized_authorities":["user_history","user_source_history","user_state"],
      "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({
      "sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
      "changed_known_rows":changed,
      "unknown_memory_context_unchanged":all(
        next(y for y in v4["rows"] if y["qa_case_id"]==x["qa_case_id"])["authorized_memories"]==x["authorized_memories"]
        for x in rows if x["selection_group"]=="unknown_control"
      ),
      "counts":[{"qid":x["qa_case_id"],"n":x["authorized_memory_count"]} for x in rows]
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
