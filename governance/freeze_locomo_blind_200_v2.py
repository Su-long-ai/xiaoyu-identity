#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze LoCoMo blind-200 V2 from the GOLD-STRIPPED local source only.

V2 remedies V1 audit findings:
- fresh seed and excludes every V1-selected question;
- selection is made from a source that contains no gold fields;
- membership exposes no qa_index and no selection-rank hash;
- model-visible input exposes no category labels;
- no per-case gold hashes exist pre-seal;
- raw gold source is not required for selection or preflight.

Primary balancing rule:
- for each category 1/2/4, first take 4 hash-ranked items per conversation;
- then globally hash-rank the remaining eligible items in that category and
  add 20 more, giving 60 per category and at least 4 per category per conversation.
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
SOURCE_SEAL=G/"LOCOMO_BLIND_200_SOURCE_SEAL_V2.json"
PROTOCOL=G/"LOCOMO_BLIND_200_PROTOCOL_V2.json"

SAFE_SHA="57e6455dd56c1821e6ef88bd3afaa812cab15ec8de10d2d4014354650450b26d"
RAW_SHA="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
RAW_URL="https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
SEED="xiaoyu-locomo-blind-200-v2-20261030-fresh"
PRIMARY_CATS=("1","2","4")
PRIMARY_MIN_PER_SAMPLE=4
PRIMARY_TOTAL_PER_CATEGORY=60
DIAG_N=20

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
h=lambda s:hashlib.sha256(str(s).encode("utf-8")).hexdigest()
def rank(sid,idx,cat):return h(f"{SEED}|{sid}|{idx}|{cat}")
def blind_id(sid,idx,cat):return "locomo-b200v2-"+h(f"{SEED}|{sid}|{idx}|{cat}|blind")[:20]

if sha(SAFE)!=SAFE_SHA:raise SystemExit("gold-stripped source SHA drift")
src=json.loads(SAFE.read_text("utf-8"))
if src.get("raw_dataset_sha256")!=RAW_SHA:raise SystemExit("raw dataset binding drift")
samples=src.get("samples") or []
if len(samples)!=10:raise SystemExit("sample count drift")

# Exclude every V1-selected question by sample_id + question hash.
v1=json.loads(V1.read_text("utf-8"))
excluded={(str(x["sample_id"]),str(x["question_sha256"])) for x in v1["rows"]}
if len(excluded)!=200:raise SystemExit("V1 exclusion set drift")

chosen=[]
by_sample=defaultdict(list)
chosen_keys=set()

# Primary categories: minimum 4 per sample, then globally fill to 60 per category.
for cat in PRIMARY_CATS:
    remaining=[]
    for sample in samples:
        sid=str(sample["sample_id"]); local=[]
        for idx,q in enumerate(sample.get("qa") or []):
            if str(q.get("category"))!=cat:continue
            qh=h(q.get("question",""))
            if (sid,qh) in excluded:continue
            local.append((rank(sid,idx,cat),sid,idx,qh))
        local.sort()
        if len(local)<PRIMARY_MIN_PER_SAMPLE:
            raise SystemExit(f"insufficient V2 minimum pool {sid} cat={cat}: {len(local)}")
        for _,sid2,idx,qh in local[:PRIMARY_MIN_PER_SAMPLE]:
            key=(sid2,idx)
            chosen.append((sid2,idx,cat,"PRIMARY_MEMORY_GATE",qh))
            chosen_keys.add(key);by_sample[sid2].append(idx)
        remaining.extend(local[PRIMARY_MIN_PER_SAMPLE:])
    need=PRIMARY_TOTAL_PER_CATEGORY-PRIMARY_MIN_PER_SAMPLE*len(samples)
    if need<0:raise SystemExit("primary quota arithmetic invalid")
    remaining.sort()
    fill=[x for x in remaining if (x[1],x[2]) not in chosen_keys][:need]
    if len(fill)!=need:raise SystemExit(f"insufficient global fill cat={cat}: need={need} got={len(fill)}")
    for _,sid,idx,qh in fill:
        chosen.append((sid,idx,cat,"PRIMARY_MEMORY_GATE",qh))
        chosen_keys.add((sid,idx));by_sample[sid].append(idx)

# Category 3: diagnostic only, global deterministic selection.
pool=[]
for sample in samples:
    sid=str(sample["sample_id"])
    for idx,q in enumerate(sample.get("qa") or []):
        if str(q.get("category"))!="3":continue
        qh=h(q.get("question",""))
        if (sid,qh) in excluded:continue
        pool.append((rank(sid,idx,"3"),sid,idx,qh))
pool.sort()
fill=[x for x in pool if (x[1],x[2]) not in chosen_keys][:DIAG_N]
if len(fill)!=DIAG_N:raise SystemExit("insufficient V2 category-3 pool")
for _,sid,idx,qh in fill:
    chosen.append((sid,idx,"3","OPEN_DOMAIN_DIAGNOSTIC",qh))
    chosen_keys.add((sid,idx));by_sample[sid].append(idx)

if len(chosen)!=200 or len(chosen_keys)!=200:raise SystemExit("V2 selection size/duplicate drift")
rows=[]
for sid,idx,cat,role,qh in sorted(chosen,key=lambda x:(x[0],x[1])):
    rows.append({
      "blind_id":blind_id(sid,idx,cat),
      "sample_id":sid,
      "category":cat,
      "evaluation_role":role,
      "question_sha256":qh,
    })
if len({x["blind_id"] for x in rows})!=200:raise SystemExit("blind id collision")

mem={
 "schema":"xiaoyu-locomo-blind-membership-v2",
 "status":"FROZEN_ONE_SHOT",
 "generation":"V2_AFTER_V1_PREFREEZE_INVALIDATION",
 "raw_dataset_sha256":RAW_SHA,
 "gold_stripped_source_sha256":SAFE_SHA,
 "selection_seed":SEED,
 "excluded_v1_selected_question_count":200,
 "selection_uses_question_text":False,
 "selection_uses_answer":False,
 "selection_uses_evidence":False,
 "primary_categories":list(PRIMARY_CATS),
 "primary_min_per_sample_per_category":PRIMARY_MIN_PER_SAMPLE,
 "primary_total_per_category":PRIMARY_TOTAL_PER_CATEGORY,
 "open_domain_diagnostic_n":DIAG_N,
 "primary_n":180,"diagnostic_n":20,"total_n":200,
 "rows":rows,
}
MEM.write_text(json.dumps(mem,ensure_ascii=False,indent=2)+"\n","utf-8")

# Model-visible input intentionally omits category/evaluation role.
rowmap={(x["sample_id"],x["question_sha256"]):x for x in rows}
input_samples=[]
for sample in samples:
    sid=str(sample["sample_id"]);qs=[]
    for idx in sorted(set(by_sample.get(sid,[]))):
        q=sample["qa"][idx];qh=h(q.get("question",""));r=rowmap[(sid,qh)]
        qs.append({"blind_id":r["blind_id"],"question":q.get("question"),"question_sha256":qh})
    if qs:input_samples.append({"sample_id":sid,"conversation":sample.get("conversation"),"questions":qs})
inp={
 "schema":"xiaoyu-locomo-blind-input-v2",
 "status":"MODEL_VISIBLE_GOLD_AND_CATEGORY_STRIPPED",
 "raw_dataset_sha256":RAW_SHA,
 "membership_sha256":sha(MEM),
 "gold_stripped_source_sha256":SAFE_SHA,
 "contains_category":False,
 "contains_answer":False,"contains_evidence":False,
 "contains_event_summary":False,"contains_observation":False,"contains_session_summary":False,
 "samples":input_samples,
}
INP.write_text(json.dumps(inp,ensure_ascii=False,indent=2)+"\n","utf-8")

seal={
 "schema":"xiaoyu-locomo-blind-source-seal-v2",
 "status":"SOURCE_SHA_ONLY_NO_PER_CASE_GOLD_ORACLE",
 "raw_dataset_url":RAW_URL,
 "raw_dataset_sha256":RAW_SHA,
 "gold_stripped_source_sha256":SAFE_SHA,
 "membership_sha256":sha(MEM),
 "selected_n":200,
 "per_case_gold_hashes_present":False,
 "raw_gold_required_locally_before_prediction_seals":False,
 "raw_gold_redownload_allowed_only_after_gold_gate_authorization":True,
}
SOURCE_SEAL.write_text(json.dumps(seal,ensure_ascii=False,indent=2)+"\n","utf-8")

cats=Counter(x["category"] for x in rows)
primary=Counter(x["category"] for x in rows if x["evaluation_role"]=="PRIMARY_MEMORY_GATE")
per_sample=Counter(x["sample_id"] for x in rows)
per_sample_primary_cat=Counter((x["sample_id"],x["category"]) for x in rows if x["evaluation_role"]=="PRIMARY_MEMORY_GATE")
protocol={
 "schema":"xiaoyu-locomo-blind-200-protocol-v2",
 "status":"FROZEN_BEFORE_ANY_V2_BLIND_PREDICTION",
 "supersedes":"LOCOMO_BLIND_200_PROTOCOL_V1.json (invalidated before prediction)",
 "purpose":"One-shot prospective generalization gate after exposed HaluMem tuning.",
 "scientific_role":{
   "exposed_targeted_10":"DEBUG_REGRESSION_ONLY",
   "exposed_halumem_51qa":"DEV_REGRESSION_ONLY",
   "locomo_blind_200_v2":"ONE_SHOT_PROSPECTIVE_GENERALIZATION_GATE",
   "halumem_18_user_confirmatory":"FORMAL_CONFIRMATORY_ISOLATED",
 },
 "selection":{
   "seed":SEED,
   "fresh_vs_v1":True,
   "v1_selected_questions_excluded":200,
   "primary":"For each category 1/2/4, take 4 hash-ranked V1-unselected questions per conversation, then globally hash-fill 20 additional questions to reach 60/category.",
   "diagnostic":"20 category-3 globally hash-ranked from V1-unselected questions.",
   "category_5_excluded":True,
   "selection_content_blind":True,
   "counts_by_category":dict(sorted(cats.items())),
   "primary_counts_by_category":dict(sorted(primary.items())),
   "counts_by_sample":dict(sorted(per_sample.items())),
   "minimum_primary_per_sample_per_category":min(per_sample_primary_cat.values()),
 },
 "anti_overfit":{
   "one_shot":True,
   "do_not_tune_on_selected_200":True,
   "both_baseline_and_candidate_predictions_seal_before_gold":True,
   "selected_200_permanently_exposed_after_scoring":True,
   "unselected_locomo_questions_remain_reserve":True,
   "raw_gold_must_be_absent_from_local_workspace_during_prediction_phase":True,
   "no_per_case_gold_hash_oracle":True,
   "model_visible_category_labels":False,
 },
 "evaluation_design":{
   "baseline_binding":"PENDING_FROZEN_BASELINE",
   "candidate_binding":"PENDING_POST_DEV_CANDIDATE",
   "primary_n":180,
   "open_domain_diagnostic_n":20,
   "primary_metric":"paired LLM-judge accuracy over categories 1,2,4",
   "promotion_rule":{
     "candidate_primary_accuracy_must_not_be_lower_than_baseline":True,
     "candidate_primary_absolute_gain_pp_min":5.0,
     "no_primary_category_drop_pp_more_than":5.0,
     "open_domain_non_gating":True,
     "formal_confirmatory_auto_authorized":False,
   },
 },
 "execution_boundary":{
   "paid_execution_authorized_now":False,
   "gold_decode_allowed_now":False,
   "formal_confirmatory_authorized":False,
   "next_required_step":"Independent exact review, delete local raw gold source, freeze exact baseline and candidate, then execute both blind predictions from stripped input only.",
 },
 "bindings":{
   "gold_stripped_source":"governance/locomo_blind_source_v2_gold_stripped.json",
   "gold_stripped_source_sha256":SAFE_SHA,
   "membership":"governance/LOCOMO_BLIND_200_MEMBERSHIP_V2.json",
   "membership_sha256":sha(MEM),
   "blind_input":"governance/locomo_blind_200_input_v2.json",
   "blind_input_sha256":sha(INP),
   "source_seal":"governance/LOCOMO_BLIND_200_SOURCE_SEAL_V2.json",
   "source_seal_sha256":sha(SOURCE_SEAL),
   "freeze_script":"governance/freeze_locomo_blind_200_v2.py",
   "freeze_script_sha256":sha(Path(__file__)),
 },
}
PROTOCOL.write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({
 "status":protocol["status"],"membership_sha256":sha(MEM),"blind_input_sha256":sha(INP),
 "source_seal_sha256":sha(SOURCE_SEAL),"protocol_sha256":sha(PROTOCOL),
 "counts_by_category":dict(sorted(cats.items())),"counts_by_sample":dict(sorted(per_sample.items())),
 "minimum_primary_per_sample_per_category":min(per_sample_primary_cat.values()),
 "v1_overlap":len({(x["sample_id"],x["question_sha256"]) for x in rows}&excluded),
 "model_visible_category":False,"per_case_gold_hashes":False
},ensure_ascii=False,indent=2))
