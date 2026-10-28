#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen LongMemEval-S context builder for the E2 nonpromotional pilot.

No model/API calls. Reuses the accepted P1 lexical source-aware history policy:
- SQLite FTS5 lexical relevance;
- user raw source -> user_history;
- assistant raw source -> conversation_history;
- lifecycle active;
- top-7 whole source records;
- rarest-term posting guard at 128.

The builder deliberately never reads answer/gold fields into the paid payload.
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
DATASET=ROOT/"external"/"OmniMemEval"/"data"/"longmemeval"/"longmemeval_s_cleaned.json"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
DATASET_SHA256="d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
LIMIT=7
MAX_POSTING=128
TRACK="longmemeval_answer"

if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from identity_core import _keywords

SCHEMA="""
CREATE TABLE evidence_docs(
  doc_key TEXT PRIMARY KEY,
  source_message_id TEXT NOT NULL,
  source_role TEXT NOT NULL,
  authority TEXT NOT NULL,
  temporal_status TEXT NOT NULL,
  lifecycle TEXT NOT NULL,
  source_time TEXT NOT NULL,
  text TEXT NOT NULL,
  priority INTEGER NOT NULL,
  token_blob TEXT NOT NULL
);
CREATE INDEX idx_e2_lme_authority ON evidence_docs(authority,lifecycle);
CREATE VIRTUAL TABLE evidence_fts USING fts5(
  token_blob, content='evidence_docs', content_rowid='rowid', tokenize='unicode61'
);
CREATE VIRTUAL TABLE evidence_vocab USING fts5vocab(evidence_fts,'row');
CREATE TRIGGER evidence_ai AFTER INSERT ON evidence_docs BEGIN
  INSERT INTO evidence_fts(rowid,token_blob) VALUES(new.rowid,new.token_blob);
END;
"""
AUTHORITY_PRIORITY={"user_history":3,"conversation_history":2}


class ContextBuildError(RuntimeError):
    pass


def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()


def tok(term:str)->str:
    return "k"+term.encode("utf-8").hex()


def token_blob(text:str)->str:
    return " ".join(tok(x) for x in sorted(_keywords(str(text))))


def case_id(index:int)->str:
    return f"lme-a-{int(index):03d}"


def frozen_pilot_indices()->list[int]:
    split=json.loads(SPLIT.read_text(encoding="utf-8"))
    return [int(x) for x in split["longmemeval"]["pilot_indices"]]


def verify_dataset()->None:
    if not DATASET.is_file():
        raise ContextBuildError("LongMemEval-S dataset is missing")
    actual=sha_file(DATASET)
    if actual.lower()!=DATASET_SHA256:
        raise ContextBuildError(
            f"LongMemEval-S hash mismatch: {actual} != {DATASET_SHA256}")


def load_dataset():
    verify_dataset()
    data=json.loads(DATASET.read_text(encoding="utf-8"))
    if not isinstance(data,list) or len(data)!=500:
        raise ContextBuildError("LongMemEval-S must contain exactly 500 records")
    return data


def put_record(con,idx:int,record:dict)->int:
    sessions=record["haystack_sessions"]
    dates=record["haystack_dates"]
    session_ids=record["haystack_session_ids"]
    if not (len(sessions)==len(dates)==len(session_ids)):
        raise ContextBuildError("LongMemEval session/date/id lengths differ")
    count=0
    for si,(session,date,sid) in enumerate(zip(sessions,dates,session_ids)):
        for mi,msg in enumerate(session):
            role=str(msg.get("role") or "").lower()
            if role not in ("user","assistant"):
                continue
            text=str(msg.get("content") or "")
            if not text.strip():
                continue
            authority="user_history" if role=="user" else "conversation_history"
            priority=AUTHORITY_PRIORITY[authority]
            # LongMemEval can repeat haystack_session_ids inside one record.
            # Bind source identity to the stable session ordinal as well so two
            # distinct source messages can never collide in the local evidence DB.
            doc_key=f"lme:{idx}:{si}:{sid}:{mi}"
            con.execute(
                """INSERT INTO evidence_docs(
                   doc_key,source_message_id,source_role,authority,temporal_status,
                   lifecycle,source_time,text,priority,token_blob)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (doc_key,doc_key,role,authority,"historical","active",
                 str(date),text,priority,token_blob(text)))
            count+=1
    return count


def recall(con,query:str,limit:int=LIMIT,max_posting:int=MAX_POSTING):
    terms=sorted(_keywords(str(query)))
    if not terms:
        return [],{"status":"NO_TERMS","query_terms":[]}
    encoded={tok(t):t for t in terms}
    marks=",".join("?" for _ in encoded)
    vocab=con.execute(
        f"SELECT term,doc FROM evidence_vocab WHERE term IN ({marks})",
        list(encoded)).fetchall()
    dfs=[(int(r[1]),encoded[str(r[0])]) for r in vocab if int(r[1])>0]
    if not dfs:
        return [],{"status":"ZERO_OVERLAP","query_terms":terms}
    df,rare=min(dfs)
    if df>max_posting:
        return [],{"status":"FALLBACK_HIGH_DF","query_terms":terms,
                   "rarest_term":rare,"rarest_df":df}
    rows=con.execute(
        """SELECT d.* FROM evidence_fts f
           JOIN evidence_docs d ON d.rowid=f.rowid
           WHERE evidence_fts MATCH ? AND d.lifecycle='active'""",
        (tok(rare),)).fetchall()
    q=set(terms); ranked=[]
    for row in rows:
        text=str(row[7])
        overlap=len(q&_keywords(text))
        if not overlap:continue
        score=overlap*12+int(row[8])*2
        ranked.append((score,str(row[0]),row))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    selected=ranked[:limit]
    context=[]
    for rank,(score,_key,row) in enumerate(selected,1):
        context.append({
            "id":str(row[0]),
            "source_role":str(row[2]),
            "authority":str(row[3]),
            "temporal_status":str(row[4]),
            "lifecycle":str(row[5]),
            "time":str(row[6]),
            "text":str(row[7]),
        })
    meta={"status":"FTS5","query_terms":terms,"rarest_term":rare,
          "rarest_df":df,"candidate_count":len(rows),"returned":len(context)}
    return context,meta


def build_payload_from_record(index:int,record:dict):
    cid=case_id(index)
    if index not in set(frozen_pilot_indices()):
        raise ContextBuildError(f"index {index} is outside frozen pilot split")
    question=str(record.get("question") or "")
    if not question:
        raise ContextBuildError("LongMemEval question is empty")
    con=sqlite3.connect(":memory:")
    try:
        con.executescript(SCHEMA)
        docs=put_record(con,index,record)
        context,meta=recall(con,question)
    finally:
        con.close()
    payload={"id":cid,"context":context,"question":question}
    diagnostics={
        "schema":"xiaoyu-e2-lme-context-build-v1",
        "track":TRACK,"case_id":cid,"dataset_index":index,
        "question_id":str(record.get("question_id") or ""),
        "question_type":str(record.get("question_type") or ""),
        "question_date":str(record.get("question_date") or ""),
        "docs_indexed":docs,
        "retrieval":meta,
        "context_ids":[x["id"] for x in context],
        "context_authorities":[x["authority"] for x in context],
        "gold_fields_read_into_payload":False,
        "model_calls":0,
    }
    return payload,diagnostics


def build_payload(index:int,data=None):
    if data is None:data=load_dataset()
    return build_payload_from_record(index,data[index])


def write_json_lf(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--indices",nargs="+",type=int,required=True)
    ap.add_argument("--output-dir",default=str(GOV/"e2_pilot_inputs"))
    args=ap.parse_args()
    data=load_dataset()
    outdir=Path(args.output_dir)
    plan=[]
    summaries=[]
    for idx in args.indices:
        payload,diag=build_payload(idx,data)
        cid=case_id(idx)
        pp=outdir/(cid+".payload.json")
        dp=outdir/(cid+".context.json")
        write_json_lf(pp,payload);write_json_lf(dp,diag)
        plan.append({"track":TRACK,"case_id":cid,"payload":payload})
        summaries.append({"case_id":cid,"payload":str(pp),"diagnostics":str(dp),
                          "retrieval":diag["retrieval"]})
    plan_path=outdir/"plan.jsonl"
    plan_path.parent.mkdir(parents=True,exist_ok=True)
    with plan_path.open("w",encoding="utf-8",newline="\n") as f:
        for row in plan:
            f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    print(json.dumps({"dataset_sha256":DATASET_SHA256,"indices":args.indices,
                      "plan":str(plan_path),"cases":summaries,"provider_calls":0},
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
