#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, shutil, sys, tempfile, hashlib

ROOT=pathlib.Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
for p in (str(ROOT),str(GOV),str(FROZEN)):
    while p in sys.path: sys.path.remove(p)
    sys.path.insert(0,p)
while str(FROZEN) in sys.path: sys.path.remove(str(FROZEN))
sys.path.insert(0,str(FROZEN))

import formal_v5_answer_overlay_candidate as ov
import r52_composition_candidate_v8 as r52

RUN=GOV/"budget50_halumem_dev_runtime_v1"
EXPECTED=GOV/"stagea_answerer_v5_full_inputs.json"
MEDIUM=ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl"
LONG=ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl"

def load(p): return json.loads(pathlib.Path(p).read_text("utf-8"))

def main():
    split=load(GOV/"E2_SPLIT_MANIFEST.json")["halumem"]
    pilots=set(split["pilot_uuids"])
    hashes={u:hashlib.sha256(u.encode()).hexdigest() for u in pilots}
    recs={}
    for variant,path in (("m",MEDIUM),("l",LONG)):
        for rec in ov.iter_safe_answer_selected(path,pilots):
            recs[(variant,hashes[rec["uuid"]][:12])]=rec
    if len(recs)!=4: raise RuntimeError(f"safe record cardinality {len(recs)}")

    loc={}
    for pp in sorted((RUN/"predictions").glob("*.json")):
        pred=load(pp)
        for li,sess in enumerate(pred.get("sessions") or []):
            for q in sess.get("questions") or []:
                loc[q["qa_case_id"]]=(pp,pred,li,sess)

    expected=load(EXPECTED)
    rows=[]
    mismatch=[]
    for ex in expected["rows"]:
        qid=ex["qa_case_id"]
        pp,pred,li,sess=loc[qid]
        variant=pred["variant"]
        pref=pred["uuid_hash_prefix"]
        rec=recs[(variant,pref)]
        global_si=int(sess["session_index"])
        cp=RUN/"state_checkpoints"/pp.stem/f"session-{li+1:03d}.sqlite3"
        if not cp.is_file(): raise RuntimeError(f"missing cp {cp}")
        with tempfile.TemporaryDirectory(prefix="formal-v5-eq-") as td:
            db=pathlib.Path(td)/"state.sqlite3"
            shutil.copy2(cp,db)
            comp=r52.R52Composition(db,identity_id="formal-v5-eq:"+qid)
            try:
                messages,ctx,meta=ov.build_messages(
                    comp,rec,variant,pref,global_si,ex["question"]
                )
            finally:
                comp.close()
        checks={
          "messages_equal":messages==ex["messages"],
          "context_equal":ctx==ex["authorized_memories"],
          "upper_bound_equal":meta.get("upper_bound")==ex["historical_upper_bound"],
          "same_session_count_equal":meta.get("same_session_candidate_n")==ex["retrieval_meta"].get("same_session_candidate_n"),
        }
        row={
          "qa_case_id":qid,**checks,
          "expected_messages_sha256":hashlib.sha256(json.dumps(ex["messages"],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
          "actual_messages_sha256":hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
          "expected_context_sha256":hashlib.sha256(json.dumps(ex["authorized_memories"],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
          "actual_context_sha256":hashlib.sha256(json.dumps(ctx,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
          "checkpoint_sha256":hashlib.sha256(cp.read_bytes()).hexdigest(),
          "checkpoint_path":cp.relative_to(GOV).as_posix(),
        }
        rows.append(row)
        if not all(checks.values()):
            mismatch.append({
              **row,
              "expected_context":ex["authorized_memories"],
              "actual_context":ctx,
              "expected_messages_sha":hashlib.sha256(json.dumps(ex["messages"],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
              "actual_messages_sha":hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
              "expected_meta":ex["retrieval_meta"],
              "actual_meta":meta,
            })
    out={
      "schema":"xiaoyu-formal-v5-overlay-stagea-equivalence-v1",
      "case_count":len(rows),
      "messages_equal_n":sum(x["messages_equal"] for x in rows),
      "context_equal_n":sum(x["context_equal"] for x in rows),
      "upper_bound_equal_n":sum(x["upper_bound_equal"] for x in rows),
      "same_session_count_equal_n":sum(x["same_session_count_equal"] for x in rows),
      "pass":not mismatch and len(rows)==51,
      "rows":rows,
      "mismatches":mismatch[:6],
      "formal_gold_reads":0,
      "provider_calls":0,
    }
    p=GOV/"FORMAL_V5_OVERLAY_STAGEA_EQUIVALENCE.json"
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:out[k] for k in ["case_count","messages_equal_n","context_equal_n","upper_bound_equal_n","same_session_count_equal_n","pass"]},indent=2))
    raise SystemExit(0 if out["pass"] else 2)

if __name__=="__main__":main()
