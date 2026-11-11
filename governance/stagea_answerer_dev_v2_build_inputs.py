#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,shutil,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUNTIME=GOV/"budget50_halumem_dev_runtime_v1"
FROZEN=GOV/"confirmatory_frozen"
for p in (str(FROZEN),str(GOV),str(ROOT)):
    if p not in sys.path:sys.path.insert(0,p)

import r52_composition_candidate_v8 as r52
from stagea_exact_retrieval_diagnostic import load,bind_current_session_external_ids
from stagea_source_timestamp_temporal_v2 import rec,qdate,row_timestamp

ALLOWED={"user_state","user_history","user_source_history"}
OUT=GOV/"stagea_answerer_dev_v2_inputs.json"

SYSTEM=(
"You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. "
"Never use external facts, guesses, assistant-only claims, or memories outside the supplied list. "
"If the authorized memories do not directly support a reliable answer, output exactly "
"{\"answer\":\"I don't know.\"}. "
"For a historical question containing 'as of' or a specific date, answer only from memories at or "
"before that date; the supplied list has already removed known future memories. "
"If memories conflict, prefer the most directly relevant user_state, then the most recent directly "
"relevant user-authored evidence that is valid for the question's time. "
"If the question asks about multiple attributes or contrasts multiple states, answer EVERY requested "
"component that is directly supported; do not silently omit one supported component. "
"Answer the QUESTION directly and concisely, normally within 18 words. "
"For yes/no questions, start with Yes or No and include all supported facts needed to resolve the contrast. "
"Return exactly one JSON object with one string field named answer and no other text."
)

def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def normalize_text(s):
    return " ".join(str(s).casefold().split())

def main():
    prior=load(GOV/"stagea_answerer_dev_v1_runtime"/"judge_result.json")
    v1_inputs=load(GOV/"stagea_answerer_dev_v1_inputs.json")["rows"]
    v1_map={x["qa_case_id"]:x for x in v1_inputs}
    failed=[x["qa_case_id"] for x in prior["rows"] if (not x["selection_gold_unknown"]) and x["evaluation_result"]!="Correct"]
    unknown=[x["qa_case_id"] for x in prior["rows"] if x["selection_gold_unknown"]]
    if len(failed)!=6 or len(unknown)!=4:
        raise RuntimeError(f"unexpected selection sizes failed={len(failed)} unknown={len(unknown)}")
    selected=failed+unknown

    qas=load(RUNTIME/"QA_INPUTS_POST_SEAL.json")["rows"];qmap={x["qa_case_id"]:x for x in qas}
    loc={}
    for pp in (RUNTIME/"predictions").glob("*.json"):
        pred=load(pp)
        for li,sess in enumerate(pred.get("sessions") or []):
            for q in sess.get("questions") or []:
                loc[q["qa_case_id"]]=(pp,pred,li,sess)

    rows=[]
    for qid in selected:
        qa=qmap[qid];pp,pred,li,sess=loc[qid]
        cp=RUNTIME/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
        record=rec(qa["variant"],qa["uuid"]);target=qdate(qa["question"])
        with tempfile.TemporaryDirectory(prefix="stagea-answerer-v2-") as td:
            db=Path(td)/"state.sqlite3";shutil.copy2(cp,db)
            comp=r52.R52Composition(db,identity_id="answerer-v2:"+pp.stem)
            try:
                bind_current_session_external_ids(comp,qa["variant"],pred["uuid_hash_prefix"],int(sess["session_index"]))
                raw=comp.retrieve(qa["question"],limit=64)
                history={x["source_message_id"]:x for x in comp.store.source_history()}
            finally:comp.close()

        filtered=[]
        seen=set()
        future_filtered=0
        for x in raw:
            auth=str(x.get("authority") or "")
            if auth not in ALLOWED:continue
            text=str(x.get("text") or "").strip()
            if not text:continue
            ts=row_timestamp(x,history,record)
            if target is not None and ts is not None and ts.date()>target:
                future_filtered+=1
                continue
            nt=normalize_text(text)
            if nt in seen:continue
            seen.add(nt)
            filtered.append({
                "authority":auth,
                "timestamp":ts.isoformat() if ts else None,
                "effective_at":x.get("effective_at"),
                "source_id":x.get("source_id"),
                "text":text,
            })
            if len(filtered)>=20:break

        lines=[]
        for i,x in enumerate(filtered,1):
            meta=f"authority={x['authority']}"
            if x["timestamp"]:meta+=f" timestamp={x['timestamp']}"
            lines.append(f"[{i}] {meta}\n{x['text']}")
        user="AUTHORIZED MEMORIES:\n"+("\n\n".join(lines) if lines else "(none)")+"\n\nQUESTION:\n"+qa["question"]
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":user}]
        old=v1_map[qid]
        rows.append({
            "case_id":"ansdev2-"+hashlib.sha256(qid.encode()).hexdigest()[:16],
            "qa_case_id":qid,
            "variant":qa["variant"],
            "selection_group":"known_failure" if qid in failed else "unknown_control",
            "selection_prior_label":next(x["evaluation_result"] for x in prior["rows"] if x["qa_case_id"]==qid),
            "selection_gold_unknown":old["selection_gold_unknown"],
            "question":qa["question"],
            "question_date":target.isoformat() if target else None,
            "retrieval_k":64,
            "future_filtered_n":future_filtered,
            "authorized_memory_count":len(filtered),
            "authorized_memories":filtered,
            "messages":messages,
            "request_messages_sha256":stable(messages),
        })

    out={
      "schema":"xiaoyu-stagea-grounded-answerer-dev-inputs-v2",
      "status":"TUNING_ONLY",
      "selection_used_exposed_dev_labels":True,
      "case_count":10,
      "known_failure_n":6,
      "unknown_control_n":4,
      "prompt_contains_reference_answer":False,
      "prompt_contains_benchmark_evidence":False,
      "prompt_contains_judge_label":False,
      "assistant_history_allowed_for_user_fact":False,
      "retrieval_k":64,
      "source_timestamp_temporal_filter":True,
      "deduplicate_evidence_text":True,
      "context_cap":20,
      "authorized_authorities":sorted(ALLOWED),
      "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({
      "cases":len(rows),"failed":len(failed),"unknown":len(unknown),
      "future_filtered_total":sum(x["future_filtered_n"] for x in rows),
      "memory_counts":[x["authorized_memory_count"] for x in rows],
      "sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
      "qids":[x["qa_case_id"] for x in rows],
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
