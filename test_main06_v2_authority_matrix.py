# -*- coding: utf-8 -*-
from __future__ import annotations
import tempfile
from pathlib import Path
from identity_core import IdentityStore
import product_memory_bridge_base as baseline
import product_memory_bridge as candidate

ROOT=Path(__file__).resolve().parent

def ids(rows): return [int(x["memory_id"]) for x in rows]

def claim_for_mid(bridge,mid):
    sid=bridge._r47.source_message_id(
        "xiaoyu-product-confirmed-memory",f"memory-{int(mid)}")
    row=bridge.pipeline.store.db.execute(
        "SELECT * FROM claims WHERE source_message_id=? ORDER BY ordinal",(sid,)
    ).fetchone()
    assert row is not None
    return sid,dict(row)

def mutate(bridge,mid,kind):
    sid,old=claim_for_mid(bridge,mid)
    if kind=="SOURCE_QUARANTINE":
        bridge.pipeline.store.set_source_lifecycle(sid,"quarantined")
        return
    text=f"authority {kind.lower()} replacement Cedar"
    bridge.pipeline.store.ingest(
        "authority-v2-attack",f"{kind.lower()}-{mid}",100000+int(mid),
        "user",text,int(old["effective_at"])+1,
        [{"claim_text":text,"evidence_quote":text,
          "relation":kind,"targets":[str(old["claim_id"])]}],
    )

def one(mod,kind):
    with tempfile.TemporaryDirectory() as td:
        home=Path(td)
        s=IdentityStore(home)
        mid=s.add_memory("authority matrix target Harbor",category="shared",priority=5)
        b=mod.ProductMemoryBridge(home,s,component_root=ROOT)
        try:
            before=ids(b.recall("authority matrix target Harbor",limit=7))
            mutate(b,mid,kind)
            after=ids(b.recall("authority matrix target Harbor",limit=7))
            return before,after,mid
        finally:
            b.close();s.close()

def duplicate(mod):
    with tempfile.TemporaryDirectory() as td:
        home=Path(td);s=IdentityStore(home)
        text="duplicate support green tea"
        low=s.add_memory(text,category="preference",priority=5)
        high=s.add_memory(text,category="preference",priority=5)
        b=mod.ProductMemoryBridge(home,s,component_root=ROOT)
        try:
            initial=ids(b.recall("duplicate support green tea",limit=7))
            sid,_=claim_for_mid(b,high)
            b.pipeline.store.set_source_lifecycle(sid,"quarantined")
            after=ids(b.recall("duplicate support green tea",limit=7))
            return initial,after,low,high
        finally:
            b.close();s.close()

def main():
    for kind in ("SOURCE_QUARANTINE","SUPERSEDE","RETRACT","CONFLICT"):
        bb,ba,bmid=one(baseline,kind)
        cb,ca,cmid=one(candidate,kind)
        assert bb==[bmid] and ba==[bmid],(kind,bb,ba)
        assert cb==[cmid] and ca==[],(kind,cb,ca)
        print("PASS",kind,"baseline_stale",ba,"candidate",ca)
    bi,ba,bl,bh=duplicate(baseline)
    ci,ca,cl,ch=duplicate(candidate)
    assert bi==[bh] and ba==[bh],(bi,ba,bl,bh)
    assert ci==[ch] and ca==[cl],(ci,ca,cl,ch)
    print("PASS DUPLICATE_FALLBACK",ca)
    print("SUMMARY 5 / 5 PASS")

if __name__=="__main__":
    main()
