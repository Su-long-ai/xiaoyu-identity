#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,pathlib,shutil,tempfile,sys,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUNTIME=GOV/"budget50_halumem_dev_runtime_v1"
FROZEN=GOV/"confirmatory_frozen"
for p in (str(FROZEN),str(GOV),str(ROOT)):
    if p not in sys.path: sys.path.insert(0,p)

import r52_composition_candidate_v8 as r52
from stagea_exact_retrieval_diagnostic import load,bind_current_session_external_ids,is_gold_unknown

QA_INPUTS=RUNTIME/"QA_INPUTS_POST_SEAL.json"
PRED_DIR=RUNTIME/"predictions"
CP_ROOT=RUNTIME/"state_checkpoints"
OUT=GOV/"stagea_answerer_dev_v1_inputs.json"

ALLOWED={"user_state","user_history","user_source_history"}

SYSTEM=(
"You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. "
"Never use external facts, guesses, or assistant-only claims. If the authorized memories do not "
"directly support a reliable answer, output exactly {\"answer\":\"I don't know.\"}. "
"If memories conflict, prefer a directly relevant current user_state; otherwise prefer the most "
"recent directly relevant user-authored evidence. Answer the QUESTION directly and concisely, "
"normally within 12 words. For yes/no questions, start with Yes or No and add only the needed fact. "
"Return exactly one JSON object with one string field named answer and no other text."
)

def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def labels():
    v1=load(RUNTIME/"QA_SCORE_RECOVERY_PROGRESS_V1.json")
    v2=load(RUNTIME/"QA_SCORE_CONTINUATION_V2_PROGRESS.json")
    out={}
    for x in (v1.get("rows") or [])+(v2.get("rows") or []):
        out[x["qa_case_id"]]=str(x.get("evaluation_result") or "")
    abst={x["qa_case_id"] for x in (v1.get("abstains") or [])}
    abst.add(load(RUNTIME/"QA_SCORE_RECOVERY_ABORT_V1.json")["failed_qa_case_id"])
    for q in abst: out[q]="JudgeAbstain"
    return out

def choose(qa_rows,labs):
    # Deterministic stratified tuning sample: 8 medium omissions, 4 long omissions,
    # plus 2 medium + 2 long true-unknown controls.
    omissions={"m":[],"l":[]}; unknowns={"m":[],"l":[]}
    for r in qa_rows:
        qid=r["qa_case_id"]; v=r["variant"]
        if labs.get(qid)=="Omission":
            omissions[v].append(qid)
        if is_gold_unknown(r):
            unknowns[v].append(qid)
    key=lambda x:hashlib.sha256(("stagea-answerer-dev-v1:"+x).encode()).hexdigest()
    for d in (omissions,unknowns):
        for v in d: d[v]=sorted(d[v],key=key)
    chosen=omissions["m"][:8]+omissions["l"][:4]+unknowns["m"][:2]+unknowns["l"][:2]
    return chosen

def main():
    qa_rows=load(QA_INPUTS)["rows"]; qa_by={x["qa_case_id"]:x for x in qa_rows}; labs=labels()
    selected=choose(qa_rows,labs)
    locations={}
    for pp in sorted(PRED_DIR.glob("*.json")):
        pred=load(pp); stream=pp.stem
        for li,sess in enumerate(pred.get("sessions") or []):
            for q in sess.get("questions") or []:
                locations[q["qa_case_id"]]=(pp,pred,li,sess,q)

    rows=[]
    for qid in selected:
        pp,pred,li,sess,qrec=locations[qid]
        cp=CP_ROOT/pp.stem/f"session-{li+1:03d}.sqlite3"
        with tempfile.TemporaryDirectory(prefix="stagea-answerer-input-") as td:
            db=Path(td)/"state.sqlite3"; shutil.copy2(cp,db)
            comp=r52.R52Composition(db,identity_id=f"stagea-answerer-dev:{pp.stem}")
            try:
                bind_current_session_external_ids(comp,pred["variant"],pred["uuid_hash_prefix"],int(sess["session_index"]))
                rr=comp.retrieve(qrec["question"],limit=20)
            finally:
                comp.close()
        auth=[]
        seen=set()
        for x in rr:
            a=str(x.get("authority") or "")
            if a not in ALLOWED: continue
            text=str(x.get("text") or "").strip()
            if not text: continue
            key=(a,text,str(x.get("source_id") or ""))
            if key in seen: continue
            seen.add(key)
            auth.append({
                "authority":a,
                "effective_at":x.get("effective_at"),
                "source_id":x.get("source_id"),
                "text":text,
            })
        context_lines=[]
        for i,x in enumerate(auth,1):
            ts=(" effective_at="+str(x["effective_at"])) if x.get("effective_at") is not None else ""
            context_lines.append(f"[{i}] authority={x['authority']}{ts}\n{x['text']}")
        user=(
            "AUTHORIZED MEMORIES:\n"+("\n\n".join(context_lines) if context_lines else "(none)")
            +"\n\nQUESTION:\n"+qrec["question"]
        )
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":user}]
        rows.append({
            "case_id":"ansdev-"+hashlib.sha256(qid.encode()).hexdigest()[:16],
            "qa_case_id":qid,
            "variant":qa_by[qid]["variant"],
            "selection_label":labs.get(qid),
            "selection_gold_unknown":is_gold_unknown(qa_by[qid]),
            "question":qrec["question"],
            "authorized_memory_count":len(auth),
            "authorized_memories":auth,
            "messages":messages,
            "request_messages_sha256":stable(messages),
        })
    out={
        "schema":"xiaoyu-stagea-grounded-answerer-dev-inputs-v1",
        "status":"TUNING_ONLY",
        "selection_used_exposed_dev_labels":True,
        "prompt_contains_reference_answer":False,
        "prompt_contains_benchmark_evidence":False,
        "prompt_contains_judge_label":False,
        "assistant_history_allowed_for_user_fact":False,
        "retrieval_limit":20,
        "authorized_authorities":sorted(ALLOWED),
        "case_count":len(rows),
        "rows":rows,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({
        "case_count":len(rows),
        "known_failures":sum(not x["selection_gold_unknown"] for x in rows),
        "unknown_controls":sum(x["selection_gold_unknown"] for x in rows),
        "medium":sum(x["variant"]=="m" for x in rows),
        "long":sum(x["variant"]=="l" for x in rows),
        "memory_counts":[x["authorized_memory_count"] for x in rows],
        "sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
