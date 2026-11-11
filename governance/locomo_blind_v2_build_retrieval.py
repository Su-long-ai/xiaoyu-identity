#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build LoCoMo blind-200 V2 retrieval snapshot using the existing OmniMemEval XiaoYu adapter.

Gold-free/offline only:
- reads governance/locomo_blind_200_input_v2.json
- ingests every conversation twice using OmniMemEval's dual-speaker perspective:
  speaker A's own turns are user memories in A's store; B turns are assistant events,
  and vice versa for B's store
- XIAOYU_INGEST_MODE=literal_source (all turns preflighted <=1500 chars)
- searches both stores top_k=10, producing <=20 structured user_source_history memories
- never reads raw locomo10.json, membership categories, answer/evidence, blind gold or formal data
"""
from __future__ import annotations
import hashlib, importlib.util, json, os, re, shutil, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
OMNI=ROOT/"external"/"OmniMemEval"
SCRIPTS=OMNI/"scripts"
INPUT=G/"locomo_blind_200_input_v2.json"
COMPAT=G/"LOCOMO_BLIND_V2_LITERAL_SOURCE_COMPAT.json"
OUT=G/"LOCOMO_BLIND_V2_RETRIEVAL_SNAPSHOT.json"
RUNTIME=G/"locomo_blind_v2_runtime"
STORE=RUNTIME/"literal_source_store"

EXPECTED_INPUT_SHA="57cbfc53ce0818933831e6b87b8a2c038922a423e533aae2ab2610525c69398c"
EXPECTED_COMPAT_SHA=None
TOP_K_PER_SPEAKER=10

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

if sha(INPUT)!=EXPECTED_INPUT_SHA: raise SystemExit("blind input byte drift")
compat=json.loads(COMPAT.read_text("utf-8"))
if not compat.get("literal_source_compatible") or compat.get("over_1500")!=0:
    raise SystemExit("literal_source compatibility not proven")

sys.path.insert(0,str(SCRIPTS))
sys.path.insert(0,str(SCRIPTS/"client_factory"))
from utils.time import parse_locomo_time, to_iso
from client_factory.xiaoyu_client import XiaoYuClient

if STORE.exists(): shutil.rmtree(STORE)
STORE.mkdir(parents=True,exist_ok=True)
os.environ["XIAOYU_PROJECT_ROOT"]=str(ROOT)
os.environ["XIAOYU_EVAL_ROOT"]=str(STORE)
os.environ["XIAOYU_INGEST_MODE"]="literal_source"
client=XiaoYuClient()

data=json.loads(INPUT.read_text("utf-8"))
samples=data.get("samples") or []
if len(samples)!=10: raise SystemExit("blind sample count drift")

# Structured view of the exact same IdentityStore.recall() retrieval used by
# XiaoYuClient.search(). Avoid text-format -> parse roundtrip.
def structured_search(user_id,query,top_k,side):
    store=client._open(user_id)
    try:
        hits=store.recall(str(query),limit=int(top_k))
        out=[]
        for hit in hits:
            mid=int(hit["memory_id"])
            row=store.conn.execute(
                "SELECT m.memory_id,m.text,m.category,m.source_event,"
                "e.actor,e.kind,e.extra FROM memories m "
                "LEFT JOIN events e ON e.event_id=m.source_event "
                "WHERE m.memory_id=?",(mid,)).fetchone()
            if not row: continue
            if str(row["actor"] or "")!="user":
                raise RuntimeError("non-user search hit leaked")
            extra={}
            try: extra=json.loads(row["extra"] or "{}")
            except (TypeError,ValueError): pass
            out.append({
              "authority":"user_source_history",
              "timestamp":extra.get("chat_time"),
              "source_id":f"locomo:{user_id}:event:{row['source_event']}",
              "speaker_side":side,
              "text":row["text"],
            })
        return out
    finally:
        store.close()

def session_num(k):
    m=re.fullmatch(r"session_(\d+)",str(k))
    return int(m.group(1)) if m else None

ingest_counts={}
for sample_idx,sample in enumerate(samples):
    sid=str(sample["sample_id"])
    conv=sample["conversation"]
    a=str(conv["speaker_a"]); b=str(conv["speaker_b"])
    ua=f"locomo_blind_v2_{sid}_speaker_a"
    ub=f"locomo_blind_v2_{sid}_speaker_b"
    sessions=sorted(
      [(session_num(k),k,v) for k,v in conv.items() if session_num(k) is not None and isinstance(v,list)],
      key=lambda x:x[0]
    )
    user_a=user_b=assistant_a=assistant_b=0
    for n,key,session in sessions:
        dt_raw=conv.get(f"session_{n}_date_time")
        if not dt_raw: raise RuntimeError(f"{sid}/{key}: missing session date")
        dt=parse_locomo_time(str(dt_raw)+" UTC")
        iso=to_iso(dt)
        am=[]; bm=[]
        for chat in session:
            speaker=str(chat.get("speaker") or "")
            text=str(chat.get("text") or "")
            content=f"{speaker}: {text}"
            if speaker==a:
                am.append({"role":"user","name":a,"content":content,"chat_time":iso})
                bm.append({"role":"assistant","name":a,"content":content,"chat_time":iso})
                user_a+=1;assistant_b+=1
            elif speaker==b:
                am.append({"role":"assistant","name":b,"content":content,"chat_time":iso})
                bm.append({"role":"user","name":b,"content":content,"chat_time":iso})
                assistant_a+=1;user_b+=1
            else:
                raise RuntimeError(f"{sid}/{key}: unexpected speaker {speaker!r}")
        client.add(am,ua)
        client.add(bm,ub)
    ingest_counts[sid]={
      "speaker_a":a,"speaker_b":b,
      "speaker_a_user_memories_expected":user_a,
      "speaker_b_user_memories_expected":user_b,
      "speaker_a_assistant_events":assistant_a,
      "speaker_b_assistant_events":assistant_b,
      "sessions":len(sessions),
    }

rows=[]
for sample in samples:
    sid=str(sample["sample_id"]); conv=sample["conversation"]
    a=str(conv["speaker_a"]); b=str(conv["speaker_b"])
    ua=f"locomo_blind_v2_{sid}_speaker_a"; ub=f"locomo_blind_v2_{sid}_speaker_b"
    for q in sample.get("questions") or []:
        bid=str(q["blind_id"]); question=str(q["question"])
        if hashlib.sha256(question.encode("utf-8")).hexdigest()!=q["question_sha256"]:
            raise RuntimeError(f"{bid}: question hash drift")
        ha=structured_search(ua,question,TOP_K_PER_SPEAKER,"speaker_a")
        hb=structured_search(ub,question,TOP_K_PER_SPEAKER,"speaker_b")
        memories=ha+hb
        if len(memories)>2*TOP_K_PER_SPEAKER: raise RuntimeError("context cap drift")
        rows.append({
          "blind_id":bid,
          "sample_id":sid,
          "question_sha256":q["question_sha256"],
          "question":question,
          "speaker_a":a,
          "speaker_b":b,
          "authorized_memories":memories,
          "authorized_memory_count":len(memories),
          "retrieval":{
            "backend":"OmniMemEval XiaoYuClient literal_source",
            "top_k_per_speaker":TOP_K_PER_SPEAKER,
            "speaker_a_hits":len(ha),
            "speaker_b_hits":len(hb),
          }
        })

ids=[x["blind_id"] for x in rows]
if len(rows)!=200 or len(set(ids))!=200: raise RuntimeError("retrieval membership drift")
if any(m["authority"]!="user_source_history" for x in rows for m in x["authorized_memories"]):
    raise RuntimeError("authority drift")
out={
 "schema":"xiaoyu-locomo-blind-v2-retrieval-snapshot-v1",
 "status":"OFFLINE_GOLD_FREE_RETRIEVAL_COMPLETE",
 "blind_input_sha256":sha(INPUT),
 "xiaoyu_client_path":"external/OmniMemEval/scripts/client_factory/xiaoyu_client.py",
 "xiaoyu_client_sha256":sha(SCRIPTS/"client_factory"/"xiaoyu_client.py"),
 "identity_core_sha256":sha(ROOT/"identity_core.py"),
 "ingest_mode":"literal_source",
 "top_k_per_speaker":TOP_K_PER_SPEAKER,
 "context_cap":20,
 "sample_count":10,
 "question_count":200,
 "ingest_counts":ingest_counts,
 "rows":rows,
 "provider_calls":0,
 "raw_gold_read":False,
 "blind_gold_read":False,
 "formal_touched":False,
}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({
 "status":out["status"],
 "snapshot_sha256":sha(OUT),
 "questions":len(rows),
 "memory_count_min":min(x["authorized_memory_count"] for x in rows),
 "memory_count_max":max(x["authorized_memory_count"] for x in rows),
 "memory_count_avg":sum(x["authorized_memory_count"] for x in rows)/len(rows),
 "provider_calls":0,
 "raw_gold_read":False
},ensure_ascii=False,indent=2))
