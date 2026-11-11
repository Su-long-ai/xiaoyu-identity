# -*- coding: utf-8 -*-
"""Zero-call compatibility audit: replay the 16 already-paid R49 public canary
provider receipts through receipt-bound R52 structural-v5 validation.
No provider/network calls and no confirmatory-user reads.
"""
from __future__ import annotations
import importlib.util, json, sys, tempfile
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
GOV=ROOT/"governance"
R52=GOV/"workspaces"/"fish-6534847e38ed48b6"
sys.path.insert(0,str(GOV))
sys.path.insert(0,str(R52))
import e2_r49_canary_runner as old
import r49_structural_v5 as v5
from r47_open_domain_memory_store_frozen import OpenDomainMemoryStore

manifest=old.load_manifest()
cases=old.case_map()
rows={x["case_id"]:x for x in manifest["case_rows"]}
order=list(manifest["tracks"]["halumem_semantic_transition_canary"]["case_ids"])

streams={}
details=[]
with tempfile.TemporaryDirectory(prefix="r52-v5-legacy-receipts-") as td:
    tdp=Path(td)
    for cid in order:
        row=rows[cid]; case=cases[cid]; stream=row["stream_key"]
        if stream not in streams:
            streams[stream]=OpenDomainMemoryStore(tdp/(stream.replace(":","_")+".sqlite3"))
        store=streams[stream]
        rec=json.loads(old.provider_receipt_path(cid).read_text("utf-8"))
        oldres=json.loads(old.result_path(cid).read_text("utf-8"))
        try:
            raw=json.loads(rec["response_text"])
            raw_outputs=raw.get("outputs")
        except Exception as e:
            raw_outputs=None
        source_results=[]
        all_v5_accept=True
        if not isinstance(raw_outputs,list) or len(raw_outputs)!=len(case["source_messages"]):
            all_v5_accept=False
            source_results.append({"error":"raw_output_cardinality_or_json"})
        else:
            built_rows=[]
            # Match the legacy canary's batch pre-state: build both source candidate
            # sets before mutating this pair's stream state.
            for msg,bind in zip(case["source_messages"],row["caller_binding"]):
                meta=v5.prior_candidates_from_r47(
                    store,str(msg["text"]),str(msg["role"]),int(bind["effective_at"]),
                    limit=6,return_metadata=True)
                built=v5.build_model_payload([{
                    "source_text":str(msg["text"]),
                    "source_role":str(msg["role"]),
                    "prior_candidates":meta["candidates"],
                    "candidate_pool_complete":meta["discovery_complete"],
                }],limit=6)
                built_rows.append((msg,bind,built))
            canonical_rows=[]
            for i,((msg,bind,built),out) in enumerate(zip(built_rows,raw_outputs)):
                try:
                    validated=v5.validate_response(
                        {"outputs":[out]},built["model_payload"],built["caller_binding"])
                    canonical_rows.append(validated["outputs"][0])
                    source_results.append({
                        "position":i,
                        "role":msg["role"],
                        "v5":"ACCEPTED",
                        "projection_mode":built["caller_binding"][0]["projection_mode"],
                        "binding_mode":built["caller_binding"][0]["binding_mode"],
                        "proposal_count":len(validated["outputs"][0].get("proposals") or []),
                    })
                except Exception as e:
                    all_v5_accept=False
                    canonical_rows.append(None)
                    source_results.append({
                        "position":i,
                        "role":msg["role"],
                        "v5":"REJECTED",
                        "projection_mode":built["caller_binding"][0]["projection_mode"],
                        "binding_mode":built["caller_binding"][0]["binding_mode"],
                        "error":type(e).__name__+":"+str(e),
                    })
            # Only advance compatibility-state when the complete legacy pair survives
            # v5. This avoids manufacturing partial state after an incompatible pair.
            if all_v5_accept:
                for (msg,bind,_built),out in zip(built_rows,canonical_rows):
                    candidates=[{
                        "claim_text":p["claim_text"],
                        "evidence_quote":p["evidence_quote"],
                        "relation":p["relation"],
                        "targets":p["target_ids"],
                    } for p in (out.get("proposals") or [])]
                    store.ingest(
                        bind["conversation_id"],bind["message_id"],bind["message_seq"],
                        bind["source_role"],msg["text"],bind["effective_at"],candidates)
        details.append({
            "case_id":cid,
            "stream_key":stream,
            "legacy_semantic_validation":oldres.get("semantic_validation"),
            "v5_pair_accepted":all_v5_accept,
            "sources":source_results,
        })
    for s in streams.values(): s.close()

legacy_accepted=sum(x["legacy_semantic_validation"]=="ACCEPTED" for x in details)
v5_accepted=sum(x["v5_pair_accepted"] for x in details)
legacy_accepted_v5=sum(x["legacy_semantic_validation"]=="ACCEPTED" and x["v5_pair_accepted"] for x in details)
out={
 "schema":"xiaoyu-r52-r49-v5-legacy-paid-receipt-compat-v1",
 "scope":"16 already-paid public R49 HaluMem pilot canary receipts only",
 "provider_calls":0,
 "confirmatory_users_read":0,
 "case_count":len(details),
 "legacy_accepted_cases":legacy_accepted,
 "v5_pair_accepted_cases":v5_accepted,
 "legacy_accepted_and_v5_accepted_cases":legacy_accepted_v5,
 "all_legacy_accepted_survive_v5":legacy_accepted_v5==legacy_accepted,
 "all_cases_survive_v5":v5_accepted==len(details),
 "details":details
}
path=GOV/"E2_R52_R49_V5_LEGACY_RECEIPT_COMPAT.json"
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({k:v for k,v in out.items() if k!="details"},ensure_ascii=False,indent=2))
for x in details:
    if not x["v5_pair_accepted"]:
        print(json.dumps(x,ensure_ascii=False))
