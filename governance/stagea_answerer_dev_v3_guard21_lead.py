#!/usr/bin/env python3
from __future__ import annotations
import sys,json,pathlib,hashlib
from datetime import datetime

ROOT=pathlib.Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
WS=GOV/"workspaces"/"fish-15c16374cc7c4c2b"
for p in (str(GOV),str(GOV/"workspaces"/"fish-6534847e38ed48b6")):
    if p not in sys.path:sys.path.insert(0,p)
import stagea_answerer_dev_v3_build_inputs as v3
import r52_qa_sufficiency_v7 as qa

inp=json.loads((WS/"stagea_completeness_guard_inputs_v2.json").read_text("utf-8"))
gold=json.loads((WS/"stagea_completeness_guard_gold_v2.json").read_text("utf-8"))
qrows=json.loads((GOV/"budget50_halumem_dev_runtime_v1"/"QA_INPUTS_POST_SEAL.json").read_text("utf-8"))["rows"]
qmap={x["qa_case_id"]:x for x in qrows}
loc={}
for pp in (GOV/"budget50_halumem_dev_runtime_v1"/"predictions").glob("*.json"):
    pred=json.loads(pp.read_text("utf-8"))
    for li,sess in enumerate(pred.get("sessions") or []):
        for q in sess.get("questions") or []:
            loc[q["qa_case_id"]]=(pp,pred,li,sess)

allowed=set(gold["allowed_authorities"])
contexts={}
real_qids=sorted({x["qa_case_id"] for x in inp["real_requirements"]+inp["unknown_controls"]+inp["historical_upper_bound"]})
for qid in real_qids:
    pp,pred,li,sess=loc[qid]
    cp=GOV/"budget50_halumem_dev_runtime_v1"/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
    ctx,meta=v3.build_context(qmap[qid],pred,sess,cp)
    contexts[qid]={"context":ctx,"meta":meta}

def contains_group(rows,group):
    texts=[" ".join(str(x["text"]).casefold().split()) for x in rows]
    return any(any(str(tok).casefold() in t for tok in group) for t in texts)

checks=[]
for req in inp["real_requirements"]:
    ctx=contexts[req["qa_case_id"]]["context"]
    groups=[contains_group(ctx,g) for g in req["required_groups"]]
    checks.append({"id":req["qa_case_id"],"kind":req["kind"],
                   "passed":len(ctx)<=20 and all(x["authority"] in allowed for x in ctx) and all(groups),
                   "required_groups":groups,"context_count":len(ctx)})
for u in inp["unknown_controls"]:
    ctx=contexts[u["qa_case_id"]]["context"];sup=qa.select_supported(u["question"],ctx)
    checks.append({"id":u["qa_case_id"],"kind":"true_unknown",
                   "passed":len(ctx)<=20 and all(x["authority"] in allowed for x in ctx) and len(sup)==0,
                   "supported_count":len(sup),"context_count":len(ctx)})
for h in inp["historical_upper_bound"]:
    ctx=contexts[h["qa_case_id"]]["context"];target=datetime.strptime(h["target_date"],"%Y-%m-%d").date()
    ts=[datetime.fromisoformat(x["timestamp"]).date() if x.get("timestamp") else None for x in ctx]
    ok=all(t is not None and (t<target if h["relation"]=="before" else t<=target) for t in ts)
    checks.append({"id":h["qa_case_id"],"kind":"historical_upper_bound",
                   "passed":len(ctx)<=20 and all(x["authority"] in allowed for x in ctx) and ok,
                   "all_within_cutoff":ok,"context_count":len(ctx)})
for s in inp["synthetic_authority_controls"]:
    ctx=[x for x in s["rows"] if x["authority"] in allowed]
    if s["kind"]=="assistant_only_negative":
        sup=qa.select_supported(s["question"],ctx);ok=len(sup)==0;extra={"supported_count":len(sup)}
    else:
        ok=any(s["required_text_fragment"].casefold() in x["text"].casefold() for x in ctx);extra={}
    checks.append({"id":s["id"],"kind":s["kind"],"passed":ok,**extra})

out={"schema":"xiaoyu-stagea-answerer-v3-guard21-lead-v2",
     "builder_sha256":hashlib.sha256((GOV/"stagea_answerer_dev_v3_build_inputs.py").read_bytes()).hexdigest(),
     "inputs_sha256":hashlib.sha256((GOV/"stagea_answerer_dev_v3_inputs.json").read_bytes()).hexdigest(),
     "auditor_contract_correction_sha256":hashlib.sha256((WS/"stagea_completeness_guard_contract_correction_v2.json").read_bytes()).hexdigest(),
     "n":len(checks),"passed":sum(bool(x["passed"]) for x in checks),
     "failed":[x for x in checks if not x["passed"]],"checks":checks,
     "provider_calls":0,"formal_confirmatory_reads":0}
out["pass"]=out["passed"]==out["n"]
(GOV/"STAGEA_ANSWERER_DEV_V3_GUARD21_LEAD.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({"n":out["n"],"passed":out["passed"],"failed":out["failed"],"pass":out["pass"],
                  "builder_sha256":out["builder_sha256"],"inputs_sha256":out["inputs_sha256"]},ensure_ascii=False,indent=2))
raise SystemExit(0 if out["pass"] else 2)
