#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Count formal HaluMem question texts without materializing any gold fields.

Allowed materialization: uuid, sessions[].questions[].question.
All other values, including dialogue, memory_points, question answer/evidence/
difficulty/question_type, are skipped structurally.
"""
from __future__ import annotations
import json,re,hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
FILES={
 "m":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl",
 "l":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl",
}

class E(RuntimeError): pass
class C:
    def __init__(self,s): self.s=s; self.i=0
    def ws(self):
        n=len(self.s)
        while self.i<n and self.s[self.i] in " \t\r\n": self.i+=1
    def ch(self,c):
        self.ws()
        if self.i>=len(self.s) or self.s[self.i]!=c: raise E(f"expected {c} at {self.i}")
        self.i+=1
    def string(self):
        self.ws()
        if self.i>=len(self.s) or self.s[self.i]!='"': raise E("expected string")
        x,end=json.JSONDecoder().raw_decode(self.s,self.i)
        if not isinstance(x,str): raise E("not string")
        self.i=end; return x
    def skip_string(self):
        self.ws()
        if self.i>=len(self.s) or self.s[self.i]!='"': raise E("skip_string")
        i=self.i+1; esc=False
        while i<len(self.s):
            c=self.s[i]
            if esc: esc=False
            elif c=="\\": esc=True
            elif c=='"': self.i=i+1; return
            i+=1
        raise E("unterminated")
    def skip(self):
        self.ws()
        if self.i>=len(self.s): raise E("eof")
        c=self.s[self.i]
        if c=='"': self.skip_string(); return
        if c=="{":
            self.i+=1; self.ws()
            if self.i<len(self.s) and self.s[self.i]=="}": self.i+=1; return
            while True:
                self.skip_string(); self.ch(":"); self.skip(); self.ws()
                if self.i<len(self.s) and self.s[self.i]==",": self.i+=1; continue
                self.ch("}"); return
        if c=="[":
            self.i+=1; self.ws()
            if self.i<len(self.s) and self.s[self.i]=="]": self.i+=1; return
            while True:
                self.skip(); self.ws()
                if self.i<len(self.s) and self.s[self.i]==",": self.i+=1; continue
                self.ch("]"); return
        m=re.match(r"(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)",self.s[self.i:])
        if not m: raise E(f"bad scalar {self.i}")
        self.i+=len(m.group(0))

def parse_questions(c):
    n=0
    c.ch("["); c.ws()
    if c.i<len(c.s) and c.s[c.i]=="]": c.i+=1; return 0
    while True:
        c.ch("{"); c.ws()
        if c.i<len(c.s) and c.s[c.i]!="}":
            while True:
                k=c.string(); c.ch(":")
                if k=="question":
                    c.string(); n+=1
                else:
                    c.skip()
                c.ws()
                if c.i<len(c.s) and c.s[c.i]==",": c.i+=1; continue
                break
        c.ch("}"); c.ws()
        if c.i<len(c.s) and c.s[c.i]==",": c.i+=1; continue
        c.ch("]"); return n

def parse_sessions(c):
    q=0; sessions=0
    c.ch("["); c.ws()
    if c.i<len(c.s) and c.s[c.i]=="]": c.i+=1; return 0,0
    while True:
        sessions+=1; c.ch("{"); c.ws()
        if c.i<len(c.s) and c.s[c.i]!="}":
            while True:
                k=c.string(); c.ch(":")
                if k=="questions": q+=parse_questions(c)
                else: c.skip()
                c.ws()
                if c.i<len(c.s) and c.s[c.i]==",": c.i+=1; continue
                break
        c.ch("}"); c.ws()
        if c.i<len(c.s) and c.s[c.i]==",": c.i+=1; continue
        c.ch("]"); return sessions,q

def scan_line(line,selected):
    c=C(line); c.ch("{"); uuid=None; sessions=questions=0; c.ws()
    if c.i<len(c.s) and c.s[c.i]!="}":
        while True:
            k=c.string(); c.ch(":")
            if k=="uuid": uuid=c.string()
            elif k=="sessions":
                if uuid is None: raise E("uuid must precede sessions")
                if uuid in selected: sessions,questions=parse_sessions(c)
                else: c.skip()
            else: c.skip()
            c.ws()
            if c.i<len(c.s) and c.s[c.i]==",": c.i+=1; continue
            break
    c.ch("}"); c.ws()
    if c.i!=len(c.s): raise E("trailing")
    if uuid in selected: return uuid,sessions,questions
    return None

def main():
    split=json.loads(SPLIT.read_text("utf-8"))["halumem"]
    selected=set(split["confirmatory_uuids"])
    out={
      "schema":"xiaoyu-formal-safe-question-count-v2",
      "scanner_sha256":None,
      "method":"bytewise structural scan; only uuid and question strings decoded; dialogue and all gold fields skipped",
      "gold_fields_materialized":0,
      "variants":{},
    }
    for v,p in FILES.items():
        rows=[]; sessions=questions=0
        with p.open("r",encoding="utf-8") as f:
            for raw in f:
                hit=scan_line(raw.strip(),selected)
                if hit is None: continue
                u,s,q=hit; sessions+=s; questions+=q
                rows.append({"uuid_hash":hashlib.sha256(u.encode()).hexdigest(),"sessions":s,"questions":q})
        if len(rows)!=18: raise E(f"{v} selected row count {len(rows)}")
        out["variants"][v]={"rows":18,"sessions":sessions,"questions":questions,"per_user":rows}
    out["total_questions"]=sum(x["questions"] for x in out["variants"].values())
    me=Path(__file__)
    out["scanner_sha256"]=hashlib.sha256(me.read_bytes()).hexdigest()
    p=GOV/"FORMAL_SAFE_QUESTION_COUNT_V2.json"
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({"m":out["variants"]["m"]["questions"],"l":out["variants"]["l"]["questions"],"total":out["total_questions"],"gold_fields_materialized":0},indent=2))

if __name__=="__main__": main()
