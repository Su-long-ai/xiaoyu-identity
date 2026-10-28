#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a zero-call, gold-free source-pair manifest for the already-exposed HaluMem pilot.
This is a transition candidate input artifact only; it does not authorize provider calls.
"""
from __future__ import annotations
import hashlib,json,re,statistics
from pathlib import Path

ROOT=Path(r"D:\dsh-fish");G=ROOT/"governance"
SPLIT=json.loads((G/"E2_SPLIT_MANIFEST.json").read_text("utf-8"))
EXEC=json.loads((G/"E2_PILOT_EXECUTION_MANIFEST.json").read_text("utf-8"))
HALU=ROOT/"external"/"halumem_dataset_cache"

def hobj(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def main():
    pilot=set(str(x) for x in SPLIT["halumem"]["pilot_uuids"])
    frozen_ids=set(EXEC["tracks"]["halumem_extract"]["case_ids"])
    rows=[];seen=set();pair_chars=[];role_counts={"user":0,"assistant":0}
    variants=(("m","HaluMem-Medium.jsonl"),("l","HaluMem-Long.jsonl"))
    uuid_re=re.compile(r'"uuid"\s*:\s*"([^"]+)"')
    for short,name in variants:
        path=HALU/name
        with path.open("r",encoding="utf-8") as f:
            for raw in f:
                m=uuid_re.search(raw[:4096])
                if not m or m.group(1) not in pilot:
                    continue
                o=json.loads(raw);uuid=str(o["uuid"])
                uh=hashlib.sha256(uuid.encode()).hexdigest()[:12]
                for si,sess in enumerate(o["sessions"]):
                    dialogue=sess.get("dialogue") or []
                    for ti,msg in enumerate(dialogue):
                        if str(msg.get("role") or "").lower()!="user":continue
                        cid=f"hm-{short}-i-{uh}-{si}-{ti}"
                        if cid not in frozen_ids:continue
                        if ti+1>=len(dialogue):
                            raise RuntimeError(f"{cid}: user turn has no following assistant reply")
                        nxt=dialogue[ti+1]
                        if str(nxt.get("role") or "").lower()!="assistant":
                            raise RuntimeError(f"{cid}: next turn is not assistant")
                        pair={
                          "case_id":cid,
                          "variant":name,
                          "source_messages":[
                            {"message_index":ti,"role":"user","text":str(msg.get("content") or "")},
                            {"message_index":ti+1,"role":"assistant","text":str(nxt.get("content") or "")}
                          ]
                        }
                        pair["source_pair_sha256"]=hobj(pair["source_messages"])
                        rows.append(pair);seen.add(cid)
                        role_counts["user"]+=1;role_counts["assistant"]+=1
                        pair_chars.append(sum(len(x["text"]) for x in pair["source_messages"]))
    missing=sorted(frozen_ids-seen);extra=sorted(seen-frozen_ids)
    if missing or extra or len(rows)!=647:
        raise RuntimeError(f"coverage mismatch rows={len(rows)} missing={len(missing)} extra={len(extra)}")
    rows.sort(key=lambda x:x["case_id"])
    chars=sorted(pair_chars)
    def pct(p):
        if not chars:return 0
        return chars[min(len(chars)-1,int(round((len(chars)-1)*p)))]
    meta={
      "schema":"xiaoyu-e2-halumem-pair-source-candidate-v1",
      "status":"INPUT_CANDIDATE_ONLY_NO_PAID_EXECUTION",
      "basis_execution_manifest_sha256":hashlib.sha256((G/"E2_PILOT_EXECUTION_MANIFEST.json").read_bytes()).hexdigest(),
      "split_sha256":hashlib.sha256((G/"E2_SPLIT_MANIFEST.json").read_bytes()).hexdigest(),
      "case_count":len(rows),
      "original_frozen_extract_case_ids_preserved":len(seen)==len(frozen_ids)==647,
      "source_role_counts":role_counts,
      "pair_character_count":{"mean":statistics.mean(chars),"median":statistics.median(chars),
        "p95":pct(.95),"p99":pct(.99),"max":max(chars)},
      "pair_rows_sha256":hobj(rows),
      "forbidden_fields_absent":["memory_points","questions","answer","evidence","original_memories"],
      "confirmatory_user_records_selected_or_analyzed":0,
      "provider_calls":0,
      "note":"Each old user-turn extraction anchor is deterministically expanded to that user source plus its immediately following assistant source. This changes payload semantics and therefore requires a new frozen transition manifest before any paid call."
    }
    (G/"E2_HALUMEM_PAIR_SOURCE_CANDIDATE.json").write_text(
      json.dumps({"metadata":meta,"cases":rows},ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
