#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materialize only invalidated V1's selected gold as an exposed development set.

The upstream LoCoMo raw JSON is downloaded into memory, SHA-verified, and never
written to disk. Only V1-selected rows are persisted. V2-selected gold is never
written or printed.
"""
from __future__ import annotations
import hashlib,json,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
V1M=G/"LOCOMO_BLIND_200_MEMBERSHIP_V1.json"
V1I=G/"locomo_blind_200_input_v1.json"
V2M=G/"LOCOMO_BLIND_200_MEMBERSHIP_V2.json"
OUT=G/"LOCOMO_EXPOSED_DEV_V1_200.json"
URL="https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
RAW_SHA="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"

req=urllib.request.Request(URL,headers={"User-Agent":"XiaoYu-LoCoMo-V1-dev-extractor/1.0"})
with urllib.request.urlopen(req,timeout=60) as resp:
    raw=resp.read()
if hashlib.sha256(raw).hexdigest()!=RAW_SHA:
    raise SystemExit("LoCoMo raw SHA drift")
data=json.loads(raw.decode("utf-8"))
# Drop raw byte buffer ASAP after parse; no raw file is written.
del raw
samples={str(x["sample_id"]):x for x in data}
v1=json.loads(V1M.read_text("utf-8"))
v1_input=json.loads(V1I.read_text("utf-8"))
v2=json.loads(V2M.read_text("utf-8"))
v2set={(str(x["sample_id"]),str(x["question_sha256"])) for x in v2["rows"]}
rows=[]
for m in v1["rows"]:
    sid=str(m["sample_id"]); idx=int(m["qa_index"]); q=samples[sid]["qa"][idx]
    qh=hashlib.sha256(str(q.get("question","")).encode("utf-8")).hexdigest()
    if qh!=m["question_sha256"]: raise RuntimeError("V1 question binding drift")
    if (sid,qh) in v2set: raise RuntimeError("V1/V2 overlap unexpectedly nonzero")
    rows.append({
      "blind_id":m["blind_id"],
      "sample_id":sid,
      "qa_index":idx,
      "category":str(q.get("category")),
      "question":q.get("question"),
      "answer":q.get("answer"),
      "evidence":q.get("evidence"),
    })
if len(rows)!=200 or len({x["blind_id"] for x in rows})!=200:
    raise RuntimeError("V1 dev membership drift")
out={
 "schema":"xiaoyu-locomo-exposed-dev-v1-200-v1",
 "status":"EXPOSED_DEVELOPMENT_ONLY",
 "origin":"LoCoMo blind V1 invalidated before any prediction; now intentionally exposed for development",
 "raw_dataset_sha256":RAW_SHA,
 "v1_membership_sha256":hashlib.sha256(V1M.read_bytes()).hexdigest(),
 "v1_input_sha256":hashlib.sha256(V1I.read_bytes()).hexdigest(),
 "v2_overlap":0,
 "may_support_generalization_claim":False,
 "must_be_excluded_from_future_blind_generations":True,
 "raw_file_written":False,
 "rows":rows,
}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({
 "status":out["status"],"rows":len(rows),
 "output_sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
 "v2_overlap":0,"raw_file_written":False,
 "categories":{c:sum(x["category"]==c for x in rows) for c in sorted({x["category"] for x in rows})}
},ensure_ascii=False,indent=2))
