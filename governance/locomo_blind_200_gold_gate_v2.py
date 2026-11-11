#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed LoCoMo blind-200 V2 gold authorization gate.

Before any gold scoring:
- raw locomo10.json must be absent locally;
- exact baseline + candidate system binding must exist;
- both prediction seals must bind exact V2 membership/input;
- each predictions file must contain exactly the 200 frozen blind IDs, once each;
- both seals must declare no gold access before sealing.

This gate never downloads or exposes gold. It only emits an authorization record
for a later one-shot scorer, which may then re-download the exact source SHA.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
RAW=ROOT/"external"/"OmniMemEval"/"data"/"locomo"/"locomo10.json"
PROTOCOL=G/"LOCOMO_BLIND_200_PROTOCOL_V2.json"
MEM=G/"LOCOMO_BLIND_200_MEMBERSHIP_V2.json"
INP=G/"locomo_blind_200_input_v2.json"
SEAL=G/"LOCOMO_BLIND_200_SOURCE_SEAL_V2.json"
PREFLIGHT=G/"LOCOMO_BLIND_200_PREFLIGHT_V2.json"
BINDING=G/"LOCOMO_BLIND_200_SYSTEM_BINDING_V2.json"
AUTH=G/"LOCOMO_BLIND_200_GOLD_DECODE_AUTHORIZATION_V2.json"

EXPECTED_PROTOCOL_SHA="b1912599f39984ba09f2676f58393bc6e66127614f34ccb12a60d1bc88a368e1"
EXPECTED_MEM_SHA="7785702d3136ce15330a32091b0ce605a257a4de89abc25ea091d08b783950ba"
EXPECTED_INPUT_SHA="57cbfc53ce0818933831e6b87b8a2c038922a423e533aae2ab2610525c69398c"
EXPECTED_SOURCE_SEAL_SHA="3bc5903416f9343b7b7b35edf014deb689ba7193d918d90b9657d207783a7188"
EXPECTED_RAW_SHA="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fail(reason,detail=None):
    out={"schema":"xiaoyu-locomo-blind-gold-gate-v2","status":"BLOCKED","reason":reason}
    if detail is not None:out["detail"]=detail
    print(json.dumps(out,ensure_ascii=False,indent=2));raise SystemExit(2)

def pred_rows(path:Path):
    d=json.loads(path.read_text("utf-8"))
    rows=d if isinstance(d,list) else d.get("rows")
    if not isinstance(rows,list):fail("PREDICTIONS_ROWS_MISSING",str(path))
    return rows

def validate():
    for p,e,label in [
      (PROTOCOL,EXPECTED_PROTOCOL_SHA,"protocol"),
      (MEM,EXPECTED_MEM_SHA,"membership"),
      (INP,EXPECTED_INPUT_SHA,"blind_input"),
      (SEAL,EXPECTED_SOURCE_SEAL_SHA,"source_seal"),
    ]:
        if not p.is_file():fail("FROZEN_ARTIFACT_MISSING",label)
        if sha(p)!=e:fail("FROZEN_ARTIFACT_HASH_DRIFT",label)
    if not PREFLIGHT.is_file():fail("PREFLIGHT_MISSING")
    pf=json.loads(PREFLIGHT.read_text("utf-8"))
    if pf.get("schema")!="xiaoyu-locomo-blind-200-preflight-v2" or pf.get("pass") is not True:
        fail("PREFLIGHT_NOT_PASS")
    if RAW.exists():fail("RAW_GOLD_PRESENT_PRESEAL",str(RAW))
    src=json.loads(SEAL.read_text("utf-8"))
    if src.get("raw_dataset_sha256")!=EXPECTED_RAW_SHA or src.get("per_case_gold_hashes_present") is not False:
        fail("SOURCE_SEAL_DRIFT")
    m=json.loads(MEM.read_text("utf-8"))
    expected_ids=[str(x["blind_id"]) for x in m.get("rows") or []]
    if len(expected_ids)!=200 or len(set(expected_ids))!=200:fail("FROZEN_MEMBERSHIP_ID_DRIFT")
    expected_set=set(expected_ids)
    if not BINDING.is_file():fail("SYSTEM_BINDING_MISSING")
    b=json.loads(BINDING.read_text("utf-8"))
    if b.get("schema")!="xiaoyu-locomo-blind-system-binding-v2":fail("SYSTEM_BINDING_SCHEMA_MISMATCH")
    if b.get("status")!="BOTH_PREDICTIONS_SEALED":fail("BOTH_PREDICTIONS_NOT_SEALED")
    if b.get("formal_confirmatory_authorized") is not False:fail("FORMAL_BOUNDARY_DRIFT")
    if b.get("membership_sha256")!=EXPECTED_MEM_SHA or b.get("blind_input_sha256")!=EXPECTED_INPUT_SHA:
        fail("SYSTEM_BINDING_INPUT_DRIFT")
    systems=b.get("systems") or {}
    if set(systems)!={"baseline","candidate"}:fail("SYSTEM_SET_MISMATCH")
    outsys={}
    for role in ("baseline","candidate"):
        spec=systems[role]
        sp=ROOT/str(spec.get("prediction_seal_path") or "")
        if not sp.is_file():fail("PREDICTION_SEAL_MISSING",role)
        if sha(sp)!=spec.get("prediction_seal_sha256"):fail("PREDICTION_SEAL_HASH_DRIFT",role)
        sd=json.loads(sp.read_text("utf-8"))
        if sd.get("schema")!="xiaoyu-locomo-blind-prediction-seal-v2":fail("PREDICTION_SEAL_SCHEMA_MISMATCH",role)
        if sd.get("status")!="SEALED_BEFORE_GOLD":fail("PREDICTION_STATUS_MISMATCH",role)
        if sd.get("system_role")!=role:fail("PREDICTION_ROLE_MISMATCH",role)
        if sd.get("membership_sha256")!=EXPECTED_MEM_SHA or sd.get("blind_input_sha256")!=EXPECTED_INPUT_SHA:
            fail("PREDICTION_INPUT_BINDING_DRIFT",role)
        if sd.get("gold_access_before_seal") is not False:fail("PREDICTION_GOLD_DECLARATION_INVALID",role)
        pp=ROOT/str(sd.get("predictions_path") or "")
        if not pp.is_file():fail("PREDICTIONS_FILE_MISSING",role)
        if sha(pp)!=sd.get("predictions_sha256"):fail("PREDICTIONS_HASH_DRIFT",role)
        rows=pred_rows(pp)
        ids=[str(x.get("blind_id") or "") for x in rows]
        if len(ids)!=200:fail("PREDICTION_COUNT_MISMATCH",role)
        if len(set(ids))!=200:fail("PREDICTION_ID_DUPLICATE",role)
        if set(ids)!=expected_set:fail("PREDICTION_ID_MEMBERSHIP_MISMATCH",role)
        if any(not isinstance(x.get("answer"),str) for x in rows):fail("PREDICTION_ANSWER_SCHEMA_MISMATCH",role)
        if int(sd.get("prediction_count",-1))!=200:fail("PREDICTION_SEAL_COUNT_MISMATCH",role)
        outsys[role]={"prediction_seal_path":str(sp.relative_to(ROOT)).replace("\\","/"),"prediction_seal_sha256":sha(sp),"predictions_sha256":sha(pp)}
    return b,outsys

def main():
    ap=argparse.ArgumentParser();ap.add_argument("mode",choices=["check","authorize"]);a=ap.parse_args()
    b,systems=validate()
    out={"schema":"xiaoyu-locomo-blind-gold-gate-v2","status":"READY_FOR_ONE_SHOT_GOLD_SCORING","gold_plaintext_exposed":False,"systems":systems}
    if a.mode=="authorize":
        auth={
          "schema":"xiaoyu-locomo-blind-gold-decode-authorization-v2",
          "status":"AUTHORIZED_AFTER_EXACT_DUAL_PREDICTION_SEAL",
          "protocol_sha256":EXPECTED_PROTOCOL_SHA,
          "membership_sha256":EXPECTED_MEM_SHA,
          "blind_input_sha256":EXPECTED_INPUT_SHA,
          "source_seal_sha256":EXPECTED_SOURCE_SEAL_SHA,
          "raw_dataset_sha256":EXPECTED_RAW_SHA,
          "system_binding_sha256":sha(BINDING),
          "prediction_seals":systems,
          "selected_200_becomes_exposed_after_scoring":True,
          "formal_confirmatory_authorized":False,
        }
        AUTH.write_text(json.dumps(auth,ensure_ascii=False,indent=2)+"\n","utf-8")
        out["authorization_path"]=str(AUTH.relative_to(ROOT)).replace("\\","/")
        out["authorization_sha256"]=sha(AUTH)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
