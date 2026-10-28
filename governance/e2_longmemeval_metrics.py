#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summarize already-committed E2 LongMemEval pilot receipts without API calls."""
from __future__ import annotations
import argparse,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
DATA=ROOT/"external"/"OmniMemEval"/"data"/"longmemeval"/"longmemeval_s_cleaned.json"

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def evaluate(limit=None):
    data=load(DATA)
    manifest=load(GOV/"E2_PILOT_EXECUTION_MANIFEST.json")
    case_ids=[str(x) for x in manifest["tracks"]["longmemeval_answer"]["case_ids"]]
    rows=[]
    for cid in case_ids:
        try:i=int(cid.rsplit("-",1)[1])
        except Exception:continue
        rp=GOV/"e2_pilot_runtime"/(cid+".json")
        pp=GOV/"e2_pilot_inputs"/(cid+".payload.json")
        if not rp.is_file() or not pp.is_file():
            continue
        rec=load(rp);payload=load(pp)
        if rec.get("status")!="COMMITTED":
            continue
        try: ans=json.loads(rec["response_text"])["results"][0]
        except Exception: ans={}
        gold=str(data[i]["answer"])
        got=ans.get("answer")
        ctx=payload.get("context") or []
        text="\n".join(str(x.get("text","")) for x in ctx)
        gold_in_context=gold.casefold() in text.casefold()
        exact=(got is not None and str(got).strip().casefold()==gold.strip().casefold())
        ev=ans.get("evidence_ids") or []
        byid={str(x.get("id")):x for x in ctx}
        ev_valid=bool(ev) and all(str(x) in byid for x in ev)
        usage=rec.get("usage") or {}
        if exact:
            failure="PASS"
        elif not gold_in_context:
            failure="RETRIEVAL_MISS"
        elif ans.get("status")=="unknown":
            failure="ANSWER_ABSTENTION_WITH_GOLD_IN_CONTEXT"
        else:
            failure="ANSWER_MISMATCH_WITH_GOLD_IN_CONTEXT"
        rows.append({
          "index":i,"case_id":cid,"question_type":data[i].get("question_type"),
          "question":data[i]["question"],"gold":gold,"answer":got,
          "status":ans.get("status"),"exact":exact,
          "gold_literal_in_context":gold_in_context,
          "context_records":len(ctx),"evidence_valid":ev_valid,
          "evidence_authorities":[byid[str(x)].get("authority") for x in ev if str(x) in byid],
          "failure_class":failure,
          "prompt_tokens":int(usage.get("prompt_tokens") or 0),
          "completion_tokens":int(usage.get("completion_tokens") or 0),
          "raw_tokens":int(usage.get("actual_tokens") or 0),
          "cache_hit_tokens":int(usage.get("cache_hit_tokens") or 0),
          "cache_miss_tokens":int(usage.get("cache_miss_tokens") or 0),
        })
        if limit and len(rows)>=limit:break
    n=len(rows);raw=sum(x["raw_tokens"] for x in rows);miss=sum(x["cache_miss_tokens"] for x in rows)
    comp=sum(x["completion_tokens"] for x in rows);hit=sum(x["cache_hit_tokens"] for x in rows)
    # Current off-peak DeepSeek V4.1-Flash-1017 prices in policy.
    cost=(hit/1e6*0.02)+(miss/1e6*1.0)+(comp/1e6*4.0)
    classes={}
    for x in rows:classes[x["failure_class"]]=classes.get(x["failure_class"],0)+1
    return {
      "schema":"xiaoyu-e2-lme-pilot-metrics-v1",
      "committed_cases":n,
      "exact_cases":sum(x["exact"] for x in rows),
      "exact_rate":round(sum(x["exact"] for x in rows)/n,6) if n else None,
      "evidence_valid_cases":sum(x["evidence_valid"] for x in rows),
      "gold_literal_in_context_cases":sum(x["gold_literal_in_context"] for x in rows),
      "failure_classes":classes,
      "raw_tokens":raw,"cache_miss_tokens":miss,"cache_hit_tokens":hit,
      "completion_tokens":comp,
      "raw_tokens_per_case":round(raw/n,2) if n else None,
      "cache_miss_tokens_per_case":round(miss/n,2) if n else None,
      "completion_tokens_per_case":round(comp/n,2) if n else None,
      "offpeak_cost_cny":round(cost,8),
      "offpeak_cost_cny_per_case":round(cost/n,8) if n else None,
      "rows":rows
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--limit",type=int)
    args=ap.parse_args()
    print(json.dumps(evaluate(args.limit),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
