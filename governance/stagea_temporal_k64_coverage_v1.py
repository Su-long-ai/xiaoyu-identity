#!/usr/bin/env python3
from __future__ import annotations
import datetime,hashlib,json,re,shutil,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
RUNTIME=GOV/"budget50_halumem_dev_runtime_v1"
for p in (str(FROZEN),str(GOV),str(ROOT)):
    if p not in sys.path:sys.path.insert(0,p)

import r52_composition_candidate_v8 as r52
from stagea_exact_retrieval_diagnostic import (
    load,bind_current_session_external_ids,gold_similarity,is_gold_unknown
)

ALLOWED={"user_state","user_history","user_source_history"}
MONTHS="Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
DATE_RE=re.compile(rf"(?i)\b({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})\b")
FILES={
 "m":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl",
 "l":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl",
}

def parse_dt(s):
    for fmt in ("%b %d, %Y, %H:%M:%S","%B %d, %Y, %H:%M:%S"):
        try:return datetime.datetime.strptime(str(s),fmt)
        except:pass
    return None

def question_date(q):
    m=DATE_RE.search(str(q))
    if not m:return None
    s=m.group(0)
    for fmt in ("%b %d, %Y","%B %d, %Y"):
        try:return datetime.datetime.strptime(s,fmt).date()
        except:pass
    return None

_RECORDS={}
def raw_record(variant,uuid):
    key=(variant,uuid)
    if key in _RECORDS:return _RECORDS[key]
    with FILES[variant].open("r",encoding="utf-8") as f:
        for line in f:
            if uuid not in line:continue
            o=json.loads(line)
            if str(o.get("uuid"))==uuid:
                _RECORDS[key]=o;return o
    raise KeyError(key)

def temporal_cutoff(record,target_date):
    if target_date is None:return None
    ordinal=0;cut=None
    for sess in record.get("sessions") or []:
        for turn in sess.get("dialogue") or []:
            ordinal+=1
            dt=parse_dt(turn.get("timestamp"))
            if dt is not None and dt.date()<=target_date:
                cut=ordinal
    return cut

def best_goldlike(gold_evidence,rows):
    best={"gold_like":False,"evidence_coverage":0.0,"jaccard":0.0,"intersection":0}
    for row in rows:
        text=str(row.get("text") or "")
        for ev in gold_evidence:
            s=gold_similarity(str(ev.get("memory_content") or ""),text)
            if (s["gold_like"],s["evidence_coverage"],s["jaccard"],s["intersection"]) > (
                best["gold_like"],best["evidence_coverage"],best["jaccard"],best["intersection"]):
                best=s
    return best

def main():
    inputs=load(GOV/"stagea_answerer_dev_v1_inputs.json")["rows"]
    qas=load(RUNTIME/"QA_INPUTS_POST_SEAL.json")["rows"]
    qmap={x["qa_case_id"]:x for x in qas}
    preds={}
    for p in (RUNTIME/"predictions").glob("*.json"):
        d=load(p)
        for li,sess in enumerate(d.get("sessions") or []):
            for q in sess.get("questions") or []:
                preds[q["qa_case_id"]]=(p,d,li,sess)

    rows=[]
    for inp in inputs:
        qid=inp["qa_case_id"];qa=qmap[qid];pp,pred,li,sess=preds[qid]
        cp=RUNTIME/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
        rec=raw_record(qa["variant"],qa["uuid"])
        qd=question_date(qa["question"])
        cutoff=temporal_cutoff(rec,qd)
        with tempfile.TemporaryDirectory(prefix="stagea-temporal-") as td:
            db=Path(td)/"state.sqlite3";shutil.copy2(cp,db)
            comp=r52.R52Composition(db,identity_id=f"temporal:{pp.stem}")
            try:
                bind_current_session_external_ids(comp,qa["variant"],pred["uuid_hash_prefix"],int(sess["session_index"]))
                raw=comp.retrieve(qa["question"],limit=64)
            finally:comp.close()
        allowed=[x for x in raw if str(x.get("authority") or "") in ALLOWED]
        temporal=[x for x in allowed if cutoff is None or int(x.get("effective_at") or 0)<=int(cutoff)]
        old=[{"text":x["text"],"authority":x["authority"],"source_id":x["source_id"],"effective_at":x.get("effective_at")} for x in inp["authorized_memories"]]
        known=not is_gold_unknown(qa)
        rows.append({
            "qa_case_id":qid,"variant":qa["variant"],"question":qa["question"],
            "known":known,"question_date":qd.isoformat() if qd else None,"cutoff_ordinal":cutoff,
            "old_k20_n":len(old),"k64_allowed_n":len(allowed),"k64_temporal_n":len(temporal),
            "future_filtered_n":len(allowed)-len(temporal),
            "old_best":best_goldlike(qa.get("evidence") or [],old) if known else None,
            "k64_temporal_best":best_goldlike(qa.get("evidence") or [],temporal) if known else None,
            "top_temporal":[{"authority":x.get("authority"),"effective_at":x.get("effective_at"),"text":x.get("text")} for x in temporal[:24]],
        })
    known=[x for x in rows if x["known"]];unk=[x for x in rows if not x["known"]]
    out={
      "schema":"xiaoyu-stagea-temporal-k64-coverage-v1","provider_calls":0,
      "candidate_uses_gold":False,"evaluation_uses_exposed_dev_gold":True,
      "rules":{"retrieval_k":64,"allowed_authority":sorted(ALLOWED),
               "full_date_filter":"effective_at <= max raw-turn ordinal whose timestamp date <= question date"},
      "summary":{
        "known_n":len(known),
        "old_k20_goldlike":sum(bool(x["old_best"]["gold_like"]) for x in known),
        "k64_temporal_goldlike":sum(bool(x["k64_temporal_best"]["gold_like"]) for x in known),
        "known_new_goldlike_gain":sum((not x["old_best"]["gold_like"]) and x["k64_temporal_best"]["gold_like"] for x in known),
        "dated_cases":sum(x["question_date"] is not None for x in rows),
        "future_rows_filtered":sum(x["future_filtered_n"] for x in rows),
        "unknown_n":len(unk),
      },
      "rows":rows,
    }
    (GOV/"STAGEA_TEMPORAL_K64_COVERAGE_V1.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(out["summary"],ensure_ascii=False,indent=2))
    print(json.dumps([{"qid":x["qa_case_id"],"date":x["question_date"],"filtered":x["future_filtered_n"],
                       "old_gold":x["old_best"]["gold_like"] if x["old_best"] else None,
                       "new_gold":x["k64_temporal_best"]["gold_like"] if x["k64_temporal_best"] else None,
                       "cov":x["k64_temporal_best"]["evidence_coverage"] if x["k64_temporal_best"] else None}
                      for x in rows],ensure_ascii=False,indent=2))

if __name__=="__main__":main()
