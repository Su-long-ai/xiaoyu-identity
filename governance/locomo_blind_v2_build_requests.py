#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib,importlib.util,json,pathlib,sqlite3,statistics
from collections import Counter

ROOT=pathlib.Path(__file__).resolve().parents[1]
G=ROOT/"governance"; LP=G/"lead_prechecks"
SNAP=G/"LOCOMO_BLIND_V2_RETRIEVAL_SNAPSHOT.json"
V5IN=G/"stagea_answerer_v5_full_inputs.json"
CAND=LP/"combined_safe_reference_frozen.py"
REQ=G/"LOCOMO_BLIND_V2_BASELINE_REQUESTS.json"
ROUTES=G/"LOCOMO_BLIND_V2_CANDIDATE_ROUTE_PLAN.json"
COST=G/"LOCOMO_BLIND_V2_ANSWER_COST_PROJECTION.json"

EXP_SNAP="c2b59224bbd06bf95dbc61e389c494f7b64ea40975e3db659c93acf9ffa35dff"
EXP_CAND="62ac33d950463c545366c46b6983aa626590f5f6a0635aa9ba2af0252d61e938"
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
if sha(SNAP)!=EXP_SNAP:raise SystemExit("retrieval snapshot drift")
if sha(CAND)!=EXP_CAND:raise SystemExit("candidate drift")
v5=json.loads(V5IN.read_text("utf-8"))
prefix=v5["rows"][0]["messages"][:-1]
if len(prefix)!=1 or prefix[0].get("role")!="system":raise SystemExit("V5 prefix shape drift")
prefix_hash=stable(prefix)
if any(stable(x["messages"][:-1])!=prefix_hash for x in v5["rows"]):raise SystemExit("V5 system not invariant")
system=prefix[0]["content"]

snap=json.loads(SNAP.read_text("utf-8"))
requests=[]
for x in snap["rows"]:
    lines=[]
    for i,m in enumerate(x["authorized_memories"],1):
        md=f"authority={m['authority']}"
        if m.get("timestamp"):md+=f" timestamp={m['timestamp']}"
        lines.append(f"[{i}] {md}\n{m['text']}")
    user="AUTHORIZED MEMORIES:\n"+("\n\n".join(lines) if lines else "(none)")+"\n\nQUESTION:\n"+x["question"]
    messages=[{"role":"system","content":system},{"role":"user","content":user}]
    requests.append({
      "blind_id":x["blind_id"],
      "sample_id":x["sample_id"],
      "question_sha256":x["question_sha256"],
      "authorized_memory_count":x["authorized_memory_count"],
      "messages":messages,
      "request_messages_sha256":stable(messages),
      "message_chars":sum(len(str(m["content"])) for m in messages),
    })
ids=[x["blind_id"] for x in requests]
if len(ids)!=200 or len(set(ids))!=200:raise SystemExit("request membership drift")
reqobj={
 "schema":"xiaoyu-locomo-blind-v2-baseline-requests-v1",
 "status":"FROZEN_PRE_EXECUTION_GOLD_FREE",
 "retrieval_snapshot_sha256":sha(SNAP),
 "v5_full_inputs_sha256":sha(V5IN),
 "v5_system_prefix_sha256":prefix_hash,
 "case_count":200,
 "model_visible_category":False,
 "gold_present":False,
 "rows":requests,
}
REQ.write_text(json.dumps(reqobj,ensure_ascii=False,indent=2)+"\n","utf-8")

spec=importlib.util.spec_from_file_location("combined_safe",CAND)
cand=importlib.util.module_from_spec(spec);spec.loader.exec_module(cand)
routes=[]
for x in snap["rows"]:
    r=cand.safe_direct_route({"question":x["question"],"authorized_memories":x["authorized_memories"]})
    routes.append({
      "blind_id":x["blind_id"],
      "routed":r is not None,
      "route_type":None if r is None else r.get("type"),
      "answer":None if r is None else r.get("answer"),
    })
routeobj={
 "schema":"xiaoyu-locomo-blind-v2-candidate-route-plan-v1",
 "status":"DETERMINISTIC_CANDIDATE_PRECOMPUTED_BEFORE_GOLD",
 "candidate_sha256":sha(CAND),
 "retrieval_snapshot_sha256":sha(SNAP),
 "case_count":200,
 "routed_count":sum(x["routed"] for x in routes),
 "route_type_counts":dict(Counter(x["route_type"] for x in routes if x["routed"])),
 "rows":routes,
 "provider_calls":0,
 "gold_read":False,
}
ROUTES.write_text(json.dumps(routeobj,ensure_ascii=False,indent=2)+"\n","utf-8")

# Empirical chars/token calibration from exact V5 Full messages + durable prompt tokens.
con=sqlite3.connect(G/"research_api_usage.sqlite3");con.row_factory=sqlite3.Row
ratios=[]; tok_by_cid={}
for row in con.execute("SELECT case_id,prompt_tokens FROM calls WHERE budget_scope='proxy:xiaoyu:stagea_grounded_answerer_v5_full' AND status='COMMITTED'"):
    tok_by_cid[row["case_id"]]=int(row["prompt_tokens"] or 0)
con.close()
for x in v5["rows"]:
    tok=tok_by_cid.get(x["case_id"])
    if tok:
        chars=sum(len(str(m["content"])) for m in x["messages"])
        ratios.append(tok/max(1,chars))
if len(ratios)!=51:raise SystemExit(f"V5 calibration coverage {len(ratios)}")
ratio_max=max(ratios);ratio_p95=sorted(ratios)[int(.95*(len(ratios)-1))]
chars=[x["message_chars"] for x in requests]
# Conservative token bound uses max observed V5 ratio plus 20% and also a hard 1 token/char ceiling.
estimated_prompt=sum(chars)*ratio_p95
conservative_prompt=min(sum(chars),sum(chars)*ratio_max*1.20)
# max completion fixed to V5 Full 128 per call (bound from manifest below).
manifest=json.loads((G/"STAGEA_GROUNDED_ANSWERER_V5_FULL.json").read_text("utf-8"))
max_out=int(manifest["paid_track"]["max_completion_tokens"])
conservative_out=200*max_out
policy=json.loads((G/"policy.json").read_text("utf-8"))
pricing=policy["budget"]["paid_research"]["pricing_cny_per_million"]
# Offpeak is current intended window; also compute peak worst-case.
def cost(inp,out,band):
    return inp/1e6*float(pricing["cache_miss"][band])+out/1e6*float(pricing["output"][band])
projection={
 "schema":"xiaoyu-locomo-blind-v2-answer-cost-projection-v1",
 "request_sha256":sha(REQ),
 "candidate_route_plan_sha256":sha(ROUTES),
 "case_count":200,
 "candidate_routed_count":routeobj["routed_count"],
 "baseline_deepseek_calls":200,
 "candidate_additional_deepseek_calls":0,
 "candidate_reuse_baseline_calls":200-routeobj["routed_count"],
 "candidate_deterministic_local_answers":routeobj["routed_count"],
 "message_chars_total":sum(chars),
 "message_chars_min":min(chars),"message_chars_max":max(chars),"message_chars_avg":sum(chars)/len(chars),
 "v5_prompt_token_per_char_p95":ratio_p95,
 "v5_prompt_token_per_char_max":ratio_max,
 "estimated_prompt_tokens_p95":estimated_prompt,
 "conservative_prompt_tokens":conservative_prompt,
 "max_completion_tokens_per_call":max_out,
 "conservative_completion_tokens":conservative_out,
 "cost_cny":{
   "off_peak_conservative_cache_miss":cost(conservative_prompt,conservative_out,"off_peak"),
   "peak_conservative_cache_miss":cost(conservative_prompt,conservative_out,"peak"),
 },
 "provider_calls_before_scoring":200,
 "judge_cost_not_included":True,
 "raw_gold_read":False,
 "formal_touched":False,
}
COST.write_text(json.dumps(projection,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({
 "requests_sha256":sha(REQ),
 "route_plan_sha256":sha(ROUTES),
 "cost_sha256":sha(COST),
 "route_count":routeobj["routed_count"],
 "route_types":routeobj["route_type_counts"],
 "message_chars_total":sum(chars),
 "estimated_prompt_tokens_p95":round(estimated_prompt),
 "conservative_prompt_tokens":round(conservative_prompt),
 "conservative_completion_tokens":conservative_out,
 "off_peak_cost_cny":projection["cost_cny"]["off_peak_conservative_cache_miss"],
 "peak_cost_cny":projection["cost_cny"]["peak_conservative_cache_miss"],
},ensure_ascii=False,indent=2))
