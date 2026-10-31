# -*- coding: utf-8 -*-
from __future__ import annotations
import tempfile, threading, time
from pathlib import Path

from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from send_guard import (
    FreshnessChanged, capture_expectations, dual_guarded_chat,
    persist_assistant_if_fresh,
)

ROOT=Path(__file__).resolve().parent

def setup(text="freshness target secret-alpha"):
    td=tempfile.TemporaryDirectory()
    home=Path(td.name)
    store=IdentityStore(home)
    mid=store.add_memory(text,category="shared",priority=5)
    bridge=ProductMemoryBridge(home,store,component_root=ROOT)
    rows=bridge.recall("freshness target secret-alpha",limit=7)
    assert any(int(x["memory_id"])==mid for x in rows), rows
    gen=store.memory_generation()
    ex=capture_expectations(bridge,rows)
    return td,store,bridge,mid,rows,gen,ex

def sid_for(bridge,mid):
    return bridge._r47.source_message_id(
        "xiaoyu-product-confirmed-memory",f"memory-{int(mid)}"
    )

def assistant_count(store):
    return store.actual_progress()["assistant_replies"]

def expect_stale(fn):
    try:
        fn()
    except FreshnessChanged:
        return
    raise AssertionError("expected FreshnessChanged")

def test_preexisting_r47_quarantine_is_filtered():
    td,s,b,mid,rows,gen,ex=setup()
    try:
        b.pipeline.store.set_source_lifecycle(sid_for(b,mid),"quarantined")
        assert b.recall("freshness target secret-alpha",limit=7)==[]
    finally:
        b.close();s.close();td.cleanup()

def test_r47_changes_after_recall_before_dispatch_blocks_network():
    td,s,b,mid,rows,gen,ex=setup()
    called=[]
    try:
        b.pipeline.store.set_source_lifecycle(sid_for(b,mid),"quarantined")
        def fake(config,messages,on_dispatched=None):
            called.append(True)
            if on_dispatched:on_dispatched()
            return "bad",{}
        expect_stale(lambda: dual_guarded_chat(
            fake,{},[{"role":"system","content":"secret-alpha"}],
            s.db_path,b.db_path,gen,ex
        ))
        assert called==[], called
    finally:
        b.close();s.close();td.cleanup()

def test_identity_changes_after_recall_before_dispatch_blocks_network():
    for mutation in ("retract","archive","correct","confirmed_add"):
        td,s,b,mid,rows,gen,ex=setup("identity mutation target secret-alpha")
        called=[]
        try:
            if mutation=="retract": assert s.retract_memory(mid)
            elif mutation=="archive": assert s.archive_memory(mid)
            elif mutation=="correct": s.correct_memory(mid,"identity mutation replacement beta")
            else: s.add_memory("new confirmed memory gamma",category="shared",priority=4)
            def fake(config,messages,on_dispatched=None):
                called.append(True)
                if on_dispatched:on_dispatched()
                return "bad",{}
            expect_stale(lambda: dual_guarded_chat(
                fake,{},[{"role":"system","content":"secret-alpha"}],
                s.db_path,b.db_path,gen,ex
            ))
            assert called==[], (mutation,called)
        finally:
            b.close();s.close();td.cleanup()

def test_postdispatch_identity_mutation_rejects_reply_persistence():
    td,s,b,mid,rows,gen,ex=setup()
    dispatched=threading.Event();finish=threading.Event();out={}
    try:
        def fake(config,messages,on_dispatched=None):
            on_dispatched();dispatched.set()
            assert finish.wait(3)
            return "old answer secret-alpha",{}
        def run():
            out["reply"]=dual_guarded_chat(
                fake,{},[{"role":"system","content":"secret-alpha"}],
                s.db_path,b.db_path,gen,ex
            )[0]
        t=threading.Thread(target=run);t.start()
        assert dispatched.wait(3)
        t0=time.perf_counter();assert s.retract_memory(mid)
        assert time.perf_counter()-t0<0.25
        finish.set();t.join(3);assert not t.is_alive()
        before=assistant_count(s)
        expect_stale(lambda: persist_assistant_if_fresh(s,b,gen,ex,out["reply"]))
        assert assistant_count(s)==before==0
    finally:
        finish.set();b.close();s.close();td.cleanup()

def test_postdispatch_r47_mutation_rejects_reply_persistence():
    td,s,b,mid,rows,gen,ex=setup()
    dispatched=threading.Event();finish=threading.Event();out={}
    try:
        def fake(config,messages,on_dispatched=None):
            on_dispatched();dispatched.set()
            assert finish.wait(3)
            return "old answer secret-alpha",{}
        def run():
            out["reply"]=dual_guarded_chat(
                fake,{},[{"role":"system","content":"secret-alpha"}],
                s.db_path,b.db_path,gen,ex
            )[0]
        t=threading.Thread(target=run);t.start()
        assert dispatched.wait(3)
        t0=time.perf_counter()
        b.pipeline.store.set_source_lifecycle(sid_for(b,mid),"quarantined")
        assert time.perf_counter()-t0<0.25
        finish.set();t.join(3);assert not t.is_alive()
        expect_stale(lambda: persist_assistant_if_fresh(s,b,gen,ex,out["reply"]))
        assert assistant_count(s)==0
    finally:
        finish.set();b.close();s.close();td.cleanup()

def test_queue_window_mutation_is_caught_at_final_persist():
    for kind in ("identity","r47"):
        td,s,b,mid,rows,gen,ex=setup()
        try:
            def fake(config,messages,on_dispatched=None):
                on_dispatched()
                return "reply before pump",{}
            reply,_=dual_guarded_chat(
                fake,{},[{"role":"system","content":"secret-alpha"}],
                s.db_path,b.db_path,gen,ex
            )
            if kind=="identity": assert s.retract_memory(mid)
            else: b.pipeline.store.set_source_lifecycle(sid_for(b,mid),"quarantined")
            expect_stale(lambda: persist_assistant_if_fresh(s,b,gen,ex,reply))
            assert assistant_count(s)==0
        finally:
            b.close();s.close();td.cleanup()

def test_unchanged_request_persists_normally():
    td,s,b,mid,rows,gen,ex=setup()
    try:
        def fake(config,messages,on_dispatched=None):
            on_dispatched();return "fresh normal answer",{}
        reply,_=dual_guarded_chat(fake,{},[],s.db_path,b.db_path,gen,ex)
        eid=persist_assistant_if_fresh(s,b,gen,ex,reply)
        assert eid>0
        assert assistant_count(s)==1
        assert s.latest_dialog(4)[-1]["content"]=="fresh normal answer"
    finally:
        b.close();s.close();td.cleanup()

def test_provider_exception_releases_both_writers():
    td,s,b,mid,rows,gen,ex=setup()
    try:
        def fake(config,messages,on_dispatched=None):
            on_dispatched()
            raise RuntimeError("synthetic provider failure")
        try:
            dual_guarded_chat(fake,{},[],s.db_path,b.db_path,gen,ex)
        except RuntimeError:
            pass
        else:
            raise AssertionError("provider failure missing")
        t0=time.perf_counter();assert s.retract_memory(mid)
        b.pipeline.store.set_source_lifecycle(sid_for(b,mid),"quarantined")
        assert time.perf_counter()-t0<0.25
    finally:
        b.close();s.close();td.cleanup()

def test_growth_pending_guard_is_present():
    src=Path("companion.py").read_text(encoding="utf-8")
    p=src.index("def approve():")
    q=src.index("FISH.propose_growth(text,self.reflection or [],confirmed=True)",p)
    segment=src[p:q]
    assert "if self.pending:" in segment and "return" in segment

if __name__=="__main__":
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn();print("PASS",fn.__name__)
    print("SUMMARY",len(tests),"/",len(tests),"PASS")
