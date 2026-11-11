#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XiaoYu V1 minimal longitudinal product shadow.

Synthetic/public-free only. Zero provider calls. Does not modify identity_core.py
or any formal user identity state. Reuses exact confirmatory-frozen ACCEPT_E1
components to exercise a vertical product path.
"""
from __future__ import annotations
import json, shutil, statistics, sys, tempfile, time
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
FROZEN=ROOT/"governance"/"confirmatory_frozen"
sys.path.insert(0,str(FROZEN))

from product_shadow_r52_adapter_v1 import ProductShadowR52Composition as R52Composition
import r49_structural_v5 as structural
import r51_semantic_binder_v4 as r51
import R50_TYPED_CONSUMER_V2_FROZEN as r50

OUT=ROOT/"governance"/"PRODUCT_SHADOW_V1_METRICS.json"

def src(sid,seq,role,text,t=None,conv="shadow-main"):
    return {
      "source_id":sid,"conversation_id":conv,"message_id":sid,
      "message_seq":seq,"source_role":role,"text":text,
      "effective_at":int(t if t is not None else seq)
    }

def texts(rows,authority=None):
    return [x["text"] for x in rows if authority is None or x.get("authority")==authority]

def current_texts(c):
    return [x["text"] for x in c.current_rows() if x["authority"]=="user_state"]

def pending_confirm(c,source,raw_projection=None):
    before=list(current_texts(c))
    r=c.ingest_source(source,raw_projection=raw_projection)
    assert r["kind"]=="pending",r
    after=list(current_texts(c))
    assert before==after,("unconfirmed_mutated",before,after)
    rec=r["pending"]
    assert rec["confirmable"] and rec["status"]=="pending",rec
    cr=c.confirm(rec["action_id"])
    assert cr["status"] in ("applied","applied_recovered"),cr
    return r,cr

def build_conflict_projection(c,source,new_claim):
    pri,complete=c._prior(source)
    built=structural.build_model_payload([{
      "source_text":source["text"],"source_role":source["source_role"],
      "prior_candidates":pri,"candidate_pool_complete":complete
    }],limit=6)
    bind=built["caller_binding"][0]
    comps=bind.get("target_components") or []
    assert len(comps)==1,(bind,pri)
    return {"outputs":[{"status":"propose","proposals":[{
      "claim_text":new_claim,"evidence_quote":source["text"],
      "relation":"CONFLICT","target_ids":list(comps[0])
    }]}]}

def rebind(c,sources):
    for s in sources:
        c._bind_source(s)

def p95(xs):
    if not xs:return 0.0
    ys=sorted(xs)
    return ys[min(len(ys)-1,int(round((len(ys)-1)*0.95)))]

def timed_retrieve(c,q,n=80):
    xs=[];counts=[]
    for _ in range(n):
        t=time.perf_counter()
        rr=c.retrieve(q,limit=7)
        xs.append((time.perf_counter()-t)*1000)
        counts.append(len(rr))
    return {"n":n,"median_ms":statistics.median(xs),"p95_ms":p95(xs),
            "max_ms":max(xs),"max_context_rows":max(counts)}

def temporal_shadow():
    ev=[
      {"evidence_id":"city-1","source_role":"user","authority":"user_state","lifecycle":"active",
       "binding":"state","state_key":"home city","value":"Suzhou",
       "effective_at":"2026-01-10T09:00:00+08:00","text":"My home city was Suzhou."},
      {"evidence_id":"city-2","source_role":"user","authority":"user_state","lifecycle":"active",
       "binding":"state","state_key":"home city","value":"Shanghai",
       "effective_at":"2026-03-15T09:00:00+08:00","text":"My current home city is Shanghai."}
    ]
    q="What is my current home city?"
    b=r51.bind(q,ev,question_time="2026-10-29T18:00:00+08:00")
    if b.get("status")!="typed":
        return {"pass":False,"binder":b}
    ans=r50.consume(b["spec"],b["events"])
    # Same-time conflicting direct user state must fail closed.
    conflict=list(ev)+[
      {"evidence_id":"city-3","source_role":"user","authority":"user_state","lifecycle":"active",
       "binding":"state","state_key":"home city","value":"Nanjing",
       "effective_at":"2026-03-15T09:00:00+08:00","text":"My current home city is Nanjing."}
    ]
    b2=r51.bind(q,conflict,question_time="2026-10-29T18:00:00+08:00")
    ans2=(r50.consume(b2["spec"],b2["events"]) if b2.get("status")=="typed" else None)
    ok=(ans.get("status")=="resolved" and ans.get("answer")=="Shanghai"
        and ans2 is not None and ans2.get("status")=="conflict")
    return {"pass":ok,"binder":b,"consumer":ans,
            "conflict_binder":b2,"conflict_consumer":ans2}

def main():
  all_sources=[]
  checks={}
  with tempfile.TemporaryDirectory(prefix="xiaoyu-product-shadow-",dir=ROOT/"governance") as td:
    td=Path(td);db=td/"primary.sqlite3"
    c=R52Composition(db,identity_id="shadow-owner-1",
                     confirmation_key=b"shadow-product-confirm-key-v1-2026")
    try:
      # Initial durable user preference + assistant conversation history.
      s1=src("s1",1,"user","My preferred exercise is running.")
      s2=src("s2",2,"assistant","I suggested stretching after running.")
      all_sources += [s1,s2]
      assert c.ingest_source(s1)["kind"]=="ingested"
      assert c.ingest_source(s2)["kind"]=="ingested"
      checks["initial_user_current"]=any("running" in x.lower() for x in current_texts(c))
      checks["assistant_not_user_current"]=not any("stretching" in x.lower() for x in current_texts(c))
      checks["assistant_history_retrievable"]=any(
        "stretching" in x["text"].lower() and x["authority"]=="conversation_history"
        for x in c.retrieve("stretching",7))

      # Correction must be pending first, then atomically replace current state.
      s3=src("s3",3,"user",
             "I changed my preferred exercise to swimming; running is no longer my choice.")
      all_sources.append(s3)
      pending_confirm(c,s3)
      cur=current_texts(c)
      checks["correction_new_current"]=any("swimming" in x.lower() for x in cur)
      checks["correction_old_not_current"]=not any(x.strip()=="My preferred exercise is running." for x in cur)
      a,ins,rr=c.answer("What is my preferred exercise?")
      checks["answer_uses_corrected_state"]=(not ins and a is not None and "swimming" in a.lower())

      # Retraction must clear current state, while history/provenance remains.
      s4=src("s4",4,"user","Forget that my preferred exercise is swimming.")
      all_sources.append(s4)
      pending_confirm(c,s4)
      cur=current_texts(c)
      checks["retraction_removes_current"]=not any("swimming" in x.lower() and "forget" not in x.lower() for x in cur)
      hist=c.history_rows()
      checks["retraction_preserves_history"]=any("swimming" in x["text"].lower() for x in hist)

      # Unrelated stable memory survives destructive operations.
      s5=src("s5",5,"user","My bird's name is Pippin.")
      all_sources.append(s5)
      c.ingest_source(s5)
      checks["unrelated_memory_current"]=any("pippin" in x.lower() for x in current_texts(c))

      # Explicit unresolved conflict over a separate fact.
      s6=src("s6",6,"user","My emergency contact is Mira.")
      all_sources.append(s6);c.ingest_source(s6)
      s7=src("s7",7,"user","My emergency contact is Noor; this conflicts with the earlier contact.")
      all_sources.append(s7)
      raw=build_conflict_projection(c,s7,"My emergency contact is Noor.")
      pending_confirm(c,s7,raw_projection=raw)
      cv=c.store.current_view()
      checks["conflict_materialized"]=(cv["status"]=="unresolved_conflict" and len(cv["conflict"])>=2)
      ca,cins,crr=c.answer("Who is my emergency contact?")
      checks["conflict_answer_fails_closed"]=bool(cins and ca is None)

      baseline_latency=timed_retrieve(c,"Pippin bird",80)
      state_before_restart=c.store.current_view()
    finally:
      c.close()

    # Restart: rebind trusted source envelopes, no semantic replay.
    c=R52Composition(db,identity_id="shadow-owner-1",
                     confirmation_key=b"shadow-product-confirm-key-v1-2026")
    try:
      rebind(c,all_sources)
      checks["restart_current_exact"]=c.store.current_view()==state_before_restart
      ra,rins,rr=c.answer("What is my bird's name?")
      checks["restart_answer_continuity"]=(not rins and ra is not None and "pippin" in ra.lower())
    finally:c.close()

    # Cross-runtime/local-store migration: copy closed SQLite and re-open independently.
    migrated=td/"migrated.sqlite3";shutil.copy2(db,migrated)
    c=R52Composition(migrated,identity_id="shadow-owner-1",
                     confirmation_key=b"shadow-product-confirm-key-v1-2026")
    try:
      rebind(c,all_sources)
      checks["migration_current_exact"]=c.store.current_view()==state_before_restart
      ma,mins,mrr=c.answer("What is my bird's name?")
      checks["migration_answer_continuity"]=(not mins and ma is not None and "pippin" in ma.lower())

      # Grow memory with 1000 independent synthetic facts.
      for i in range(1000):
        sg=src(f"g{i}",1000+i,"user",f"My archive marker {i} is Quartz{i}.",
               1000+i,conv="growth")
        c.ingest_source(sg)
      checks["growth_source_count_ge_1007"]=c.source_count()>=1007
      growth_latency=timed_retrieve(c,"Pippin bird",80)
      gr=c.retrieve("Pippin bird",limit=7)
      checks["growth_context_bounded"]=len(gr)<=7
      checks["growth_answer_preserved"]=any("pippin" in x["text"].lower() for x in gr)
      # Engineering shadow guard, intentionally generous and not a formal SLO.
      checks["growth_retrieval_p95_under_100ms"]=growth_latency["p95_ms"]<100.0
    finally:c.close()

  temporal=temporal_shadow()
  checks["typed_temporal_path"]=bool(temporal["pass"])
  report={
    "schema":"xiaoyu-product-shadow-v1",
    "date":"2026-10-29",
    "scope":"synthetic longitudinal vertical slice; no production identity mutation; zero provider calls",
    "components":{
      "R52":"confirmatory_frozen/r52_composition_candidate_v8.py",
      "R49":"confirmatory_frozen/r49_atomic_confirmed_transition.py",
      "R51":"confirmatory_frozen/r51_semantic_binder_v4.py",
      "R50":"confirmatory_frozen/R50_TYPED_CONSUMER_V2_FROZEN.py"
    },
    "checks":checks,
    "passed":sum(bool(x) for x in checks.values()),
    "total":len(checks),
    "pass":all(bool(x) for x in checks.values()),
    "retrieval_latency_ms":{"before_growth":baseline_latency,"after_1000_facts":growth_latency},
    "temporal":temporal,
    "provider_calls":0,
    "private_user_data_used":False,
    "formal_identity_state_modified":False
  }
  OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
  print(json.dumps(report,ensure_ascii=False,indent=2))
  if not report["pass"]: raise SystemExit(2)

if __name__=="__main__":main()
