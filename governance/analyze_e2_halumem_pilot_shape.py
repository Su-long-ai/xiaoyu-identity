#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline characterization of ONLY the already-exposed HaluMem pilot users/windows.
No provider/model calls and no confirmatory-user access.
"""
from __future__ import annotations
import json,re,statistics
from collections import Counter
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
G=ROOT/"governance"
M=json.loads((G/"E2_PILOT_EXECUTION_MANIFEST.json").read_text("utf-8"))

def toks(s):
    return set(re.findall(r"[a-z0-9]+",str(s).lower()))
def overlap(a,b):
    aa=toks(a);bb=toks(b)
    return len(aa&bb)/max(1,len(aa))
def load(path):
    out={}
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            o=json.loads(line);out[str(o["uuid"])]=o
    return out

def main():
    sampling=M["halumem_operation_subsample"]["sampling"]
    datasets={
      "HaluMem-Medium.jsonl":load(ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl"),
      "HaluMem-Long.jsonl":load(ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl")
    }
    types=Counter();sources=Counter();updates=0;mems=0;turns=Counter()
    role_support=Counter();scores=[]
    for spec in sampling:
        data=datasets[spec["variant"]];u=data[spec["uuid"]]
        for si in spec["selected_session_indices"]:
            sess=u["sessions"][si]
            messages=sess.get("dialogue") or []
            user_text="\n".join(str(x.get("content") or "") for x in messages if x.get("role")=="user")
            asst_text="\n".join(str(x.get("content") or "") for x in messages if x.get("role")=="assistant")
            turns["user"]+=sum(x.get("role")=="user" for x in messages)
            turns["assistant"]+=sum(x.get("role")=="assistant" for x in messages)
            for mp in sess.get("memory_points") or []:
                mems+=1
                types[str(mp.get("memory_type"))]+=1
                sources[str(mp.get("memory_source"))]+=1
                updates+=int(str(mp.get("is_update")).lower()=="true")
                text=str(mp.get("memory_content") or "")
                us=overlap(text,user_text);ass=overlap(text,asst_text)
                if us>ass+0.10:k="user_lean"
                elif ass>us+0.10:k="assistant_lean"
                else:k="tie"
                role_support[k]+=1;scores.append((us,ass))
    report={
      "sampling_specs":sampling,
      "selected_sessions":sum(len(x["selected_session_indices"]) for x in sampling),
      "dialogue_turns":dict(turns),
      "memory_points":mems,"updates":updates,
      "memory_types":dict(types),"memory_sources":dict(sources),
      "lexical_support_lean":dict(role_support),
      "mean_memory_token_coverage_user":statistics.mean(x[0] for x in scores) if scores else 0,
      "mean_memory_token_coverage_assistant":statistics.mean(x[1] for x in scores) if scores else 0,
      "interpretation":"Lexical overlap is diagnostic only, not provenance proof. Any material assistant-lean population is sufficient to reject a user-only extraction contract as a faithful implementation of official full-dialogue ingestion.",
      "confirmatory_user_records_selected_or_analyzed":0,
      "provider_calls":0
    }
    out=G/"E2_HALUMEM_PILOT_SHAPE_AUDIT.json"
    with out.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
