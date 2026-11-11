#!/usr/bin/env python3
from __future__ import annotations
import datetime,json,re,shutil,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
RUNTIME=GOV/"budget50_halumem_dev_runtime_v1"
for p in (str(FROZEN),str(GOV),str(ROOT)):
    if p not in sys.path:sys.path.insert(0,p)

import r52_composition_candidate_v8 as r52
from stagea_exact_retrieval_diagnostic import load,bind_current_session_external_ids,gold_similarity,is_gold_unknown

ALLOWED={"user_state","user_history","user_source_history"}
MONTHS="Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
DATE_RE=re.compile(rf"(?i)\b({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})\b")
FILES={"m":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl","l":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl"}
_REC={}

def parse_dt(s):
    for fmt in ("%b %d, %Y, %H:%M:%S","%B %d, %Y, %H:%M:%S"):
        try:return datetime.datetime.strptime(str(s),fmt)
        except:pass
    return None

def qdate(q):
    m=DATE_RE.search(str(q))
    if not m:return None
    for fmt in ("%b %d, %Y","%B %d, %Y"):
        try:return datetime.datetime.strptime(m.group(0),fmt).date()
        except:pass
    return None

def rec(v,u):
    key=(v,u)
    if key in _REC:return _REC[key]
    with FILES[v].open("r",encoding="utf-8") as f:
        for line in f:
            if u not in line:continue
            o=json.loads(line)
            if str(o.get("uuid"))==u:_REC[key]=o;return o
    raise KeyError(key)

def session_turn_timestamp(record,si,ti):
    try:return parse_dt(record["sessions"][int(si)]["dialogue"][int(ti)].get("timestamp"))
    except:return None

def row_timestamp(row,history,record):
    sid=str(row.get("source_id") or "")
    m=re.search(r":s(\d+):t(\d+)$",sid)
    if m:return session_turn_timestamp(record,*map(int,m.groups()))
    h=history.get(sid)
    if h:
        conv=str(h.get("conversation_id") or "")
        m=re.search(r":session:(\d+)$",conv)
        if m:
            return session_turn_timestamp(record,int(m.group(1)),int(h.get("message_seq") or h.get("message_id") or 0))
    return None

def best(gold,rows):
    z={"gold_like":False,"evidence_coverage":0.0,"jaccard":0.0,"intersection":0}
    for r in rows:
        for e in gold:
            s=gold_similarity(str(e.get("memory_content") or ""),str(r.get("text") or ""))
            if (s["gold_like"],s["evidence_coverage"],s["jaccard"],s["intersection"])>(z["gold_like"],z["evidence_coverage"],z["jaccard"],z["intersection"]):z=s
    return z

def main():
    inputs=load(GOV/"stagea_answerer_dev_v1_inputs.json")["rows"]
    qas=load(RUNTIME/"QA_INPUTS_POST_SEAL.json")["rows"];qmap={x["qa_case_id"]:x for x in qas}
    loc={}
    for pp in (RUNTIME/"predictions").glob("*.json"):
        pred=load(pp)
        for li,s in enumerate(pred.get("sessions") or []):
            for q in s.get("questions") or []:loc[q["qa_case_id"]]=(pp,pred,li,s)
    rows=[]
    for inp in inputs:
        qid=inp["qa_case_id"];qa=qmap[qid];pp,pred,li,sess=loc[qid]
        cp=RUNTIME/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
        record=rec(qa["variant"],qa["uuid"]);target=qdate(qa["question"])
        with tempfile.TemporaryDirectory(prefix="stagea-temporal2-") as td:
            db=Path(td)/"s.sqlite3";shutil.copy2(cp,db)
            comp=r52.R52Composition(db,identity_id="temporal2:"+pp.stem)
            try:
                bind_current_session_external_ids(comp,qa["variant"],pred["uuid_hash_prefix"],int(sess["session_index"]))
                raw=comp.retrieve(qa["question"],limit=64)
                history={x["source_message_id"]:x for x in comp.store.source_history()}
            finally:comp.close()
        allowed=[x for x in raw if str(x.get("authority") or "") in ALLOWED]
        enriched=[]
        for x in allowed:
            ts=row_timestamp(x,history,record)
            y=dict(x);y["_timestamp"]=ts.isoformat() if ts else None
            enriched.append(y)
        temporal=[x for x in enriched if target is None or x["_timestamp"] is None or datetime.datetime.fromisoformat(x["_timestamp"]).date()<=target]
        known=not is_gold_unknown(qa)
        rows.append({"qa_case_id":qid,"variant":qa["variant"],"question":qa["question"],"known":known,
          "question_date":target.isoformat() if target else None,"allowed_n":len(allowed),"temporal_n":len(temporal),
          "future_filtered":[{"text":x["text"],"authority":x["authority"],"effective_at":x.get("effective_at"),"timestamp":x["_timestamp"]} for x in enriched if x not in temporal],
          "best":best(qa.get("evidence") or [],temporal) if known else None,
          "top20":[{"text":x["text"],"authority":x["authority"],"effective_at":x.get("effective_at"),"timestamp":x["_timestamp"]} for x in temporal[:20]]})
    known=[x for x in rows if x["known"]]
    out={"schema":"xiaoyu-stagea-source-timestamp-temporal-v2","provider_calls":0,"candidate_uses_gold":False,"evaluation_uses_dev_gold":True,
      "summary":{"known_n":len(known),"goldlike_after":sum(x["best"]["gold_like"] for x in known),"dated_cases":sum(x["question_date"] is not None for x in rows),"future_rows_filtered":sum(len(x["future_filtered"]) for x in rows)},
      "rows":rows}
    (GOV/"STAGEA_SOURCE_TIMESTAMP_TEMPORAL_V2.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(out["summary"],indent=2))
    print(json.dumps([{"qid":x["qa_case_id"],"date":x["question_date"],"filtered":len(x["future_filtered"]),"gold":x["best"]["gold_like"] if x["best"] else None,
      "filtered_examples":[(z["timestamp"],z["text"][:90]) for z in x["future_filtered"][:5]]} for x in rows],ensure_ascii=False,indent=2))

if __name__=="__main__":main()
