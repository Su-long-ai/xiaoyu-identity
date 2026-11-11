#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib,json,os,re,sqlite3,time
from pathlib import Path
from openai import OpenAI

ROOT=Path(os.environ.get("XIAOYU_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
GOV=ROOT/"governance";FROZEN=GOV/"confirmatory_frozen";RUNTIME=GOV/"halumem_confirmatory_runtime_v2"
PROTOCOL=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_V1.json"
PROTOCOL_FREEZE=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_FREEZE_V1.json"
ANSWER_SEAL=RUNTIME/"V5_ANSWER_OVERLAY_RESULT_SEAL.json"
BINDING_PATH=FROZEN/"HALUMEM_JUDGE_BINDING.json"
CANONICAL=GOV/"formal_v5_judge_ledger.py"
LEDGER=RUNTIME/"v5_judge_ledger_qwen38_flash.sqlite3"

class JudgeError(RuntimeError):pass
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))

def authorized():
    if not PROTOCOL.is_file() or not PROTOCOL_FREEZE.is_file() or not ANSWER_SEAL.is_file():
        raise JudgeError("V5 judge authorization material missing")
    p=load(PROTOCOL);f=load(PROTOCOL_FREEZE);a=load(ANSWER_SEAL);psha=sha(PROTOCOL)
    if p.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-v1" or p.get("status")!="PREFROZEN_FOR_INDEPENDENT_REVIEW":
        raise JudgeError("protocol candidate drift")
    if f.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-freeze-v1" or f.get("status")!="PROTOCOL_EXECUTION_READY" or f.get("protocol_sha256")!=psha:
        raise JudgeError("protocol independent freeze drift")
    expected=(p.get("implementation") or {}).get("judge_wrapper_sha256");actual=sha(CANONICAL)
    if not expected or expected!=actual or sha(Path(__file__))!=actual:raise JudgeError("V5 judge wrapper byte drift")
    if a.get("schema")!="xiaoyu-formal-v5-answer-overlay-result-seal-v1" or a.get("sealed") is not True:
        raise JudgeError("answer result seal invalid")
    if int(a.get("question_count") or 0)!=6282 or int(a.get("stream_count") or 0)!=36 or int(a.get("gold_fields_materialized") or 0)!=0:
        raise JudgeError("answer result seal cardinality/gold drift")
    if a.get("protocol_sha256")!=psha:raise JudgeError("answer result protocol drift")
    return p,psha,a,sha(ANSWER_SEAL)

def binding():
    b=load(BINDING_PATH);j=b.get("judge") or {}
    if b.get("schema")!="xiaoyu-halumem-final-judge-binding-v2":raise JudgeError("judge binding schema")
    if j.get("provider")!="alibaba_model_studio" or j.get("model_id")!="qwen3.8-flash":raise JudgeError("judge model drift")
    if float(j.get("temperature"))!=0.0 or int(j.get("max_tokens"))!=16384 or j.get("enable_thinking") is not False or j.get("substitution_allowed") is not False:
        raise JudgeError("judge config drift")
    return b

def parse_json_block(content):
    m=re.search(r"\x60\x60\x60json\s*(\{.*?\})\s*\x60\x60\x60",str(content or ""),re.DOTALL)
    if not m:raise JudgeError("No JSON block found")
    try:o=json.loads(m.group(1).strip())
    except Exception as exc:raise JudgeError("invalid JSON block") from exc
    if not isinstance(o,dict):raise JudgeError("judge JSON not object")
    return o

def db():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(LEDGER,timeout=30,isolation_level=None);con.row_factory=sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS judge_calls(
      prompt_sha256 TEXT PRIMARY KEY,status TEXT NOT NULL,model TEXT NOT NULL,
      binding_sha256 TEXT NOT NULL,protocol_sha256 TEXT NOT NULL,answer_seal_sha256 TEXT NOT NULL,
      response_json TEXT,response_text TEXT,prompt_tokens INTEGER,completion_tokens INTEGER,
      created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT)""")
    return con

def llm_request_for_json(prompt):
    _p,psha,a,asha=authorized();b=binding()
    key=os.getenv("DASHSCOPE_API_KEY")
    if not key:raise JudgeError("DASHSCOPE_API_KEY missing")
    prompt=str(prompt);ps=hashlib.sha256(prompt.encode()).hexdigest();bs=sha(BINDING_PATH);model=b["judge"]["model_id"]
    con=db()
    try:
        row=con.execute("SELECT * FROM judge_calls WHERE prompt_sha256=?",(ps,)).fetchone()
        if row is not None:
            if row["binding_sha256"]!=bs or row["model"]!=model or row["protocol_sha256"]!=psha or row["answer_seal_sha256"]!=asha:
                raise JudgeError("V5 judge durable binding drift")
            if row["status"]=="COMMITTED":return json.loads(row["response_json"])
            raise JudgeError(f"V5 judge prompt already {row['status']}; retry forbidden")
        now=time.time();sealed_at=float(a.get("sealed_at_epoch") or 0)
        if sealed_at<=0 or now<sealed_at:raise JudgeError("judge call not post-answer-seal")
        con.execute("BEGIN IMMEDIATE")
        try:
            if con.execute("SELECT 1 FROM judge_calls WHERE prompt_sha256=?",(ps,)).fetchone():raise JudgeError("judge prompt concurrent")
            con.execute("""INSERT INTO judge_calls(prompt_sha256,status,model,binding_sha256,protocol_sha256,answer_seal_sha256,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?)""",(ps,"RESERVED",model,bs,psha,asha,now,now));con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK");raise
        try:
            client=OpenAI(api_key=key,base_url=os.getenv("DASHSCOPE_BASE_URL") or b["runtime"]["default_base_url"])
            resp=client.chat.completions.create(model=model,messages=[{"role":"user","content":prompt}],temperature=0,max_tokens=16384,extra_body={"enable_thinking":False})
            content=resp.choices[0].message.content or "";obj=parse_json_block(content);u=getattr(resp,"usage",None)
            pt=int(getattr(u,"prompt_tokens",0) or 0);ct=int(getattr(u,"completion_tokens",0) or 0)
        except Exception as exc:
            con.execute("UPDATE judge_calls SET status='UNKNOWN',updated_at=?,error=? WHERE prompt_sha256=?",(time.time(),type(exc).__name__+":"+str(exc),ps));raise
        con.execute("""UPDATE judge_calls SET status='COMMITTED',response_json=?,response_text=?,prompt_tokens=?,completion_tokens=?,updated_at=?,error=NULL WHERE prompt_sha256=?""",
          (json.dumps(obj,ensure_ascii=False,separators=(",",":")),content,pt,ct,time.time(),ps))
        return obj
    finally:con.close()

def llm_request(prompt):raise JudgeError("raw judge text path not authorized")
