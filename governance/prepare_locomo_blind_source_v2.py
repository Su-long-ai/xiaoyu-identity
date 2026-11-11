#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trusted one-time sanitizer for LoCoMo blind V2.

Reads the upstream raw dataset only to remove all gold-bearing and derived-summary
fields. It writes a local source containing ONLY sample_id, conversation, and
per-QA question/category. It never prints or writes answer/evidence plaintext.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/"external"/"OmniMemEval"/"data"/"locomo"/"locomo10.json"
OUT=ROOT/"governance"/"locomo_blind_source_v2_gold_stripped.json"
META=ROOT/"governance"/"LOCOMO_BLIND_SOURCE_V2_SANITIZE_RECORD.json"
EXPECTED_RAW_SHA="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
if not RAW.is_file(): raise SystemExit("raw LoCoMo source missing")
if sha(RAW)!=EXPECTED_RAW_SHA: raise SystemExit("raw LoCoMo SHA drift")
data=json.loads(RAW.read_text("utf-8"))
if not isinstance(data,list) or len(data)!=10: raise SystemExit("raw LoCoMo shape drift")
safe=[]
for sample in data:
    safe.append({
      "sample_id":str(sample["sample_id"]),
      "conversation":sample.get("conversation"),
      "qa":[{"question":q.get("question"),"category":str(q.get("category"))} for q in (sample.get("qa") or [])],
    })
OUT.write_text(json.dumps({"schema":"xiaoyu-locomo-gold-stripped-source-v2","raw_dataset_sha256":EXPECTED_RAW_SHA,"samples":safe},ensure_ascii=False,indent=2)+"\n","utf-8")
record={
  "schema":"xiaoyu-locomo-source-sanitize-record-v2",
  "status":"GOLD_STRIPPED_SOURCE_CREATED",
  "raw_dataset_sha256":EXPECTED_RAW_SHA,
  "gold_stripped_source_path":"governance/locomo_blind_source_v2_gold_stripped.json",
  "gold_stripped_source_sha256":sha(OUT),
  "sample_count":len(safe),
  "qa_count":sum(len(x["qa"]) for x in safe),
  "output_contains_answer":False,
  "output_contains_evidence":False,
  "output_contains_event_summary":False,
  "output_contains_observation":False,
  "output_contains_session_summary":False,
  "stdout_contains_gold":False,
}
META.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps(record,ensure_ascii=False,indent=2))
