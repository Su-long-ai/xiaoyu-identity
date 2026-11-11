#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selective LongMemEval confirmatory input materializer.

This file is execution-preparation only. It never decodes evaluator/gold values.
Only question, haystack_sessions(role/content), haystack_session_ids are materialized.
The original LongMemEval dataset SHA is verified before any case input is written.
"""
from __future__ import annotations
import hashlib,json,re,tempfile,os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
DATA=ROOT/"external"/"OmniMemEval"/"data"/"longmemeval"/"longmemeval_s_cleaned.json"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
OUT=GOV/"e2_confirmatory_inputs"/"lme"
EXPECTED_DATA_SHA="d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
FORBIDDEN={"question_type","answer","answer_session_ids","gold","evaluator_metadata","memory_points","original_memories"}
JSON_STRING_RE=re.compile(r'"(?:\\.|[^"\\])*"')

class BuildError(RuntimeError): pass

def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def stable(x)->str:
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def atomic_json(p:Path,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode()
    fd,tmp=tempfile.mkstemp(prefix=p.name+".",suffix=".tmp",dir=str(p.parent))
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

class Cur:
    def __init__(self,s:str): self.s=s; self.i=0
    def ws(self):
        n=len(self.s)
        while self.i<n and self.s[self.i] in " \t\r\n": self.i+=1
    def ch(self,c:str):
        self.ws()
        if self.i>=len(self.s) or self.s[self.i]!=c:
            raise BuildError(f"expected {c} at {self.i}")
        self.i+=1
    def string(self)->str:
        self.ws()
        if self.i>=len(self.s) or self.s[self.i]!='"': raise BuildError("expected string")
        obj,end=json.JSONDecoder().raw_decode(self.s,self.i)
        if not isinstance(obj,str): raise BuildError("not string")
        self.i=end
        return obj
    def skip_string(self):
        self.ws()
        if self.i>=len(self.s) or self.s[self.i]!='"': raise BuildError("skip_string")
        m=JSON_STRING_RE.match(self.s,self.i)
        if not m: raise BuildError("unterminated string")
        self.i=m.end()
    def skip_value(self):
        self.ws()
        if self.i>=len(self.s): raise BuildError("skip eof")
        c=self.s[self.i]
        if c=='"': self.skip_string();return
        if c=="{":
            self.i+=1;self.ws()
            if self.i<len(self.s) and self.s[self.i]=="}": self.i+=1;return
            while True:
                self.skip_string();self.ch(":");self.skip_value();self.ws()
                if self.i<len(self.s) and self.s[self.i]==",": self.i+=1;continue
                self.ch("}");return
        if c=="[":
            self.i+=1;self.ws()
            if self.i<len(self.s) and self.s[self.i]=="]": self.i+=1;return
            while True:
                self.skip_value();self.ws()
                if self.i<len(self.s) and self.s[self.i]==",": self.i+=1;continue
                self.ch("]");return
        m=re.match(r"(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)",self.s[self.i:])
        if not m: raise BuildError(f"bad value {self.i}")
        self.i+=len(m.group(0))
    def string_array(self)->list[str]:
        out=[];self.ch("[");self.ws()
        if self.i<len(self.s) and self.s[self.i]=="]":self.i+=1;return out
        while True:
            out.append(self.string());self.ws()
            if self.i<len(self.s) and self.s[self.i]==",":self.i+=1;continue
            self.ch("]");return out
    def message(self)->dict:
        self.ch("{");role=None;content=None;self.ws()
        if self.i<len(self.s) and self.s[self.i]!="}":
            while True:
                k=self.string();self.ch(":")
                if k=="role": role=self.string()
                elif k=="content": content=self.string()
                else:self.skip_value()
                self.ws()
                if self.i<len(self.s) and self.s[self.i]==",":self.i+=1;continue
                break
        self.ch("}")
        if role not in ("user","assistant") or not isinstance(content,str):
            raise BuildError("bad message")
        return {"role":role,"content":content}
    def session(self)->list[dict]:
        out=[];self.ch("[");self.ws()
        if self.i<len(self.s) and self.s[self.i]=="]":self.i+=1;return out
        while True:
            out.append(self.message());self.ws()
            if self.i<len(self.s) and self.s[self.i]==",":self.i+=1;continue
            self.ch("]");return out
    def sessions(self)->list[list[dict]]:
        out=[];self.ch("[");self.ws()
        if self.i<len(self.s) and self.s[self.i]=="]":self.i+=1;return out
        while True:
            out.append(self.session());self.ws()
            if self.i<len(self.s) and self.s[self.i]==",":self.i+=1;continue
            self.ch("]");return out

def parse_selected_record(cur:Cur,idx:int,selected:set[int])->dict|None:
    wanted=idx in selected
    cur.ch("{")
    question=None;sessions=None;session_ids=None
    cur.ws()
    if cur.i<len(cur.s) and cur.s[cur.i]!="}":
        while True:
            k=cur.string();cur.ch(":")
            if wanted and k=="question": question=cur.string()
            elif wanted and k=="haystack_sessions": sessions=cur.sessions()
            elif wanted and k=="haystack_session_ids": session_ids=cur.string_array()
            else: cur.skip_value()
            cur.ws()
            if cur.i<len(cur.s) and cur.s[cur.i]==",":cur.i+=1;continue
            break
    cur.ch("}")
    if not wanted:return None
    if not isinstance(question,str) or not question.strip(): raise BuildError(f"{idx}: question missing")
    if not isinstance(sessions,list) or not isinstance(session_ids,list) or len(sessions)!=len(session_ids):
        raise BuildError(f"{idx}: session structure mismatch")
    return {"question":question,"sessions":sessions,"session_ids":session_ids}

def iter_records(path:Path,selected:set[int]):
    # Same anti-peeking model as the audited Halu selective parser: raw JSON is
    # scanned structurally; skipped values are never JSON-decoded/materialized.
    text=path.read_text("utf-8")
    cur=Cur(text);cur.ch("[");cur.ws();idx=0
    if cur.i<len(cur.s) and cur.s[cur.i]=="]":cur.i+=1;return
    while True:
        row=parse_selected_record(cur,idx,selected)
        if row is not None: yield idx,row
        idx+=1;cur.ws()
        if cur.i<len(cur.s) and cur.s[cur.i]==",":cur.i+=1;continue
        cur.ch("]");break
    cur.ws()
    if cur.i!=len(cur.s): raise BuildError("trailing dataset bytes")
    if idx!=500: raise BuildError(f"expected 500 records got {idx}")

def make_case(idx:int,row:dict)->dict:
    records=[]
    for si,(session,sid) in enumerate(zip(row["sessions"],row["session_ids"])):
        for mi,msg in enumerate(session):
            role=msg["role"];text=msg["content"]
            if not text.strip():continue
            eid=f"lme:{idx}:{si}:{sid}:{mi}"
            records.append({
              "session_index":si,
              "message_index":mi,
              "session_id":str(sid),
              "source_role":role,
              "authority":"user_history" if role=="user" else "conversation_history",
              "text":text,
              "admissible_current": True if role=="user" else False,
              "temporal_status":"unknown",
              "evidence_id":eid
            })
    return {"case_id":f"lme-c-{idx:03d}","question":row["question"],"records":records}

def walk_keys(x):
    if isinstance(x,dict):
        for k,v in x.items():
            yield str(k)
            yield from walk_keys(v)
    elif isinstance(x,list):
        for v in x:yield from walk_keys(v)

def main():
    got=sha_file(DATA)
    if got.lower()!=EXPECTED_DATA_SHA: raise BuildError("dataset SHA drift")
    split=json.loads(SPLIT.read_text("utf-8"))
    selected=list(map(int,split["longmemeval"]["confirmatory_indices"]))
    if len(selected)!=454 or len(set(selected))!=454: raise BuildError("confirmatory split not exact")
    selected_set=set(selected)
    built={}
    for idx,row in iter_records(DATA,selected_set):
        case=make_case(idx,row)
        bad=FORBIDDEN & set(walk_keys(case))
        if bad: raise BuildError(f"{idx}: forbidden materialized {sorted(bad)}")
        built[idx]=case
    if set(built)!=selected_set: raise BuildError("selected case coverage mismatch")
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for idx in selected:
        case=built[idx]
        p=OUT/(case["case_id"]+".json")
        atomic_json(p,case)
        rows.append({
          "dataset_index":idx,"case_id":case["case_id"],
          "input_path":str(p.relative_to(ROOT)).replace("\\","/"),
          "input_sha256":sha_file(p),
          "record_count":len(case["records"])
        })
    manifest={
      "schema":"xiaoyu-e2-lme-confirmatory-input-build-v1",
      "dataset_path":"external/OmniMemEval/data/longmemeval/longmemeval_s_cleaned.json",
      "dataset_sha256":got,
      "split_manifest_sha256":sha_file(SPLIT),
      "case_count":len(rows),
      "materialized_fields":["case_id","question","records[].session_index","records[].message_index",
        "records[].session_id","records[].source_role","records[].authority","records[].text",
        "records[].admissible_current","records[].temporal_status","records[].evidence_id"],
      "trusted_time_policy":"question_time/effective_at omitted because dataset dates lack timezone; frozen runner/R51/R50 must fail closed when trusted time is required",
      "forbidden_fields_materialized":[],
      "rows":rows,
      "rows_sha256":stable(rows)
    }
    atomic_json(OUT/"INPUT_BUILD_MANIFEST.json",manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k!="rows"},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
