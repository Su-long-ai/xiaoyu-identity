#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib,json,os,re,sqlite3,time
from pathlib import Path
from openai import OpenAI

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
RUNTIME=GOV/"stagea_answerer_dev_v1_runtime"
BINDING=FROZEN/"HALUMEM_JUDGE_BINDING.json"
MANIFEST=GOV/"STAGEA_ANSWERER_TRANCHE16_JUDGE_V1.json"
LEDGER=RUNTIME/"judge_ledger_qwen38_flash_v1.sqlite3"
THIS=Path(__file__).resolve()

class JudgeError(RuntimeError):
    pass

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def auth():
    m=json.loads(MANIFEST.read_text("utf-8"))
    if m.get("schema")!="xiaoyu-stagea-answerer-tranche16-judge-v1" or m.get("status")!="EXECUTION_AUTHORIZED":
        raise JudgeError("judge manifest not authorized")
    if m["implementation"]["judge_wrapper_sha256"]!=sha(THIS):
        raise JudgeError("judge wrapper byte drift")
    b=json.loads(BINDING.read_text("utf-8"))
    j=b.get("judge") or {}
    if b.get("schema")!="xiaoyu-halumem-final-judge-binding-v2":
        raise JudgeError("judge binding drift")
    if j.get("provider")!="alibaba_model_studio" or j.get("model_id")!="qwen3.8-flash":
        raise JudgeError("judge model drift")
    if float(j.get("temperature"))!=0.0 or j.get("enable_thinking") is not False:
        raise JudgeError("judge config drift")
    if m["bindings"]["judge_binding_sha256"]!=sha(BINDING):
        raise JudgeError("binding hash drift")
    return m,b

def parse(content):
    text=str(content or "").strip()
    cand=None
    m=re.search(r"\x60\x60\x60json\s*(\{.*?\})\s*\x60\x60\x60",text,re.S|re.I)
    if m:
        cand=m.group(1).strip()
    elif text.startswith("{") and text.endswith("}"):
        cand=text
    else:
        m2=re.fullmatch(r"\x60\x60\x60(?:json)?\s*(\{.*\})\s*\x60\x60\x60",text,re.S|re.I)
        if m2:
            cand=m2.group(1).strip()
    if cand is None:
        raise JudgeError("No authorized JSON object form found")
    try:
        obj=json.loads(cand)
    except Exception as exc:
        raise JudgeError("invalid judge JSON") from exc
    if not isinstance(obj,dict):
        raise JudgeError("judge JSON not object")
    return obj

def db():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(LEDGER,timeout=30,isolation_level=None)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS judge_calls(
      prompt_sha256 TEXT PRIMARY KEY,status TEXT NOT NULL,model TEXT NOT NULL,binding_sha256 TEXT NOT NULL,
      response_json TEXT,response_text TEXT,prompt_tokens INTEGER,completion_tokens INTEGER,total_tokens INTEGER,
      created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT)""")
    return con

def llm_request_for_json(prompt):
    manifest,binding=auth()
    key=os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise JudgeError("DASHSCOPE_API_KEY missing")
    prompt=str(prompt)
    psha=hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    bsha=sha(BINDING)
    model="qwen3.8-flash"
    cap=16
    con=db()
    try:
        row=con.execute("SELECT * FROM judge_calls WHERE prompt_sha256=?",(psha,)).fetchone()
        if row is not None:
            if row["status"]=="COMMITTED":
                return json.loads(row["response_json"])
            raise JudgeError("judge prompt already "+str(row["status"])+"; retry forbidden")
        if int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])>=cap:
            raise JudgeError("judge cap exhausted")
        now=time.time()
        con.execute("BEGIN IMMEDIATE")
        try:
            if con.execute("SELECT 1 FROM judge_calls WHERE prompt_sha256=?",(psha,)).fetchone():
                raise JudgeError("concurrent duplicate")
            if int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])>=cap:
                raise JudgeError("judge cap exhausted")
            con.execute("INSERT INTO judge_calls(prompt_sha256,status,model,binding_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (psha,"RESERVED",model,bsha,now,now))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        try:
            client=OpenAI(api_key=key,base_url=os.getenv("DASHSCOPE_BASE_URL") or binding["runtime"]["default_base_url"])
            resp=client.chat.completions.create(model=model,messages=[{"role":"user","content":prompt}],
                temperature=0,max_tokens=16384,extra_body={"enable_thinking":False})
            content=resp.choices[0].message.content or ""
            usage=resp.usage
            pt=int(getattr(usage,"prompt_tokens",0) or 0)
            ct=int(getattr(usage,"completion_tokens",0) or 0)
            tt=int(getattr(usage,"total_tokens",pt+ct) or (pt+ct))
        except Exception as exc:
            con.execute("UPDATE judge_calls SET status='UNKNOWN',updated_at=?,error=? WHERE prompt_sha256=?",
                        (time.time(),type(exc).__name__+":"+str(exc),psha))
            raise
        con.execute("UPDATE judge_calls SET status='RECEIVED',response_text=?,prompt_tokens=?,completion_tokens=?,total_tokens=?,updated_at=?,error=NULL WHERE prompt_sha256=?",
                    (content,pt,ct,tt,time.time(),psha))
        try:
            obj=parse(content)
        except Exception as exc:
            con.execute("UPDATE judge_calls SET status='FORMAT_REJECTED',updated_at=?,error=? WHERE prompt_sha256=?",
                        (time.time(),type(exc).__name__+":"+str(exc),psha))
            raise
        con.execute("UPDATE judge_calls SET status='COMMITTED',response_json=?,updated_at=?,error=NULL WHERE prompt_sha256=?",
                    (json.dumps(obj,ensure_ascii=False,separators=(",",":")),time.time(),psha))
        return obj
    finally:
        con.close()

def llm_request(prompt):
    raise JudgeError("raw text path unauthorized")
