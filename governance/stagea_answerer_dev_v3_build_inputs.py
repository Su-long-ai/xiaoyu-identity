#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Stage-A grounded-answerer dev-v3 inputs.

Dev-only, zero-provider context construction over already-exposed Stage-A cases.

Key properties:
- caller-owned historical upper-bound is applied to source history BEFORE ranking;
- accepted R52 v8 store/claims and raw-user FTS remain the retrieval substrate;
- authority remains user_state/user_history/user_source_history only;
- narrow question-derived facets are allowed only for field-head mismatch:
  job title -> role/career/employment/occupation/profession;
  health status -> physical and mental health facets;
- context is deduplicated and capped at 20;
- model messages contain no benchmark reference answer/evidence/judge label.
"""
from __future__ import annotations
import hashlib,json,re,shutil,sys,tempfile
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUN=GOV/"budget50_halumem_dev_runtime_v1"
EXT=ROOT/"external"/"halumem_dataset_cache"
R52W=GOV/"workspaces"/"fish-6534847e38ed48b6"
for p in (str(R52W),str(GOV),str(ROOT)):
    if p not in sys.path:sys.path.insert(0,p)

import r52_composition_candidate_v8 as r52
import r52_candidate_v7 as ref
from stagea_exact_retrieval_diagnostic import bind_current_session_external_ids

ACCEPTED_R52="57f7a955f724c99c8c25451801681124b2b58b7348d0d02e8a921845590d4e71"
if hashlib.sha256((R52W/"r52_composition_candidate_v8.py").read_bytes()).hexdigest()!=ACCEPTED_R52:
    raise RuntimeError("R52 v8 byte drift")

ALLOWED={"user_state","user_history","user_source_history"}
OUT=GOV/"stagea_answerer_dev_v3_inputs.json"
DATE_RE=re.compile(
    r"(?i)\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{1,2}),\s*(\d{4})\b"
)
FILES={"m":EXT/"HaluMem-Medium.jsonl","l":EXT/"HaluMem-Long.jsonl"}
_REC={}

SYSTEM=(
"You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. "
"Never use external facts, guesses, assistant-only claims, or memories outside the supplied list. "
"If the authorized memories do not directly support a reliable answer, output exactly "
"{\"answer\":\"I don't know.\"}. "
"For historical questions, the supplied memory list has already enforced the caller-owned time boundary. "
"If memories conflict, prefer the most directly relevant user_state, then the most recent directly relevant "
"user-authored evidence valid for the question time. "
"If the question asks about multiple attributes or contrasts multiple states, answer EVERY requested component "
"that is directly supported; do not silently omit one supported component. "
"Prefer explicit noun phrases and propositions from the supplied memories over thematic synthesis. "
"Answer the QUESTION directly and concisely, normally within 18 words. "
"For yes/no questions, start with Yes or No and include all supported facts needed to resolve the contrast. "
"Return exactly one JSON object with one string field named answer and no other text."
)

def load(p): return json.loads(Path(p).read_text("utf-8"))
def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def parse_dt(s):
    for fmt in ("%b %d, %Y, %H:%M:%S","%B %d, %Y, %H:%M:%S"):
        try:return datetime.strptime(str(s),fmt)
        except ValueError:pass
    return None

def question_upper_bound(question):
    q=str(question)
    m=DATE_RE.search(q)
    if not m:return None
    # "after DATE" is a lower bound, not an as-of upper bound.
    before=q[:m.start()].casefold()
    tail=before[-32:]
    if re.search(r"\bafter\s*$",tail):
        return None
    relation="before" if re.search(r"\bbefore\s*$",tail) else "at_or_before"
    # Explicit as-of/on/by and ordinary dated status questions are bounded at that date.
    try:
        dt=datetime.strptime(m.group(0),"%b %d, %Y")
    except ValueError:
        dt=datetime.strptime(m.group(0),"%B %d, %Y")
    return {"date":dt.date(),"relation":relation,"text":m.group(0)}

def record(variant,uuid):
    key=(variant,uuid)
    if key in _REC:return _REC[key]
    with FILES[variant].open("r",encoding="utf-8") as f:
        for line in f:
            if uuid not in line:continue
            o=json.loads(line)
            if str(o.get("uuid"))==uuid:
                _REC[key]=o;return o
    raise KeyError(key)

def src_session(src):
    m=re.search(r":session:(\d+)$",str(src.get("conversation_id") or ""))
    return int(m.group(1)) if m else None

def source_time(rec,src):
    si=src_session(src)
    if si is None or si>=len(rec["sessions"]):return None
    return parse_dt(rec["sessions"][si].get("end_time"))

def eligible_for_bound(rec,src,bound):
    if bound is None:return True
    ts=source_time(rec,src)
    if ts is None:return False
    day=ts.date()
    return day < bound["date"] if bound["relation"]=="before" else day <= bound["date"]

def facet_queries(question):
    q=str(question).casefold()
    out=[]
    if re.search(r"\bjob\s+title\b|\boccupation\b|\bprofession\b|\bemployment\b",q):
        out.append(("job_head","job title role career employment occupation profession",12))
    if "health status" in q or ("health" in q and ("improved" in q or "positive" in q)):
        out.extend([
            ("health_physical","physical health deterioration deteriorated symptoms bloating fatigue",6),
            ("health_mental","mental health stress anxiety overwhelmed mental clarity",6),
        ])
    return out

def build_context(qa,pred,sess,cp):
    rec=record(qa["variant"],qa["uuid"])
    bound=question_upper_bound(qa["question"])
    with tempfile.TemporaryDirectory(prefix="stagea-answerer-v3-") as td:
        db=Path(td)/"state.sqlite3";shutil.copy2(cp,db)
        comp=r52.R52Composition(db,identity_id="answerer-v3:"+pred["uuid_hash_prefix"])
        try:
            bind_current_session_external_ids(
                comp,qa["variant"],pred["uuid_hash_prefix"],int(sess["session_index"])
            )
            sources=[dict(x) for x in comp.store.source_history()]
            by_conv_seq={(str(x["conversation_id"]),int(x["message_seq"])):x for x in sources}
            eligible={
                str(x["source_message_id"]):x
                for x in sources if eligible_for_bound(rec,x,bound)
            }

            comp.store.db.execute("DROP TABLE IF EXISTS temp.stagea_answerer_v3_fts")
            comp.store.db.execute("""CREATE VIRTUAL TABLE temp.stagea_answerer_v3_fts USING fts5(
                source_message_id UNINDEXED,source_text,tokenize='unicode61')""")
            comp.store.db.executemany(
                "INSERT INTO temp.stagea_answerer_v3_fts VALUES(?,?)",
                [(sid,s["source_text"]) for sid,s in eligible.items()]
            )

            def gather(query):
                rows=[];seen=set()
                def add(text,authority,internal_sid,channel):
                    authority=str(authority or "")
                    if authority not in ALLOWED or not str(text).strip():return
                    src=eligible.get(str(internal_sid))
                    if src is None or src.get("source_role") != "user":return
                    ext=comp._external_sid(str(internal_sid))
                    key=(authority,ext," ".join(str(text).split()))
                    if key in seen:return
                    seen.add(key)
                    ts=source_time(rec,src)
                    rows.append({
                        "authority":authority,
                        "timestamp":ts.isoformat() if ts else None,
                        "effective_at":src.get("effective_at"),
                        "source_id":ext,
                        "channel":channel,
                        "text":str(text),
                    })

                for rr in comp.store.recall(query,mode="history",limit=500):
                    sid=str(rr["source_message_id"])
                    if sid in eligible:
                        add(rr["text"],rr.get("authority"),sid,"claim")

                toks=ref._query_tokens(query)
                if toks:
                    fq=" OR ".join('"'+x.replace('"','')+'"' for x in toks)
                    hits=[
                        dict(x) for x in comp.store.db.execute(
                            """SELECT source_message_id,source_text,
                                      bm25(stagea_answerer_v3_fts) score
                               FROM temp.stagea_answerer_v3_fts
                               WHERE stagea_answerer_v3_fts MATCH ?
                               ORDER BY score LIMIT 120""",(fq,)
                        ).fetchall()
                    ]
                    for hit in hits:
                        sid=str(hit["source_message_id"]);src=eligible.get(sid)
                        if not src or src["source_role"]!="user":continue
                        add(src["source_text"],"user_source_history",sid,"raw_source_hit")
                        conv=str(src["conversation_id"]);seq=int(src["message_seq"])
                        for nbr in (
                            by_conv_seq.get((conv,seq-1)),
                            by_conv_seq.get((conv,seq+1)),
                        ):
                            if (
                                nbr and nbr["source_role"]=="user"
                                and str(nbr["source_message_id"]) in eligible
                            ):
                                add(
                                    nbr["source_text"],"user_source_history",
                                    str(nbr["source_message_id"]),"adjacent_turn"
                                )

                ar={"user_state":0,"user_history":1,"user_source_history":2}
                qt=set(ref._query_tokens(query))
                rows.sort(key=lambda x:(
                    ar.get(x["authority"],9),
                    -len(qt & set(ref._query_tokens(x["text"]))),
                    0 if x["channel"]=="raw_source_hit" else 1,
                    str(x["source_id"]),x["text"]
                ))
                return rows

            facets=facet_queries(qa["question"])
            pieces=[("original",gather(qa["question"]),8 if facets else 20)]
            pieces.extend((label,gather(query),quota) for label,query,quota in facets)
            out=[];seen=set();contrib={}
            for label,rows,quota in pieces:
                n=0
                for x in rows:
                    k=(x["authority"],x["source_id"],x["text"])
                    if k in seen:continue
                    seen.add(k);out.append(x);n+=1
                    if n>=quota or len(out)>=20:break
                contrib[label]=n
                if len(out)>=20:break
            if len(out)<20:
                for label,rows,_ in pieces:
                    for x in rows:
                        k=(x["authority"],x["source_id"],x["text"])
                        if k in seen:continue
                        seen.add(k);out.append(x);contrib[label]=contrib.get(label,0)+1
                        if len(out)>=20:break
                    if len(out)>=20:break
            return out[:20],{
                "upper_bound":(
                    {"date":bound["date"].isoformat(),"relation":bound["relation"]}
                    if bound else None
                ),
                "eligible_source_count":len(eligible),
                "facets":[{"label":x[0],"quota":x[2]} for x in pieces[1:]],
                "contrib":contrib,
            }
        finally:
            comp.close()

def main():
    prior=load(GOV/"stagea_answerer_dev_v1_runtime"/"judge_result.json")
    v1_inputs=load(GOV/"stagea_answerer_dev_v1_inputs.json")["rows"]
    v1_map={x["qa_case_id"]:x for x in v1_inputs}
    failed=[
        x["qa_case_id"] for x in prior["rows"]
        if (not x["selection_gold_unknown"]) and x["evaluation_result"]!="Correct"
    ]
    unknown=[x["qa_case_id"] for x in prior["rows"] if x["selection_gold_unknown"]]
    if len(failed)!=6 or len(unknown)!=4:
        raise RuntimeError(f"unexpected selection sizes failed={len(failed)} unknown={len(unknown)}")
    selected=failed+unknown

    qas=load(RUN/"QA_INPUTS_POST_SEAL.json")["rows"]
    qmap={x["qa_case_id"]:x for x in qas}
    loc={}
    for pp in (RUN/"predictions").glob("*.json"):
        pred=load(pp)
        for li,sess in enumerate(pred.get("sessions") or []):
            for q in sess.get("questions") or []:
                loc[q["qa_case_id"]]=(pp,pred,li,sess)

    rows=[]
    for qid in selected:
        qa=qmap[qid];pp,pred,li,sess=loc[qid]
        cp=RUN/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
        ctx,meta=build_context(qa,pred,sess,cp)
        lines=[]
        for i,x in enumerate(ctx,1):
            md=f"authority={x['authority']}"
            if x["timestamp"]:md+=f" timestamp={x['timestamp']}"
            lines.append(f"[{i}] {md}\n{x['text']}")
        user="AUTHORIZED MEMORIES:\n"+("\n\n".join(lines) if lines else "(none)")+"\n\nQUESTION:\n"+qa["question"]
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":user}]
        old=v1_map[qid]
        rows.append({
            "case_id":"ansdev3-"+hashlib.sha256(qid.encode()).hexdigest()[:16],
            "qa_case_id":qid,
            "variant":qa["variant"],
            "selection_group":"known_failure" if qid in failed else "unknown_control",
            "selection_prior_label":next(
                x["evaluation_result"] for x in prior["rows"] if x["qa_case_id"]==qid
            ),
            "selection_gold_unknown":old["selection_gold_unknown"],
            "question":qa["question"],
            "historical_upper_bound":meta["upper_bound"],
            "authorized_memory_count":len(ctx),
            "authorized_memories":ctx,
            "retrieval_meta":meta,
            "messages":messages,
            "request_messages_sha256":stable(messages),
        })

    out={
        "schema":"xiaoyu-stagea-grounded-answerer-dev-inputs-v3",
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
        "question_derived_field_facets":True,
        "context_cap":20,
        "authorized_authorities":sorted(ALLOWED),
        "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({
        "cases":len(rows),"failed":len(failed),"unknown":len(unknown),
        "sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "job_context_n":next(x["authorized_memory_count"] for x in rows if "job title" in x["question"].casefold()),
        "historical_bounds":sum(x["historical_upper_bound"] is not None for x in rows),
        "facet_cases":sum(bool(x["retrieval_meta"]["facets"]) for x in rows),
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
