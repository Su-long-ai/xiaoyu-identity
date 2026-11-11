#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execute/recover the 16-case Stage-A grounded answerer tuning tranche.

No benchmark gold/reference/evidence is read here. Inputs are already frozen.
Any UNKNOWN/RESERVED durable outcome is no-retry and aborts the tranche.
"""
from __future__ import annotations
import argparse,hashlib,json,pathlib,sqlite3,urllib.request,urllib.error,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
GOV=ROOT/"governance"
MANIFEST=GOV/"STAGEA_GROUNDED_ANSWERER_DEV_V1.json"
INPUTS=GOV/"stagea_answerer_dev_v1_inputs.json"
LEDGER=GOV/"research_api_usage.sqlite3"
RUNTIME=GOV/"stagea_answerer_dev_v1_runtime"
RECEIPTS=RUNTIME/"receipts"
PROGRESS=RUNTIME/"progress.json"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def load(p): return json.loads(Path(p).read_text("utf-8"))
def atomic(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True); q=p.with_suffix(p.suffix+".tmp")
    q.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8");q.replace(p)

def manifest():
    m=load(MANIFEST)
    if m.get("schema")!="xiaoyu-stagea-grounded-answerer-dev-v1" or m.get("status")!="TUNING_EXECUTION_AUTHORIZED":
        raise RuntimeError("manifest not executable")
    if sha(Path(__file__))!=m["implementation"]["runner_sha256"]: raise RuntimeError("runner byte drift")
    if sha(INPUTS)!=m["inputs_sha256"]: raise RuntimeError("inputs byte drift")
    return m

def ledger_row(cid):
    con=sqlite3.connect(LEDGER);con.row_factory=sqlite3.Row
    try:
        r=con.execute("""SELECT call_id,status,budget_scope,prompt_tokens,completion_tokens,actual_tokens,
        cache_hit_tokens,cache_miss_tokens,response_text,response_sha256,created_at,finished_at,error_class
        FROM calls WHERE case_id=? ORDER BY created_at DESC LIMIT 1""",(cid,)).fetchone()
    finally: con.close()
    return dict(r) if r else None

def receipt_path(cid): return RECEIPTS/(cid+".json")

def validate_existing(m,row,inp):
    if row.get("status")!="COMMITTED": raise RuntimeError(f"{inp['case_id']} durable {row.get('status')}; retry forbidden")
    text=row.get("response_text")
    if not isinstance(text,str) or hashlib.sha256(text.encode()).hexdigest()!=row.get("response_sha256"):
        raise RuntimeError("durable response hash mismatch")
    return text

def parse_answer(text):
    try: obj=json.loads(text)
    except Exception as e: raise RuntimeError("FORMAT_REJECTED:invalid_json") from e
    if not isinstance(obj,dict) or set(obj)!={"answer"} or not isinstance(obj.get("answer"),str):
        raise RuntimeError("FORMAT_REJECTED:expected_exact_answer_object")
    ans=" ".join(obj["answer"].strip().split())
    if not ans: raise RuntimeError("FORMAT_REJECTED:empty_answer")
    if len(ans)>240: raise RuntimeError("FORMAT_REJECTED:answer_too_long")
    return ans

def preflight():
    m=manifest(); d=load(INPUTS)
    ids=[x["case_id"] for x in d["rows"]]
    if ids!=m["paid_track"]["case_ids"] or len(ids)!=16 or len(set(ids))!=16:
        raise RuntimeError("case membership drift")
    prefix=stable(d["rows"][0]["messages"][:-1])
    if prefix!=m["paid_track"]["invariant_prefix_sha256"]: raise RuntimeError("prefix drift")
    for x in d["rows"]:
        if stable(x["messages"][:-1])!=prefix: raise RuntimeError("noninvariant system prefix")
        if stable(x["messages"])!=x["request_messages_sha256"]: raise RuntimeError("request hash drift")
    prior={}
    for cid in ids:
        r=ledger_row(cid)
        if r: prior[cid]=r["status"]
    return {"cases":16,"prior":prior,"provider_calls":0,"scope":m["paid_track"]["scope"],
            "prompt_contains_gold":False,"formal_confirmatory_authorized":False}

def execute():
    m=manifest(); d=load(INPUTS); track=m["paid_track"]
    rows=[] if not PROGRESS.exists() else load(PROGRESS).get("rows",[])
    done={x["case_id"] for x in rows}
    for inp in d["rows"]:
        cid=inp["case_id"]
        if cid in done: continue
        rp=receipt_path(cid); durable=ledger_row(cid)
        if durable is not None:
            text=validate_existing(m,durable,inp)
            ans=parse_answer(text)
            rec={"case_id":cid,"qa_case_id":inp["qa_case_id"],"answer":ans,
                 "response_sha256":durable["response_sha256"],"call_id":durable["call_id"],
                 "recovered":True,"selection_gold_unknown":inp["selection_gold_unknown"],
                 "selection_label":inp["selection_label"]}
            atomic(rp,rec);rows.append(rec);atomic(PROGRESS,{"schema":"xiaoyu-stagea-answerer-progress-v1","rows":rows})
            continue
        body={"model":__import__("model_adapter").load_provider(ROOT)["model"],
              "messages":inp["messages"],"max_tokens":int(track["max_completion_tokens"]),
              "stream":False,"thinking":{"type":"disabled"},"reasoning_effort":"none",
              "temperature":0.0,"top_p":1.0,"response_format":track["response_format"]}
        req=urllib.request.Request(
            "http://127.0.0.1:18083/v1/chat/completions",
            data=json.dumps(body,ensure_ascii=False).encode(),method="POST",
            headers={"Content-Type":"application/json","Authorization":"Bearer local-budget-proxy:xiaoyu",
                     "X-XiaoYu-Research-Run":"stagea_grounded_answerer_dev_v1",
                     "X-XiaoYu-Case-ID":cid})
        try:
            with urllib.request.urlopen(req,timeout=120) as f: payload=json.loads(f.read().decode())
        except urllib.error.HTTPError as e:
            msg=e.read().decode("utf-8","replace"); raise RuntimeError(f"HTTP_{e.code}:{msg[:800]}") from e
        durable=ledger_row(cid)
        if durable is None or durable.get("status")!="COMMITTED":
            raise RuntimeError(f"{cid}: provider returned without COMMITTED ledger")
        content=str(payload["choices"][0]["message"]["content"])
        if content!=durable.get("response_text"): raise RuntimeError("proxy/ledger response drift")
        ans=parse_answer(content)
        rec={"case_id":cid,"qa_case_id":inp["qa_case_id"],"answer":ans,
             "response_sha256":durable["response_sha256"],"call_id":durable["call_id"],
             "recovered":False,"selection_gold_unknown":inp["selection_gold_unknown"],
             "selection_label":inp["selection_label"],
             "usage":payload.get("usage")}
        atomic(rp,rec);rows.append(rec);atomic(PROGRESS,{"schema":"xiaoyu-stagea-answerer-progress-v1","rows":rows})
    if len(rows)!=16: raise RuntimeError("progress not 16")
    result={"schema":"xiaoyu-stagea-grounded-answerer-dev-results-v1","status":"ANSWERER_TRANCHE_COMPLETE",
            "rows":rows,"provider_call_cap":16,"formal_confirmatory_authorized":False}
    atomic(RUNTIME/"results.json",result)
    return {"completed":16,"unknown_controls":sum(x["selection_gold_unknown"] for x in rows),
            "provider_call_cap":16}

def status():
    m=manifest(); d=load(INPUTS); st={}
    for x in d["rows"]:
        r=ledger_row(x["case_id"])
        st[x["case_id"]]=r["status"] if r else "NOT_CALLED"
    return st

def main():
    ap=argparse.ArgumentParser();ap.add_argument("action",choices=["preflight","execute","status"],default="preflight",nargs="?")
    a=ap.parse_args()
    try:
        out=preflight() if a.action=="preflight" else execute() if a.action=="execute" else status()
        print(json.dumps({"ok":True,"action":a.action,"result":out},ensure_ascii=False,indent=2))
    except Exception as e:
        print(json.dumps({"ok":False,"action":a.action,"error":type(e).__name__+":"+str(e)},ensure_ascii=False,indent=2))
        raise SystemExit(2)
if __name__=="__main__": main()
