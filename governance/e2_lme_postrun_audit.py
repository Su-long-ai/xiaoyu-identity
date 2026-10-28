#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-paid, offline-only audit for the frozen E2 LongMemEval pilot.
No model/API calls. Gold is read only after all 46 paid cases are committed.
"""
from __future__ import annotations
import hashlib,json,re,sqlite3,statistics
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
MANIFEST=GOV/"E2_PILOT_EXECUTION_MANIFEST.json"
RUNTIME=GOV/"e2_pilot_runtime"
INPUTS=GOV/"e2_pilot_inputs"
DATA=ROOT/"external"/"OmniMemEval"/"data"/"longmemeval"/"longmemeval_s_cleaned.json"
LEDGER=GOV/"research_api_usage.sqlite3"
OUT=GOV/"E2_LME_PILOT_POSTRUN_AUDIT.json"

def sha(s):return hashlib.sha256(s.encode("utf-8")).hexdigest()
def norm(x):
    s=str(x or "").lower().strip()
    s=re.sub(r"[^\w\s.%$:/+-]+"," ",s,flags=re.UNICODE)
    s=re.sub(r"\s+"," ",s).strip()
    return s
def f1(a,b):
    aa=norm(a).split();bb=norm(b).split()
    if not aa or not bb:return float(aa==bb)
    ca=Counter(aa);cb=Counter(bb);inter=sum((ca&cb).values())
    if inter==0:return 0.0
    p=inter/len(aa);r=inter/len(bb)
    return 2*p*r/(p+r)
def gold_strings(g):
    if isinstance(g,list):return [str(x) for x in g]
    if isinstance(g,dict):return [json.dumps(g,ensure_ascii=False,sort_keys=True)]
    return [str(g or "")]
def parse_session_from_doc_id(doc_id):
    # lme:<dataset_index>:<session_ordinal>:<session_id>:<message_index>
    parts=str(doc_id).split(":")
    return parts[3] if len(parts)>=5 and parts[0]=="lme" else None

def main():
    m=json.loads(MANIFEST.read_text("utf-8"))
    ids=list(m["tracks"]["longmemeval_answer"]["case_ids"])
    assert len(ids)==46
    data=json.loads(DATA.read_text("utf-8"))
    assert len(data)==500

    con=sqlite3.connect(LEDGER);con.row_factory=sqlite3.Row
    # Discover a compatible calls table schema once.
    tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "calls" in tables, tables
    cols={r[1] for r in con.execute("PRAGMA table_info(calls)")}
    rows=[];ledger_bad=[];usage=Counter();status_counts=Counter()
    qtype=defaultdict(lambda:Counter())
    for cid in ids:
        rp=RUNTIME/(cid+".json")
        if not rp.is_file():
            ledger_bad.append({"case_id":cid,"reason":"missing_runtime_receipt"});continue
        rec=json.loads(rp.read_text("utf-8"))
        idx=int(cid.rsplit("-",1)[1]);goldrec=data[idx]
        payload=json.loads((INPUTS/(cid+".payload.json")).read_text("utf-8"))
        pred_obj=json.loads(rec["response_text"])["results"][0]
        pred=pred_obj.get("answer")
        pred_status=str(pred_obj.get("status") or "")
        status_counts[pred_status]+=1
        gvals=gold_strings(goldrec.get("answer",goldrec.get("golden_answer")))
        # Dataset currently uses answer; fall back to golden_answer if present.
        best_exact=max(int(norm(pred)==norm(g)) for g in gvals) if pred is not None else 0
        best_sub=max(int(norm(pred) in norm(g) or norm(g) in norm(pred))
                     for g in gvals if norm(g)) if pred is not None else 0
        best_f1=max(f1(pred,g) for g in gvals) if pred is not None else 0.0

        ans_sessions={str(x) for x in (goldrec.get("answer_session_ids") or [])}
        ctx_ids=[str(x.get("id")) for x in payload.get("context",[])]
        ctx_sessions={x for x in (parse_session_from_doc_id(d) for d in ctx_ids) if x is not None}
        answer_session_hit=bool(ans_sessions & ctx_sessions) if ans_sessions else None

        call_id=rec["call_id"]
        lr=con.execute("SELECT * FROM calls WHERE call_id=?",(call_id,)).fetchone()
        if lr is None:
            ledger_bad.append({"case_id":cid,"reason":"call_id_missing_in_ledger","call_id":call_id})
        else:
            checks={
              "status":str(lr["status"])=="COMMITTED" if "status" in cols else True,
              "scope":str(lr["budget_scope"])==rec["scope"] if "budget_scope" in cols else True,
              "actual_tokens":int(lr["actual_tokens"])==int(rec["usage"]["actual_tokens"]) if "actual_tokens" in cols else True,
            }
            if "response_text" in cols:
                checks["response_text"]=str(lr["response_text"])==rec["response_text"]
            if not all(checks.values()):
                ledger_bad.append({"case_id":cid,"reason":"ledger_receipt_mismatch","checks":checks})
        for k,v in rec["usage"].items():usage[k]+=int(v or 0)

        qt=str(goldrec.get("question_type") or "")
        qtype[qt]["n"]+=1;qtype[qt]["exact"]+=best_exact;qtype[qt]["substring"]+=best_sub
        qtype[qt]["resolved"]+=int(pred_status=="resolved")
        qtype[qt]["answer_session_hit"]+=int(answer_session_hit is True)
        rows.append({
          "case_id":cid,"dataset_index":idx,"question_type":qt,
          "status":pred_status,"prediction":pred,
          "gold":gvals,"normalized_exact":bool(best_exact),
          "normalized_substring":bool(best_sub),"token_f1":best_f1,
          "answer_session_hit":answer_session_hit,
          "context_count":len(ctx_ids),"evidence_ids":pred_obj.get("evidence_ids") or []
        })
    con.close()

    exact=sum(x["normalized_exact"] for x in rows)
    substring=sum(x["normalized_substring"] for x in rows)
    hit_rows=[x for x in rows if x["answer_session_hit"] is not None]
    hits=sum(x["answer_session_hit"] for x in hit_rows)
    hit_and_exact=sum(x["answer_session_hit"] and x["normalized_exact"] for x in hit_rows)
    miss_and_exact=sum((not x["answer_session_hit"]) and x["normalized_exact"] for x in hit_rows)
    f1s=[x["token_f1"] for x in rows]
    cache_den=usage["cache_hit_tokens"]+usage["cache_miss_tokens"]
    report={
      "schema":"xiaoyu-e2-lme-pilot-postrun-audit-v1",
      "scientific_claim_allowed":False,
      "confirmatory_calls":0,
      "cases_expected":46,"cases_audited":len(rows),
      "all_runtime_receipts_present":len(rows)==46,
      "ledger_mismatch_count":len(ledger_bad),"ledger_mismatches":ledger_bad,
      "usage":dict(usage),
      "cache_hit_rate":usage["cache_hit_tokens"]/cache_den if cache_den else 0.0,
      "status_counts":dict(status_counts),
      "deterministic_quality":{
        "normalized_exact":exact,"normalized_exact_rate":exact/len(rows),
        "normalized_substring":substring,"normalized_substring_rate":substring/len(rows),
        "mean_token_f1":statistics.mean(f1s),"median_token_f1":statistics.median(f1s)
      },
      "retrieval_diagnostic":{
        "cases_with_answer_session_labels":len(hit_rows),
        "answer_session_hit_at_7":hits,
        "answer_session_hit_rate":hits/len(hit_rows) if hit_rows else None,
        "hit_and_exact":hit_and_exact,
        "miss_and_exact":miss_and_exact,
        "exact_given_hit":hit_and_exact/hits if hits else None,
        "exact_given_miss":miss_and_exact/(len(hit_rows)-hits) if len(hit_rows)>hits else None
      },
      "by_question_type":{k:dict(v) for k,v in sorted(qtype.items())},
      "cases":rows,
      "notes":[
        "Gold is read only after all frozen paid calls were committed.",
        "No LLM judge is invoked because confirmatory calls are forbidden in the frozen pilot.",
        "Normalized exact/substring/token-F1 are engineering diagnostics, not official LongMemEval LLM-judge accuracy.",
        "answer_session_hit@7 diagnoses whether frozen lexical retrieval exposed any gold answer session; it does not prove the exact answer sentence was present."
      ]
    }
    assert report["all_runtime_receipts_present"] and report["ledger_mismatch_count"]==0
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("cases","ledger_mismatches","by_question_type")},
                     ensure_ascii=False,indent=2))
    print("BY_TYPE "+json.dumps(report["by_question_type"],ensure_ascii=False))

if __name__=="__main__":main()
