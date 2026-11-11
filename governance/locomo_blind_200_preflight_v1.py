#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib,json
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
D=ROOT/"external"/"OmniMemEval"/"data"/"locomo"/"locomo10.json"
M=G/"LOCOMO_BLIND_200_MEMBERSHIP_V1.json"
I=G/"locomo_blind_200_input_v1.json"
S=G/"LOCOMO_BLIND_200_GOLD_HASH_SEAL_V1.json"
P=G/"LOCOMO_BLIND_200_PROTOCOL_V1.json"
OUT=G/"LOCOMO_BLIND_200_PREFLIGHT_V1.json"

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
stable=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
h=lambda b:hashlib.sha256(b).hexdigest()

m=json.loads(M.read_text("utf-8"))
i=json.loads(I.read_text("utf-8"))
s=json.loads(S.read_text("utf-8"))
p=json.loads(P.read_text("utf-8"))
raw=json.loads(D.read_text("utf-8"))
rawmap={str(x["sample_id"]):x for x in raw}
rows=m["rows"]
checks={}
checks["dataset_sha_match"]=sha(D)==m["dataset_sha256"]==i["dataset_sha256"]==s["dataset_sha256"]
checks["membership_200"]=len(rows)==200 and len({x["blind_id"] for x in rows})==200
checks["primary_180"]=sum(x["evaluation_role"]=="PRIMARY_MEMORY_GATE" for x in rows)==180
checks["diagnostic_20"]=sum(x["evaluation_role"]=="OPEN_DOMAIN_DIAGNOSTIC" for x in rows)==20
checks["category_counts"]=Counter(x["category"] for x in rows)==Counter({"1":60,"2":60,"3":20,"4":60})
checks["primary_category_counts"]=Counter(x["category"] for x in rows if x["evaluation_role"]=="PRIMARY_MEMORY_GATE")==Counter({"1":60,"2":60,"4":60})
checks["membership_hash_binding"]=sha(M)==i["membership_sha256"]==s["membership_sha256"]==p["bindings"]["membership_sha256"]
checks["input_hash_binding"]=sha(I)==p["bindings"]["blind_input_sha256"]
checks["seal_hash_binding"]=sha(S)==p["bindings"]["gold_hash_seal_sha256"]
checks["protocol_gold_closed"]=p["execution_boundary"]["gold_decode_allowed_now"] is False and p["execution_boundary"]["paid_execution_authorized_now"] is False
checks["one_shot"]=p["anti_overfit"]["one_shot"] is True and p["anti_overfit"]["do_not_tune_on_selected_200"] is True
forbidden={"answer","evidence","event_summary","observation","session_summary","adversarial_answer"}
def has_forbidden(x):
    if isinstance(x,dict):
        if any(str(k) in forbidden for k in x): return True
        return any(has_forbidden(v) for v in x.values())
    if isinstance(x,list): return any(has_forbidden(v) for v in x)
    return False
checks["blind_input_no_gold_keys"]=not has_forbidden(i)
checks["blind_input_flags"]=all(i.get(k) is False for k in ["contains_answer","contains_evidence","contains_event_summary","contains_observation","contains_session_summary"])
# Verify question hashes and gold hashes against raw dataset without emitting plaintext.
mr={(x["sample_id"],int(x["qa_index"])):x for x in rows}
question_ok=True
gold_ok=True
sealmap={x["blind_id"]:x["gold_answer_evidence_sha256"] for x in s["rows"]}
input_count=0
for sample in i["samples"]:
    sid=str(sample["sample_id"])
    for qv in sample["questions"]:
        input_count+=1
        idx=int(qv["qa_index"]); rawq=rawmap[sid]["qa"][idx]; r=mr[(sid,idx)]
        qh=h(str(rawq.get("question","")).encode("utf-8"))
        if qh!=r["question_sha256"] or qh!=qv["question_sha256"]: question_ok=False
        gh=h(stable({"answer":rawq.get("answer"),"evidence":rawq.get("evidence")}))
        if sealmap.get(r["blind_id"])!=gh: gold_ok=False
checks["blind_input_question_count_200"]=input_count==200
checks["question_hashes_exact"]=question_ok
checks["gold_hashes_exact_without_plaintext_output"]=gold_ok
checks["gold_seal_no_plaintext_fields"]=not has_forbidden(s)
checks["formal_boundary_preserved"]=p["execution_boundary"]["formal_confirmatory_authorized"] is False
out={"schema":"xiaoyu-locomo-blind-200-preflight-v1","checks":checks,"pass":all(checks.values()),"provider_calls":0,"gold_plaintext_emitted":False}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2))
raise SystemExit(0 if out["pass"] else 2)
