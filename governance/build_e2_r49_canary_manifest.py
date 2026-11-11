#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the hash-bound 16-case R49 supplemental E2 canary manifest.

Zero provider calls. The original E2 execution manifest is ancestry-only and is
never modified by this builder.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
PROTOCOL=GOV/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
PRIMARY=GOV/"E2_PILOT_EXECUTION_MANIFEST.json"
PAIR=GOV/"E2_HALUMEM_PAIR_SOURCE_CANDIDATE.json"
PROJECTION=GOV/"E2_R49_CANARY_TOKEN_PROJECTION.json"
CONTRACT=GOV/"E2_R49_SEMANTIC_CONTRACT_FROZEN.py"
STORE=GOV/"E2_R47_OPEN_DOMAIN_MEMORY_STORE_FROZEN.py"
RUNNER=GOV/"e2_r49_canary_runner.py"
OUT=GOV/"E2_R49_CANARY_MANIFEST.json"

ACCEPTED_SUBMISSION="sub-47b634e54ee84645"
ACCEPTED_REVIEW="review-5f18d40a1e5448b9"
CONTRACT_SHA="79218dc8960025bc7e8859a140fc760aab28fe16fb3140e62fe8619dfb4648c3"
STORE_SHA="44d41231dae573dbc360b62a8144ebe4b929808a72dc7197705ee26a704092f9"
PREEXEC_SHA="31ede7e69e05d8524b3087bfa49de01ae4b8118df2d6e0509f24b51fa485368b"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def write(path,obj):
    with Path(path).open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")

def main():
    if sha(CONTRACT)!=CONTRACT_SHA:raise RuntimeError("accepted R49 contract drift")
    if sha(STORE)!=STORE_SHA:raise RuntimeError("accepted R47 store drift")
    projection=json.loads(PROJECTION.read_text("utf-8"))
    case_ids=list(projection["canary16"]["case_ids"])
    if len(case_ids)!=16 or len(set(case_ids))!=16:raise RuntimeError("bad canary case set")
    pair=json.loads(PAIR.read_text("utf-8"));byid={x["case_id"]:x for x in pair["cases"]}
    # Bind to the independently accepted pre-exec ordering/caller metadata.
    workspace=GOV/"workspaces"/"fish-6f2d9a75c94f4185"
    preexec=workspace/"R49_PILOT_PREEXEC_MANIFEST.json"
    if not preexec.is_file() or sha(preexec)!=PREEXEC_SHA:
        raise RuntimeError("accepted R49 preexec manifest unavailable/drifted")
    pm=json.loads(preexec.read_text("utf-8"))
    rows_by={x["case_id"]:x for x in pm["cases"]}
    rows=[]
    for cid in case_ids:
        if cid not in byid or cid not in rows_by:raise RuntimeError("canary case missing")
        row=rows_by[cid]
        if stable([x["text"] for x in byid[cid]["source_messages"]])!=row["source_texts_sha256"]:
            raise RuntimeError("canary source hash mismatch")
        rows.append(row)
    # Preserve original full-pilot order, not the projection file grouping order by accident.
    order={x["case_id"]:i for i,x in enumerate(pm["cases"])}
    rows.sort(key=lambda x:order[x["case_id"]])
    case_ids=[x["case_id"] for x in rows]

    # The frozen semantic prefix is the only invariant model message.
    ns={}
    exec(CONTRACT.read_text("utf-8"),ns)
    system=ns["SYSTEM_PROMPT"]
    prefix=[{"role":"system","content":system}]
    manifest={
      "schema":"xiaoyu-e2-supplemental-execution-manifest-v1",
      "status":"FROZEN_BEFORE_EXECUTION",
      "paid_execution_authorized":True,
      "scientific_claim_allowed":False,
      "confirmatory_execution_allowed":False,
      "protocol_sha256":sha(PROTOCOL),
      "split_manifest_sha256":sha(SPLIT),
      "original_execution_manifest_sha256":sha(PRIMARY),
      "benchmark_pilot_hard_cap_tokens":1000000,
      "supplemental_scope_hard_cap_tokens":50000,
      "accepted_contract":{
        "submission_id":ACCEPTED_SUBMISSION,
        "review_id":ACCEPTED_REVIEW,
        "decision":"ACCEPT_E1",
        "decision_boundary":"pre-execution contract only; no E2/product claim",
        "contract_path":"governance/E2_R49_SEMANTIC_CONTRACT_FROZEN.py",
        "contract_sha256":sha(CONTRACT),
        "r47_store_path":"governance/E2_R47_OPEN_DOMAIN_MEMORY_STORE_FROZEN.py",
        "r47_store_sha256":sha(STORE),
        "preexec_manifest_sha256":PREEXEC_SHA
      },
      "pair_source_artifact_sha256":sha(PAIR),
      "token_projection_path":"governance/E2_R49_CANARY_TOKEN_PROJECTION.json",
      "token_projection_sha256":sha(PROJECTION),
      "runner_path":"governance/e2_r49_canary_runner.py",
      "runner_sha256":sha(RUNNER),
      "warmup":{"serial_real_cases_per_scope":2,"synthetic_paid_warmup_forbidden":True},
      "tracks":{
        "halumem_semantic_transition_canary":{
          "scope":"proxy:xiaoyu:e2_halumem_semantic_transition_pilot_v1",
          "execution_status":"READY",
          "case_ids":case_ids,
          "case_count":len(case_ids),
          "max_completion_tokens":768,
          "response_format":{"type":"json_object"},
          "invariant_prefix_messages":prefix,
          "invariant_prefix_sha256":stable(prefix),
          "stream_count":4,
          "serial_within_stream":True,
          "original_647_case_set_unchanged":True,
          "confirmatory_records_touched":0
        }
      },
      "case_rows":rows,
      "case_rows_sha256":stable(rows),
      "budget_projection":{
        "full_647_safe":False,
        "canary16_source_only_plus_completion_cap":projection["canary16"]["source_only_plus_768_completion_cap"],
        "canary16_schema_max_plus_completion_cap":projection["canary16"]["schema_max_plus_768_completion_cap"],
        "scope_raw_token_cap":50000,
        "scope_call_cap":16
      },
      "known_nonblocking_p2":{
        "issue":"generic standalone now can over-abstain when only quarantined/ineligible prior history exists",
        "independent_holdout":"56/64; quarantined_only_new 0/8; forbidden forged targets rejected 80/80",
        "effect":"recall/usability loss, not authority mutation",
        "must_remain_visible_in_canary_report":True
      },
      "nonclaims":[
        "No HaluMem semantic quality has been established by this freeze.",
        "Canary results cannot support E2 acceptance.",
        "The remaining 631 extraction anchors are not authorized by this manifest.",
        "HaluMem QA and confirmatory users remain locked."
      ]
    }
    write(OUT,manifest)
    print(json.dumps({
      "manifest":str(OUT),"sha256":sha(OUT),"case_count":len(case_ids),
      "scope":manifest["tracks"]["halumem_semantic_transition_canary"]["scope"],
      "prefix_sha256":manifest["tracks"]["halumem_semantic_transition_canary"]["invariant_prefix_sha256"],
      "runner_sha256":manifest["runner_sha256"],
      "projection_sha256":manifest["token_projection_sha256"]
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
