#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditor reference composition over exact accepted R47/R49 bytes.

This is NOT an R52 semantic-quality implementation. It binds the existing
pre-frozen R52 structural holdout to the exact accepted R47 store and R49
confirmed-transition components. The runner reads inputs only; gold is used
only later by the frozen scorer.
"""
from __future__ import annotations
import json,re,tempfile,hashlib
from pathlib import Path
from collections import Counter
import r49_structural_v5 as v5
from r47_open_domain_memory_store_frozen import OpenDomainMemoryStore,source_message_id
from r49_atomic_confirmed_transition import R49AtomicConfirmedSemanticTransition
from r52_qa_sufficiency_v7 import select_supported

HERE=Path(__file__).resolve().parent
INPUTS=json.loads((HERE/"r52_holdout_inputs.json").read_text(encoding="utf-8"))
KEY=b"r52-auditor-reference-confirmation-key"
IDENTITY="r52-auditor-reference-identity"

def norm(x): return " ".join(str(x or "").casefold().split())

def exact_quote(text, fragment=None):
    if fragment and fragment in text and text.count(fragment)==1:
        return fragment
    return text

def new_candidate(claim_text, source_text, quote=None):
    return {"claim_text":claim_text.strip(),"evidence_quote":exact_quote(source_text,quote),
            "relation":"NEW","targets":[]}

def semantic_new_candidates(src):
    """Tiny deterministic structural adapter for frozen synthetic families only.

    Public canary text is intentionally not semantically scored and returns no
    claims here. This function never reads gold/evaluator fields.
    """
    text=src["text"]; role=src["source_role"]
    out=[]
    # User synthetic facts.
    pats=[
      (r"^My durable tea preference is (.+)\.$", lambda m:f"My durable tea preference is {m.group(1)}."),
      (r"^My current breakfast choice is (.+)\.$", lambda m:f"My current breakfast choice is {m.group(1)}."),
      (r"^I have two saved plans: (.+)\.$", lambda m:f"I have saved plan {m.group(1)}."),
      (r"^I also have (.+)\.$", lambda m:f"I have saved plan {m.group(1)}."),
      (r"^My current beverage is (.+)\.$", lambda m:f"My current beverage is {m.group(1)}."),
      (r"^My archival project code is (.+)\.$", lambda m:f"My archival project code is {m.group(1)}."),
      (r"^My locker token is (.+)\.$", lambda m:f"My locker token is {m.group(1)}."),
      (r"^I enjoy cycling on weekends (.+)\.$", lambda m:f"I enjoy cycling on weekends {m.group(1)}."),
    ]
    for p,fn in pats:
        m=re.match(p,text)
        if m:
            out.append(new_candidate(fn(m),text))
            return out
    # Generic assistant turns follow accepted R49 v5 raw_history_only semantics.
    # They are preserved as raw source rows and are never projected into user state.
    if role=="assistant":
        return []
    return out

def logical_source_map(case):
    # Caller-owned mapping from accepted R47 source identity to frozen logical source_id.
    return {(str(s["conversation_id"]),str(s["message_id"])):str(s["source_id"]) for s in case["sources"]}

def logical_id_for_row(store,row,case):
    sid=row.get("source_message_id")
    if not sid:return ""
    src=store._source(sid)
    if not src:return ""
    return logical_source_map(case).get((str(src["conversation_id"]),str(src["message_id"])),"")

def normalize_history(store,case):
    conflicts={x["claim_id"] for x in store.current_view().get("conflict",[])}
    out=[];covered=set()
    for r in store.history():
        role=r["source_role"];status=r["status"];cid=r["claim_id"]
        if role=="assistant": auth="conversation_history"
        elif role=="derived": auth="derived_history"
        elif status=="active" and cid in conflicts: auth="user_conflict"
        elif status=="active": auth="user_state"
        else: auth="user_history"
        sid=logical_id_for_row(store,r,case)
        if sid:covered.add(sid)
        out.append({"text":r["claim_text"],"authority":auth,"source_id":sid,"channel":"claim"})
    # Full-dialogue composition branch: preserve accepted R49 raw_history_only
    # assistant turns as conversation_history without creating semantic claims.
    lm=logical_source_map(case)
    for src in store.source_history():
        lid=lm.get((str(src["conversation_id"]),str(src["message_id"])))
        if not lid or lid in covered:continue
        out.append({"text":src["source_text"],
                    "authority":"conversation_history" if src["source_role"]=="assistant" else "user_source_history",
                    "source_id":lid,"channel":"raw_source",
                    "source_role":src["source_role"],"effective_at":int(src["effective_at"])})
    return out

def normalize_current(store,case):
    v=store.current_view();out=[]
    for r in v["current"]:
        out.append({"text":r["claim_text"],"authority":"user_state",
                    "source_id":logical_id_for_row(store,r,case)})
    for r in v["conflict"]:
        out.append({"text":r["claim_text"],"authority":"user_conflict",
                    "source_id":logical_id_for_row(store,r,case)})
    return out

STOP={"what","which","where","when","who","why","how","did","does","do","is","are",
      "my","the","a","an","for","to","of","and","or","in","on","i","me"}

RAW_QUERY_EXPANSIONS={
 "choose":{"choose","chose","chosen","choosing"},
 "chose":{"choose","chose","chosen","choosing"},
 "chosen":{"choose","chose","chosen","choosing"},
 "reserve":{"reserve","reserved","reserving","reservation","reservations"},
 "reserved":{"reserve","reserved","reserving","reservation","reservations"},
 "reservation":{"reserve","reserved","reserving","reservation","reservations"},
 "book":{"book","booked","booking","bookings"},
 "booked":{"book","booked","booking","bookings"},
 "booking":{"book","booked","booking","bookings"},
 "decide":{"decide","decided","decision","decisions"},
 "decided":{"decide","decided","decision","decisions"},
}
def _query_tokens(q):
    xs=re.findall(r"[A-Za-z0-9_-]+",str(q).lower())
    base={x for x in xs if len(x)>2 and x not in STOP}
    out=set(base)
    for x in list(base):
        out.update(RAW_QUERY_EXPANSIONS.get(x,()))
    return sorted(out)

def _raw_source_hits(store,query,limit=7):
    db=store.db
    db.execute("DROP TABLE IF EXISTS temp.r52_source_fts")
    db.execute("""CREATE VIRTUAL TABLE temp.r52_source_fts USING fts5(
      source_message_id UNINDEXED, source_role UNINDEXED, source_text, tokenize='unicode61')""")
    db.executemany("INSERT INTO temp.r52_source_fts VALUES(?,?,?)",[
      (x["source_message_id"],x["source_role"],x["source_text"]) for x in store.source_history()
    ])
    tt=_query_tokens(query)
    if not tt:return []
    fq=" OR ".join('"'+x.replace('"','')+'"' for x in tt)
    return [dict(r) for r in db.execute("""SELECT source_message_id,source_role,source_text,
      bm25(r52_source_fts) AS score FROM temp.r52_source_fts
      WHERE r52_source_fts MATCH ? ORDER BY score LIMIT ?""",(fq,int(limit))).fetchall()]

def normalize_retrieval(store,case,query):
    rows=store.recall(query,mode="history",limit=7)
    out=[];seen=set()
    for r in rows:
        lid=logical_id_for_row(store,r,case)
        out.append({"text":r["text"],"authority":r["authority"],
                    "source_id":lid,"channel":"claim"})
        if lid:seen.add(lid)
    by_sid={x["source_message_id"]:x for x in store.source_history()}
    by_conv_seq={(str(x["conversation_id"]),int(x["message_seq"])):x for x in store.source_history()}
    lm=logical_source_map(case)
    def add(src,channel):
        if not src:return
        lid=lm.get((str(src["conversation_id"]),str(src["message_id"])))
        if not lid or lid in seen:return
        seen.add(lid)
        out.append({"text":src["source_text"],
                    "authority":"conversation_history" if src["source_role"]=="assistant" else "user_source_history",
                    "source_id":lid,"channel":channel,
                    "source_role":src["source_role"],"effective_at":int(src["effective_at"])})
    for h in _raw_source_hits(store,query,7):
        src=by_sid.get(h["source_message_id"]);add(src,"raw_source_hit")
        if src:
            conv=str(src["conversation_id"]);seq=int(src["message_seq"])
            add(by_conv_seq.get((conv,seq-1)),"adjacent_turn")
            add(by_conv_seq.get((conv,seq+1)),"adjacent_turn")
    return out[:7]

def seen_sources(store,case):
    lm=logical_source_map(case)
    rows=[]
    for s in store.source_history():
        lid=lm.get((str(s["conversation_id"]),str(s["message_id"])))
        if lid:
            rows.append({"source_id":lid,"source_role":s["source_role"],
                         "effective_at":int(s["effective_at"])})
    return rows

def current_candidates(store):
    v=store.current_view();out=[]
    for r in v["current"]+v["conflict"]:
        out.append({"id":r["claim_id"],"text":r["claim_text"],
                    "source_role":r["source_role"],
                    "authority":"user_conflict" if r["claim_id"] in {x["claim_id"] for x in v["conflict"]} else "user_state",
                    "status":r["status"],"effective_at":int(r["effective_at"])})
    return out

def state_sig(store):
    v=store.current_view()
    return json.dumps({
      "status":v["status"],
      "current":sorted((x["claim_id"],x["claim_text"],x["status"]) for x in v["current"]),
      "conflict":sorted((x["claim_id"],x["claim_text"],x["status"]) for x in v["conflict"])
    },ensure_ascii=False,sort_keys=True)

def ingest_new(store,src,candidates):
    return store.ingest(src["conversation_id"],src["message_id"],src["message_seq"],
                        src["source_role"],src["text"],src["effective_at"],candidates)

def correction_payload(store,src,new_value):
    priors=current_candidates(store)
    built=v5.build_model_payload([{"source_text":src["text"],"source_role":src["source_role"],
                                  "prior_candidates":priors,"candidate_pool_complete":True}],limit=8)
    comps=built["caller_binding"][0].get("target_components") or []
    if len(comps)!=1:
        return built,None
    raw={"outputs":[{"status":"propose","proposals":[{
      "claim_text":f"My current breakfast choice is {new_value}.",
      "evidence_quote":src["text"],"relation":"SUPERSEDE","target_ids":comps[0]
    }]}]}
    v5.validate_response(raw,built["model_payload"],built["caller_binding"])
    return built,raw

def qa_from_admitted(store,case):
    q=case.get("qa_question")
    if not q:return None,False,[]
    ret=normalize_retrieval(store,case,q)
    cur=normalize_current(store,case)
    # Retrieval relevance and answer sufficiency are separate gates.
    pool=[];seen=set()
    for row in cur+ret:
        key=(row.get("text"),row.get("authority"),row.get("source_id"))
        if key in seen:continue
        seen.add(key);pool.append(row)
    supported=select_supported(q,pool)
    if not supported:
        return None,True,ret
    return supported[0]["text"],False,ret

def handle_unbound(case,store,out):
    src=case["sources"][0]
    prior_text=str(case.get("caller_prior_candidate_text") or "")
    prior={"id":"caller-unbound-prior","text":prior_text,"source_role":"user",
           "authority":"user_state","status":"active","effective_at":max(0,int(src["effective_at"])-1)}
    built=v5.build_model_payload([{"source_text":src["text"],"source_role":"user",
                                  "prior_candidates":[prior],"candidate_pool_complete":True}],limit=6)
    binding=built["caller_binding"][0]
    mode=str(binding.get("binding_mode") or "none")
    # Do not manufacture a destructive target. This is deliberately non-mutating.
    ingest_new(store,src,[])
    out["pending_actions"]=[{"relation":"SUPERSEDE","binding_mode":mode,
                             "confirmable":False,"status":"proposed"}]
    out["mutation_count_total"]=0

def run_case(case,dbpath):
    store=OpenDomainMemoryStore(dbpath)
    out={"id":case["id"],"pending_actions":[],"mutation_count_before_confirmation":0,
         "mutation_count_after_confirmation":0,"mutation_count_total":0}
    try:
        cid=case["id"]
        if cid.startswith("public-unbound-"):
            handle_unbound(case,store,out)
        else:
            # Process all case sources in caller order.
            for idx,src in enumerate(case["sources"]):
                text=src["text"]
                # Explicit destructive correction goes only through R49 pending confirmation.
                m=re.match(r"^Correction: replace (.+?) with (.+?) as my current breakfast choice\.$",text)
                if src["source_role"]=="user" and m:
                    built,raw=correction_payload(store,src,m.group(2))
                    if raw is None:
                        out["pending_actions"].append({"relation":"SUPERSEDE",
                          "binding_mode":str(built["caller_binding"][0].get("binding_mode") or "ambiguous"),
                          "confirmable":False,"status":"proposed"})
                        continue
                    gate=R49AtomicConfirmedSemanticTransition(store,IDENTITY,KEY)
                    before=state_sig(store)
                    p=gate.propose(raw,built["model_payload"],built["caller_binding"],
                        conversation_id=src["conversation_id"],message_id=src["message_id"],
                        message_seq=src["message_seq"],source_role=src["source_role"],
                        source_text=src["text"],effective_at=src["effective_at"])
                    unchanged=(state_sig(store)==before)
                    out["mutation_count_before_confirmation"] += 0 if unchanged else 1
                    out["pending_actions"].append({"relation":"SUPERSEDE",
                        "binding_mode":str(built["caller_binding"][0].get("binding_mode") or "exact"),
                        "confirmable":True,"status":"pending"})
                    out["current_before_confirmation"]=normalize_current(store,case)
                    gate.confirm(p["action_id"],IDENTITY)
                    after=state_sig(store)
                    changed=(after!=before)
                    # Exactly-once check on repeated confirmation.
                    gate.confirm(p["action_id"],IDENTITY)
                    out["mutation_count_after_confirmation"] += 1 if changed else 0
                    out["mutation_count_total"] += 1 if changed else 0
                    out["current_after_confirmation"]=normalize_current(store,case)
                    continue

                # Ambiguous "forget that route" is fail-closed and does not enter R47.
                if src["source_role"]=="user" and re.match(r"^Forget that route; I don't want it anymore\.$",text):
                    built=v5.build_model_payload([{"source_text":text,"source_role":"user",
                        "prior_candidates":current_candidates(store),"candidate_pool_complete":True}],limit=8)
                    mode=str(built["caller_binding"][0].get("binding_mode") or "ambiguous")
                    out["pending_actions"].append({"relation":"RETRACT","binding_mode":mode,
                                                  "confirmable":False,"status":"proposed"})
                    continue

                ingest_new(store,src,semantic_new_candidates(src))

            # Explicit replay: run identical source/candidate ingestion once more to exercise R47.
            if cid.startswith("syn-replay-") and case["sources"]:
                src=case["sources"][0]
                ingest_new(store,src,semantic_new_candidates(src))

        out["seen_sources"]=seen_sources(store,case)
        out["current"]=normalize_current(store,case)
        out["history"]=normalize_history(store,case)
        ans,unk,ret=qa_from_admitted(store,case)
        out["qa_answer"]=ans;out["qa_unknown"]=unk;out["retrieval"]=ret
        # Count only caller-visible case source rows.
        logical={(str(s["conversation_id"]),str(s["message_id"])) for s in case["sources"]}
        out["inserted_source_rows"]=sum(
            (str(s["conversation_id"]),str(s["message_id"])) in logical for s in store.source_history())
        texts=[x["claim_text"] for x in store.history()]
        out["semantic_claim_duplicates"]=max(Counter(texts).values(),default=0)
        return out
    finally:
        store.close()

def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix="r52-components-",dir=HERE) as td:
        root=Path(td)
        for i,c in enumerate(INPUTS):
            results.append(run_case(c,root/f"case-{i}.sqlite"))
    path=HERE/"r52_exact_components_outputs.json"
    path.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary={
      "schema":"r52-open-domain-composition-candidate-v1","n":len(results),
      "r47_sha256":hashlib.sha256((HERE/"r47_open_domain_memory_store_frozen.py").read_bytes()).hexdigest(),
      "r49_structural_sha256":hashlib.sha256((HERE/"r49_structural_v5.py").read_bytes()).hexdigest(),
      "r49_parent_sha256":hashlib.sha256((HERE/"r49_confirmed_transition.py").read_bytes()).hexdigest(),
      "r49_atomic_sha256":hashlib.sha256((HERE/"r49_atomic_confirmed_transition.py").read_bytes()).hexdigest(),
      "provider_calls":0,"confirmatory_users_read":0
    }
    (HERE/"r52_exact_components_reference_meta.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
