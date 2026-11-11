#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execute/recover the formal post-seal V5 answer overlay.

This runner never reads HaluMem dataset files or gold. It consumes only the
sealed per-stream V5 answer inputs generated after the Recovery-V2 prediction
seal. UNKNOWN/RESERVED durable outcomes are no-retry.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3,sys,urllib.error,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
GOV=ROOT/"governance"
PROTOCOL=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_V1.json"
PROTOCOL_FREEZE=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_FREEZE_V1.json"
EXEC_FREEZE=GOV/"FORMAL_HALUMEM_V5_ANSWER_EXECUTION_FREEZE.json"
FORMAL_RUNTIME=GOV/"halumem_confirmatory_runtime_v2"
INPUT_SEAL=FORMAL_RUNTIME/"V5_ANSWER_OVERLAY_INPUT_SEAL.json"
RUNTIME=FORMAL_RUNTIME/"v5_answer_overlay_runtime"
RESULTS=RUNTIME/"results"
RECEIPTS=RUNTIME/"receipts"
RESULT_SEAL=FORMAL_RUNTIME/"V5_ANSWER_OVERLAY_RESULT_SEAL.json"
LEDGER=GOV/"research_api_usage.sqlite3"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))
def atomic(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name(p.name+".tmp")
    q.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8");q.replace(p)

def protocol():
    if not PROTOCOL.is_file():raise RuntimeError("overlay protocol missing")
    p=load(PROTOCOL)
    if p.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-v1" or p.get("status")!="PREFROZEN_FOR_INDEPENDENT_REVIEW":
        raise RuntimeError("protocol candidate schema/status")
    if not PROTOCOL_FREEZE.is_file(): raise RuntimeError("protocol independent freeze missing")
    f=load(PROTOCOL_FREEZE)
    if f.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-freeze-v1" or f.get("status")!="PROTOCOL_EXECUTION_READY":
        raise RuntimeError("protocol independent freeze not ready")
    if f.get("protocol_sha256")!=sha(PROTOCOL): raise RuntimeError("protocol independent freeze binding drift")
    impl=p.get("implementation") or {}
    if sha(Path(__file__))!=impl.get("answer_runner_sha256"):raise RuntimeError("answer runner byte drift")
    for name,b in (p.get("bindings") or {}).items():
        fp=ROOT/str(b.get("path") or "")
        if not fp.is_file() or sha(fp)!=b.get("sha256") or fp.stat().st_size!=int(b.get("bytes") or -1):
            raise RuntimeError("protocol bound byte drift: "+str(name))
    return p

def execution():
    p=protocol()
    if not EXEC_FREEZE.is_file():raise RuntimeError("answer execution freeze missing")
    e=load(EXEC_FREEZE)
    if e.get("schema")!="xiaoyu-formal-halumem-v5-answer-execution-freeze-v1":raise RuntimeError("execution freeze schema")
    if e.get("status")!="ANSWER_EXECUTION_AUTHORIZED" or e.get("paid_execution_authorized") is not True:
        raise RuntimeError("answer execution not authorized")
    if e.get("formal_gold_scoring_authorized") is not False:raise RuntimeError("gold boundary drift")
    if e.get("protocol_sha256")!=sha(PROTOCOL):raise RuntimeError("protocol binding drift")
    if e.get("input_seal_sha256")!=sha(INPUT_SEAL):raise RuntimeError("input seal binding drift")
    return p,e

def ledger_row(cid):
    con=sqlite3.connect(LEDGER);con.row_factory=sqlite3.Row
    try:r=con.execute("""SELECT call_id,status,budget_scope,prompt_tokens,completion_tokens,actual_tokens,
      cache_hit_tokens,cache_miss_tokens,response_text,response_sha256,created_at,finished_at,error_class
      FROM calls WHERE case_id=? ORDER BY created_at DESC LIMIT 1""",(cid,)).fetchone()
    finally:con.close()
    return dict(r) if r else None

def parse_answer(text):
    try:o=json.loads(text)
    except Exception as exc:raise RuntimeError("FORMAT_REJECTED:invalid_json") from exc
    if not isinstance(o,dict) or set(o)!={"answer"} or not isinstance(o["answer"],str):
        raise RuntimeError("FORMAT_REJECTED:expected_exact_answer_object")
    ans=" ".join(o["answer"].strip().split())
    if not ans or len(ans)>4096:raise RuntimeError("FORMAT_REJECTED:bad_answer_length")
    return ans

def input_material():
    p,e=execution()
    s=load(INPUT_SEAL)
    if s.get("schema")!="xiaoyu-formal-v5-answer-overlay-input-seal-v1" or s.get("sealed") is not True:
        raise RuntimeError("input seal invalid")
    if int(s.get("question_count") or 0)!=6282 or int(s.get("stream_count") or 0)!=36:
        raise RuntimeError("input seal cardinality drift")
    if int(s.get("gold_fields_materialized") or 0)!=0:raise RuntimeError("input seal gold drift")
    rows_by_stream=[]
    ids=set()
    for spec in s.get("files") or []:
        fp=GOV/spec["path"]
        if not fp.is_file() or sha(fp)!=spec["sha256"]:raise RuntimeError("input file byte drift")
        obj=load(fp)
        if int(obj.get("gold_fields_materialized") or 0)!=0:raise RuntimeError("input file gold drift")
        rows=obj.get("rows") or []
        if len(rows)!=int(spec["question_count"]):raise RuntimeError("input stream cardinality drift")
        for x in rows:
            cid=x["case_id"]
            if cid in ids:raise RuntimeError("duplicate answer case id")
            ids.add(cid)
            if stable(x["messages"])!=x["request_messages_sha256"]:raise RuntimeError("input request hash drift")
        rows_by_stream.append((spec,obj))
    if len(ids)!=6282:raise RuntimeError("input total membership drift")
    return p,e,s,rows_by_stream

def result_path(spec):
    return RESULTS/(Path(spec["path"]).stem+".json")

def validate_durable(row,track,cid):
    if row.get("status")!="COMMITTED":raise RuntimeError(f"{cid} durable {row.get('status')}; retry forbidden")
    if row.get("budget_scope")!=track["scope"]:raise RuntimeError("durable answer scope drift")
    text=row.get("response_text")
    if not isinstance(text,str) or hashlib.sha256(text.encode()).hexdigest()!=row.get("response_sha256"):
        raise RuntimeError("durable response hash drift")
    return text

def load_progress(spec,obj,track):
    rp=result_path(spec)
    if not rp.is_file():return []
    r=load(rp)
    if r.get("schema")!="xiaoyu-formal-v5-answer-overlay-stream-result-v1":raise RuntimeError("result schema")
    rows=r.get("rows") or []
    frozen={x["case_id"]:x for x in obj["rows"]}
    if [x["case_id"] for x in rows] != [x["case_id"] for x in obj["rows"][:len(rows)]]:
        raise RuntimeError("answer result is not frozen prefix")
    for rec in rows:
        inp=frozen[rec["case_id"]];d=ledger_row(rec["case_id"])
        if d is None:raise RuntimeError("answer result lacks durable row")
        ans=parse_answer(validate_durable(d,track,rec["case_id"]))
        if rec.get("answer")!=ans or rec.get("response_sha256")!=d.get("response_sha256"):
            raise RuntimeError("answer result durable binding drift")
        if rec.get("question_sha256")!=hashlib.sha256(inp["question"].encode()).hexdigest():
            raise RuntimeError("answer question binding drift")
    return rows

def execute_answers():
    p,e,s,streams=input_material();track=p["answer_track"]
    completed=0
    for spec,obj in streams:
        rows=load_progress(spec,obj,track)
        done={x["case_id"] for x in rows}
        for inp in obj["rows"]:
            cid=inp["case_id"]
            if cid in done:continue
            d=ledger_row(cid)
            if d is not None:
                ans=parse_answer(validate_durable(d,track,cid))
                rec={"case_id":cid,"variant":inp["variant"],"uuid_hash":inp["uuid_hash"],
                     "session_index":inp["session_index"],"question_index":inp["question_index"],
                     "question_sha256":hashlib.sha256(inp["question"].encode()).hexdigest(),
                     "answer":ans,"call_id":d["call_id"],"response_sha256":d["response_sha256"],"recovered":True}
            else:
                body={"model":__import__("model_adapter").load_provider(ROOT)["model"],
                      "messages":inp["messages"],"max_tokens":int(track["max_completion_tokens"]),
                      "stream":False,"thinking":{"type":"disabled"},"reasoning_effort":"none",
                      "temperature":0.0,"top_p":1.0,"response_format":track["response_format"]}
                req=urllib.request.Request("http://127.0.0.1:18089/v1/chat/completions",
                  data=json.dumps(body,ensure_ascii=False).encode(),method="POST",
                  headers={"Content-Type":"application/json","Authorization":"Bearer local-budget-proxy:xiaoyu",
                    "X-XiaoYu-Research-Run":"e2_halumem_v5_answer_overlay_v1","X-XiaoYu-Case-ID":cid})
                try:
                    with urllib.request.urlopen(req,timeout=120) as f:payload=json.loads(f.read().decode())
                except urllib.error.HTTPError as exc:
                    msg=exc.read().decode("utf-8","replace");raise RuntimeError(f"HTTP_{exc.code}:{msg[:800]}") from exc
                d=ledger_row(cid)
                if d is None or d.get("status")!="COMMITTED":raise RuntimeError("provider returned without COMMITTED durable answer")
                content=str(payload["choices"][0]["message"]["content"])
                if content!=d.get("response_text"):raise RuntimeError("proxy/ledger answer drift")
                ans=parse_answer(content)
                rec={"case_id":cid,"variant":inp["variant"],"uuid_hash":inp["uuid_hash"],
                     "session_index":inp["session_index"],"question_index":inp["question_index"],
                     "question_sha256":hashlib.sha256(inp["question"].encode()).hexdigest(),
                     "answer":ans,"call_id":d["call_id"],"response_sha256":d["response_sha256"],"recovered":False,
                     "usage":payload.get("usage")}
            atomic(RECEIPTS/(cid+".json"),rec)
            rows.append(rec)
            atomic(result_path(spec),{"schema":"xiaoyu-formal-v5-answer-overlay-stream-result-v1",
              "input_stream_sha256":spec["sha256"],"rows":rows})
        rows=load_progress(spec,obj,track)
        if len(rows)!=len(obj["rows"]):raise RuntimeError("stream answer result incomplete")
        completed+=len(rows)
    if completed!=6282:raise RuntimeError("formal answer count !=6282")
    files=[]
    for spec,obj in streams:
        rp=result_path(spec)
        files.append({"path":str(rp.relative_to(GOV)).replace("\\","/"),"sha256":sha(rp),
                      "variant":spec["variant"],"uuid_hash":spec["uuid_hash"],"question_count":spec["question_count"]})
    seal={"schema":"xiaoyu-formal-v5-answer-overlay-result-seal-v1","sealed":True,
      "protocol_sha256":sha(PROTOCOL),"input_seal_sha256":sha(INPUT_SEAL),
      "execution_freeze_sha256":sha(EXEC_FREEZE),"question_count":completed,
      "stream_count":36,"files":sorted(files,key=lambda x:x["path"]),
      "gold_fields_materialized":0,"sealed_at_epoch":__import__("time").time()}
    atomic(RESULT_SEAL,seal)
    return seal

def preflight():
    p=protocol()
    return {"schema":"xiaoyu-formal-v5-answer-runner-preflight-v1",
      "protocol_sha256":sha(PROTOCOL),"input_seal_exists":INPUT_SEAL.is_file(),
      "execution_freeze_exists":EXEC_FREEZE.is_file(),"scope":p["answer_track"]["scope"],
      "case_cap":p["answer_track"]["max_case_calls"],"provider_calls":0,"gold_reads":0}

def status():
    out=preflight()
    if INPUT_SEAL.is_file():
        try:
            _p,_e,_s,streams=input_material()
            counts={"NOT_CALLED":0}
            for _spec,obj in streams:
                for x in obj["rows"]:
                    d=ledger_row(x["case_id"]);k=d["status"] if d else "NOT_CALLED";counts[k]=counts.get(k,0)+1
            out["status_counts"]=counts
        except Exception as exc:out["input_error"]=type(exc).__name__+":"+str(exc)
    out["result_seal_exists"]=RESULT_SEAL.is_file()
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("action",nargs="?",default="preflight",choices=["preflight","status","execute"])
    a=ap.parse_args()
    try:out=preflight() if a.action=="preflight" else status() if a.action=="status" else execute_answers()
    except Exception as exc:
        print(json.dumps({"ok":False,"action":a.action,"error":type(exc).__name__+":"+str(exc)},ensure_ascii=False,indent=2));raise SystemExit(2)
    print(json.dumps({"ok":True,"action":a.action,"result":out},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
