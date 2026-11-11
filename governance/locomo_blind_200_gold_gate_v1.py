#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed authorization gate for LoCoMo blind-200 gold access.

This file never exposes gold. It only authorizes a later scorer after BOTH
baseline and candidate prediction seals are present and exact-bound.

Usage:
  py -3.11 governance/locomo_blind_200_gold_gate_v1.py check
  py -3.11 governance/locomo_blind_200_gold_gate_v1.py authorize

Before a valid system binding exists, both modes fail closed.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
PROTOCOL=G/"LOCOMO_BLIND_200_PROTOCOL_V1.json"
MEMBERSHIP=G/"LOCOMO_BLIND_200_MEMBERSHIP_V1.json"
BLIND_INPUT=G/"locomo_blind_200_input_v1.json"
GOLD_SEAL=G/"LOCOMO_BLIND_200_GOLD_HASH_SEAL_V1.json"
BINDING=G/"LOCOMO_BLIND_200_SYSTEM_BINDING_V1.json"
AUTH=G/"LOCOMO_BLIND_200_GOLD_DECODE_AUTHORIZATION_V1.json"

EXPECTED_PROTOCOL_SHA="947a46a38ce4a094147e4b86904b86d0c55a134b94c5e7ba19e45df0cd0d2af2"
EXPECTED_MEMBERSHIP_SHA="833d14b24902f5c6809f4e676c440cd101c4e654b22ef0e507d64853a9fbb62a"
EXPECTED_INPUT_SHA="2dc4752f2369bcc4772f6440a426f772115b9d3dfc94175fe2417391f23c67a1"
EXPECTED_GOLD_SEAL_SHA="a19385d95b5051b69d157e0495f341a83ecf4c0583560d016708e4e33844f773"

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def fail(reason,detail=None):
    out={"schema":"xiaoyu-locomo-blind-gold-gate-v1","status":"BLOCKED","reason":reason}
    if detail is not None:out["detail"]=detail
    print(json.dumps(out,ensure_ascii=False,indent=2))
    raise SystemExit(2)

def validate():
    expected=[
      (PROTOCOL,EXPECTED_PROTOCOL_SHA,"protocol"),
      (MEMBERSHIP,EXPECTED_MEMBERSHIP_SHA,"membership"),
      (BLIND_INPUT,EXPECTED_INPUT_SHA,"blind_input"),
      (GOLD_SEAL,EXPECTED_GOLD_SEAL_SHA,"gold_hash_seal"),
    ]
    for p,e,label in expected:
        if not p.is_file():fail("FROZEN_ARTIFACT_MISSING",label)
        if sha(p)!=e:fail("FROZEN_ARTIFACT_HASH_DRIFT",label)
    if not BINDING.is_file():fail("SYSTEM_BINDING_MISSING")
    b=json.loads(BINDING.read_text("utf-8"))
    if b.get("schema")!="xiaoyu-locomo-blind-system-binding-v1":
        fail("SYSTEM_BINDING_SCHEMA_MISMATCH")
    if b.get("status")!="BOTH_PREDICTIONS_SEALED":
        fail("BOTH_PREDICTIONS_NOT_SEALED")
    if b.get("formal_confirmatory_authorized") is not False:
        fail("FORMAL_BOUNDARY_DRIFT")
    if b.get("membership_sha256")!=EXPECTED_MEMBERSHIP_SHA or b.get("blind_input_sha256")!=EXPECTED_INPUT_SHA:
        fail("BLIND_INPUT_BINDING_DRIFT")
    systems=b.get("systems") or {}
    if set(systems)!={"baseline","candidate"}:
        fail("SYSTEM_SET_MISMATCH")
    sealed={}
    for name in ("baseline","candidate"):
        x=systems[name]
        seal=ROOT/str(x.get("prediction_seal_path") or "")
        if not seal.is_file():fail("PREDICTION_SEAL_MISSING",name)
        actual=sha(seal)
        if actual!=x.get("prediction_seal_sha256"):fail("PREDICTION_SEAL_HASH_DRIFT",name)
        d=json.loads(seal.read_text("utf-8"))
        if d.get("schema")!="xiaoyu-locomo-blind-prediction-seal-v1":
            fail("PREDICTION_SEAL_SCHEMA_MISMATCH",name)
        if d.get("status")!="SEALED_BEFORE_GOLD":
            fail("PREDICTION_NOT_SEALED_BEFORE_GOLD",name)
        if d.get("system_role")!=name:fail("PREDICTION_ROLE_MISMATCH",name)
        if d.get("membership_sha256")!=EXPECTED_MEMBERSHIP_SHA or d.get("blind_input_sha256")!=EXPECTED_INPUT_SHA:
            fail("PREDICTION_INPUT_BINDING_DRIFT",name)
        if int(d.get("prediction_count",-1))!=200:
            fail("PREDICTION_COUNT_MISMATCH",name)
        if d.get("gold_access_before_seal") is not False:
            fail("GOLD_ACCESS_DECLARATION_INVALID",name)
        pred=ROOT/str(d.get("predictions_path") or "")
        if not pred.is_file():fail("PREDICTIONS_FILE_MISSING",name)
        if sha(pred)!=d.get("predictions_sha256"):fail("PREDICTIONS_HASH_DRIFT",name)
        sealed[name]={"prediction_seal_path":str(seal.relative_to(ROOT)).replace("\\","/"),"prediction_seal_sha256":actual,"predictions_sha256":d["predictions_sha256"]}
    return b,sealed

def main():
    ap=argparse.ArgumentParser();ap.add_argument("mode",choices=["check","authorize"]);args=ap.parse_args()
    b,sealed=validate()
    out={"schema":"xiaoyu-locomo-blind-gold-gate-v1","status":"READY_FOR_GOLD_SCORING","gold_plaintext_exposed":False,"systems":sealed}
    if args.mode=="authorize":
        auth={
          "schema":"xiaoyu-locomo-blind-gold-decode-authorization-v1",
          "status":"AUTHORIZED_AFTER_BOTH_PREDICTION_SEALS",
          "protocol_sha256":EXPECTED_PROTOCOL_SHA,
          "membership_sha256":EXPECTED_MEMBERSHIP_SHA,
          "blind_input_sha256":EXPECTED_INPUT_SHA,
          "gold_hash_seal_sha256":EXPECTED_GOLD_SEAL_SHA,
          "system_binding_sha256":sha(BINDING),
          "prediction_seals":sealed,
          "formal_confirmatory_authorized":False,
          "one_shot_selected_200_becomes_exposed_after_scoring":True,
        }
        AUTH.write_text(json.dumps(auth,ensure_ascii=False,indent=2)+"\n","utf-8")
        out["authorization_path"]=str(AUTH.relative_to(ROOT)).replace("\\","/")
        out["authorization_sha256"]=sha(AUTH)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
