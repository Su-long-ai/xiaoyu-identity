#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent recomputation preflight for LoCoMo blind-200 V2.

Does not import or call the freeze script. Recomputes the deterministic membership
from the gold-stripped source and V1 exclusion set, then compares exact selected
(sample_id, question_sha256, category, role, blind_id) rows.
"""
from __future__ import annotations
import hashlib,json
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
SAFE=G/"locomo_blind_source_v2_gold_stripped.json"
V1=G/"LOCOMO_BLIND_200_MEMBERSHIP_V1.json"
MEM=G/"LOCOMO_BLIND_200_MEMBERSHIP_V2.json"
INP=G/"locomo_blind_200_input_v2.json"
SEAL=G/"LOCOMO_BLIND_200_SOURCE_SEAL_V2.json"
PROTOCOL=G/"LOCOMO_BLIND_200_PROTOCOL_V2.json"
OUT=G/"LOCOMO_BLIND_200_PREFLIGHT_V2.json"

SAFE_SHA="57e6455dd56c1821e6ef88bd3afaa812cab15ec8de10d2d4014354650450b26d"
RAW_SHA="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
SEED="xiaoyu-locomo-blind-200-v2-20261030-fresh"
PRIMARY_CATS=("1","2","4")
MIN=4
TOTAL=60
DIAG=20

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
h=lambda s:hashlib.sha256(str(s).encode("utf-8")).hexdigest()
rank=lambda sid,idx,cat:h(f"{SEED}|{sid}|{idx}|{cat}")
bid=lambda sid,idx,cat:"locomo-b200v2-"+h(f"{SEED}|{sid}|{idx}|{cat}|blind")[:20]

safe=json.loads(SAFE.read_text("utf-8"))
v1=json.loads(V1.read_text("utf-8"))
mem=json.loads(MEM.read_text("utf-8"))
inp=json.loads(INP.read_text("utf-8"))
seal=json.loads(SEAL.read_text("utf-8"))
protocol=json.loads(PROTOCOL.read_text("utf-8"))
samples=safe["samples"]
excluded={(str(x["sample_id"]),str(x["question_sha256"])) for x in v1["rows"]}

expected=[]
selected_idx=set()
for cat in PRIMARY_CATS:
    rem=[]
    for sample in samples:
        sid=str(sample["sample_id"]); local=[]
        for idx,q in enumerate(sample["qa"]):
            if str(q.get("category"))!=cat:continue
            qh=h(q.get("question",""))
            if (sid,qh) in excluded:continue
            local.append((rank(sid,idx,cat),sid,idx,qh))
        local.sort()
        if len(local)<MIN:raise SystemExit(f"independent preflight insufficient pool {sid}/{cat}")
        for _,sid2,idx,qh in local[:MIN]:
            expected.append((sid2,idx,cat,"PRIMARY_MEMORY_GATE",qh))
            selected_idx.add((sid2,idx))
        rem.extend(local[MIN:])
    rem.sort()
    need=TOTAL-MIN*len(samples)
    fill=[x for x in rem if (x[1],x[2]) not in selected_idx][:need]
    if len(fill)!=need:raise SystemExit(f"independent preflight fill drift {cat}")
    for _,sid,idx,qh in fill:
        expected.append((sid,idx,cat,"PRIMARY_MEMORY_GATE",qh))
        selected_idx.add((sid,idx))

diag=[]
for sample in samples:
    sid=str(sample["sample_id"])
    for idx,q in enumerate(sample["qa"]):
        if str(q.get("category"))!="3":continue
        qh=h(q.get("question",""))
        if (sid,qh) in excluded:continue
        diag.append((rank(sid,idx,"3"),sid,idx,qh))
diag.sort()
fill=[x for x in diag if (x[1],x[2]) not in selected_idx][:DIAG]
if len(fill)!=DIAG:raise SystemExit("independent diagnostic fill drift")
for _,sid,idx,qh in fill:
    expected.append((sid,idx,"3","OPEN_DOMAIN_DIAGNOSTIC",qh))
    selected_idx.add((sid,idx))

expected_rows=[{
  "blind_id":bid(sid,idx,cat),
  "sample_id":sid,
  "category":cat,
  "evaluation_role":role,
  "question_sha256":qh,
} for sid,idx,cat,role,qh in sorted(expected,key=lambda x:(x[0],x[1]))]

checks={}
checks["safe_source_sha"]=sha(SAFE)==SAFE_SHA and safe.get("raw_dataset_sha256")==RAW_SHA
checks["exact_membership_recomputed"]=expected_rows==mem.get("rows")
checks["membership_count"]=len(expected_rows)==len(mem.get("rows") or [])==200
checks["v1_overlap_zero"]=len({(x["sample_id"],x["question_sha256"]) for x in expected_rows}&excluded)==0
checks["category_counts"]=Counter(x["category"] for x in expected_rows)==Counter({"1":60,"2":60,"3":20,"4":60})
checks["primary_counts"]=Counter(x["category"] for x in expected_rows if x["evaluation_role"]=="PRIMARY_MEMORY_GATE")==Counter({"1":60,"2":60,"4":60})
per=Counter((x["sample_id"],x["category"]) for x in expected_rows if x["evaluation_role"]=="PRIMARY_MEMORY_GATE")
checks["primary_min_per_sample_category"]=min(per.values())>=4 and len(per)==30
checks["blind_ids_unique"]=len({x["blind_id"] for x in expected_rows})==200

# Inspect model-visible input recursively. Exact forbidden keys, plus category/role.
forbidden={"answer","evidence","event_summary","observation","session_summary","adversarial_answer","category","evaluation_role"}
def badkeys(x):
    if isinstance(x,dict):
        out=[str(k) for k in x if str(k) in forbidden]
        for v in x.values():out.extend(badkeys(v))
        return out
    if isinstance(x,list):
        out=[]
        for v in x:out.extend(badkeys(v))
        return out
    return []
checks["model_input_forbidden_keys_absent"]=not badkeys(inp)
checks["model_input_flags"]=all(inp.get(k) is False for k in [
 "contains_category","contains_answer","contains_evidence","contains_event_summary","contains_observation","contains_session_summary"])

# Exact blind ID/question correspondence between membership and model input.
m_by_id={x["blind_id"]:x for x in expected_rows}
seen=[]
question_ok=True
for sample in inp.get("samples") or []:
    sid=str(sample["sample_id"])
    for q in sample.get("questions") or []:
        blind=str(q["blind_id"]);seen.append(blind)
        if blind not in m_by_id:question_ok=False;continue
        m=m_by_id[blind]
        if m["sample_id"]!=sid:question_ok=False
        if h(q.get("question",""))!=m["question_sha256"] or q.get("question_sha256")!=m["question_sha256"]:question_ok=False
checks["model_input_exact_200_unique_ids"]=len(seen)==200 and len(set(seen))==200 and set(seen)==set(m_by_id)
checks["model_input_question_hashes"]=question_ok
checks["membership_binding"]=inp.get("membership_sha256")==sha(MEM)==seal.get("membership_sha256")==protocol["bindings"]["membership_sha256"]
checks["input_binding"]=protocol["bindings"]["blind_input_sha256"]==sha(INP)
checks["source_seal_binding"]=protocol["bindings"]["source_seal_sha256"]==sha(SEAL)
checks["no_per_case_gold_oracle"]=seal.get("per_case_gold_hashes_present") is False and not any("gold_answer" in json.dumps(x,ensure_ascii=False) for x in [mem,inp,seal,protocol])
checks["formal_boundary"]=protocol["execution_boundary"]["formal_confirmatory_authorized"] is False
checks["paid_closed"]=protocol["execution_boundary"]["paid_execution_authorized_now"] is False and protocol["execution_boundary"]["gold_decode_allowed_now"] is False

out={"schema":"xiaoyu-locomo-blind-200-preflight-v2","status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"pass":all(checks.values()),"provider_calls":0,"raw_gold_read":False,"gold_plaintext_emitted":False}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2))
raise SystemExit(0 if out["pass"] else 2)
