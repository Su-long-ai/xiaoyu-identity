#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the formal HaluMem V5 answer overlay after prediction seal.

No provider calls. No gold fields are materialized.

Required order:
1. exact Recovery-V2 extraction completes for all 36 streams;
2. exact Recovery-V2 PREDICTION_SEAL.json exists and validates 36 files;
3. this builder selectively reads only non-gold fields;
4. V5 answer-input files are frozen per stream;
5. a separate paid answer runner may execute only against those frozen bytes.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, shutil, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
RUNTIME=GOV/"halumem_confirmatory_runtime_v2"
SEAL=RUNTIME/"PREDICTION_SEAL.json"
OUTROOT=RUNTIME/"v5_answer_overlay_inputs"
INDEX=RUNTIME/"V5_ANSWER_OVERLAY_INPUT_SEAL.json"
COUNT=GOV/"FORMAL_SAFE_QUESTION_COUNT_V3.json"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
MEDIUM=ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl"
LONG=ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl"
CAND=GOV/"formal_v5_answer_overlay_candidate.py"

for p in (str(ROOT),str(GOV),str(FROZEN)):
    while p in sys.path: sys.path.remove(p)
    sys.path.insert(0,p)
# FROZEN must win for the accepted R52 closure.
while str(FROZEN) in sys.path: sys.path.remove(str(FROZEN))
sys.path.insert(0,str(FROZEN))

import formal_v5_answer_overlay_candidate as ov
import r52_composition_candidate_v8 as r52

class BuildError(RuntimeError): pass

def load(p):
    x=json.loads(Path(p).read_text("utf-8"))
    if not isinstance(x,dict):raise BuildError(f"not object: {p}")
    return x

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def atomic_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8")
    tmp.replace(path)

def split_config():
    h=load(SPLIT)["halumem"]
    uuids=list(map(str,h["confirmatory_uuids"]))
    if len(uuids)!=18 or len(set(uuids))!=18:raise BuildError("confirmatory split !=18")
    return {"uuids":uuids,"hashes":{u:hashlib.sha256(u.encode()).hexdigest() for u in uuids}}

def validate_prediction_seal():
    if not SEAL.is_file():raise BuildError("Recovery-V2 prediction seal required")
    s=load(SEAL)
    if s.get("schema")!="xiaoyu-halumem-confirmatory-prediction-seal-v2-recovery":
        raise BuildError("wrong prediction seal schema")
    if s.get("sealed") is not True or int(s.get("prediction_count") or 0)!=36:
        raise BuildError("prediction seal not exact 36")
    if int(s.get("gold_fields_read_before_seal") or 0)!=0:
        raise BuildError("prediction seal reports pre-seal gold read")
    files=s.get("prediction_files") or []
    if len(files)!=36:raise BuildError("prediction files !=36")
    for row in files:
        p=GOV/row["path"]
        if not p.is_file() or sha(p)!=row["sha256"]:
            raise BuildError("sealed prediction byte drift: "+str(row.get("path")))
        o=load(p)
        if o.get("complete") is not True:
            raise BuildError("sealed prediction incomplete")
        if int(o.get("gold_fields_materialized") or 0)!=0:
            raise BuildError("prediction materialized gold")
    return s

def case_id(variant,pref,si,qi):
    return f"hm-a-v5-{variant}-{pref}-s{int(si)}-q{int(qi)}"

def prediction_path(variant,uh):
    return RUNTIME/"predictions"/f"{variant}-{uh[:12]}.json"

def checkpoint_path(variant,uh,si):
    return RUNTIME/"state_checkpoints"/variant/uh/f"session-{int(si)+1:03d}.sqlite3"

def build_stream(variant,rec,uh):
    pref=uh[:12]
    pred=load(prediction_path(variant,uh))
    if pred.get("complete") is not True:raise BuildError("prediction not complete")
    if pred.get("uuid_hash")!=uh:raise BuildError("prediction uuid hash drift")
    if int(pred.get("completed_sessions") or 0)!=len(rec["sessions"]):
        raise BuildError("prediction/safe-record session cardinality drift")

    rows=[]
    for si,session in enumerate(rec["sessions"]):
        questions=session.get("questions") or []
        if not questions:continue
        cp=checkpoint_path(variant,uh,si)
        if not cp.is_file():raise BuildError(f"checkpoint missing {variant}/{pref}/s{si}")
        with tempfile.TemporaryDirectory(prefix="formal-v5-overlay-") as td:
            db=Path(td)/"state.sqlite3"
            shutil.copy2(cp,db)
            comp=r52.R52Composition(db,identity_id=f"formal-v5-overlay:{variant}:{pref}:s{si}")
            try:
                for qi,q in enumerate(questions):
                    question=str(q["question"])
                    msgs,ctx,meta=ov.build_messages(comp,rec,variant,uh,si,question)
                    cid=case_id(variant,pref,si,qi)
                    rows.append({
                      "case_id":cid,
                      "variant":variant,
                      "uuid_hash":uh,
                      "session_index":si,
                      "question_index":qi,
                      "question":question,
                      "historical_upper_bound":meta.get("upper_bound"),
                      "authorized_memory_count":len(ctx),
                      "authorized_memories":ctx,
                      "retrieval_meta":meta,
                      "messages":msgs,
                      "request_messages_sha256":stable(msgs),
                    })
            finally:
                comp.close()
    out={
      "schema":"xiaoyu-formal-v5-answer-overlay-input-stream-v1",
      "variant":variant,
      "uuid_hash":uh,
      "prediction_sha256":sha(prediction_path(variant,uh)),
      "prediction_seal_sha256":sha(SEAL),
      "overlay_candidate_sha256":sha(CAND),
      "question_count":len(rows),
      "gold_fields_materialized":0,
      "provider_calls":0,
      "rows":rows,
    }
    p=OUTROOT/f"{variant}-{pref}.json"
    atomic_json(p,out)
    return {"path":str(p.relative_to(GOV)).replace("\\","/"),"sha256":sha(p),
            "variant":variant,"uuid_hash":uh,"question_count":len(rows)}

def build():
    seal=validate_prediction_seal()
    count=load(COUNT)
    expected=int(count["total_questions"])
    split=split_config()
    selected=set(split["uuids"])
    records={}
    for variant,path in (("m",MEDIUM),("l",LONG)):
        for rec in ov.iter_safe_answer_selected(path,selected):
            uh=hashlib.sha256(rec["uuid"].encode()).hexdigest()
            if uh not in set(split["hashes"].values()):raise BuildError("safe row outside split")
            records[(variant,uh)]=rec
    if len(records)!=36:raise BuildError(f"safe record count {len(records)} !=36")

    files=[]
    for variant in ("m","l"):
        for u in split["uuids"]:
            uh=split["hashes"][u]
            files.append(build_stream(variant,records[(variant,uh)]))
    total=sum(x["question_count"] for x in files)
    if total!=expected:raise BuildError(f"overlay question count {total} != expected {expected}")
    if len({x["path"] for x in files})!=36:raise BuildError("overlay stream path duplicate")
    idx={
      "schema":"xiaoyu-formal-v5-answer-overlay-input-seal-v1",
      "sealed":True,
      "prediction_seal_sha256":sha(SEAL),
      "overlay_candidate_sha256":sha(CAND),
      "builder_sha256":sha(Path(__file__)),
      "formal_question_count_source_sha256":sha(COUNT),
      "question_count":total,
      "stream_count":36,
      "files":sorted(files,key=lambda x:x["path"]),
      "gold_fields_materialized":0,
      "provider_calls":0,
    }
    atomic_json(INDEX,idx)
    return idx

def preflight():
    return {
      "schema":"xiaoyu-formal-v5-overlay-build-preflight-v1",
      "prediction_seal_exists":SEAL.is_file(),
      "count_file_exists":COUNT.is_file(),
      "candidate_sha256":sha(CAND),
      "builder_sha256":sha(Path(__file__)),
      "provider_calls":0,
      "gold_fields_materialized":0,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",nargs="?",default="preflight",choices=["preflight","build"])
    a=ap.parse_args()
    try:out=preflight() if a.action=="preflight" else build()
    except Exception as e:
        print(json.dumps({"ok":False,"error":type(e).__name__+":"+str(e)},ensure_ascii=False,indent=2))
        raise SystemExit(2)
    print(json.dumps({"ok":True,"result":out},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
