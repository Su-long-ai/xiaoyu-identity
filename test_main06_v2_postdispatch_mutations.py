# -*- coding: utf-8 -*-
from __future__ import annotations
import tempfile,threading
from pathlib import Path
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from send_guard import FreshnessChanged,capture_expectations,dual_guarded_chat,persist_assistant_if_fresh
ROOT=Path(__file__).resolve().parent

def run(kind):
    with tempfile.TemporaryDirectory() as td:
        home=Path(td);s=IdentityStore(home)
        mid=s.add_memory("postdispatch mutation target",category="shared",priority=5)
        b=ProductMemoryBridge(home,s,component_root=ROOT)
        gate=threading.Event();finish=threading.Event();out={}
        try:
            rows=b.recall("postdispatch mutation target",limit=7)
            gen=s.memory_generation();ex=capture_expectations(b,rows)
            def fake(config,messages,on_dispatched=None):
                on_dispatched();gate.set();assert finish.wait(3)
                return "stale reply",{}
            def worker():
                try:
                    out["reply"]=dual_guarded_chat(
                        fake,{},[],s.db_path,b.db_path,gen,ex
                    )[0]
                except FreshnessChanged:
                    out["stale_rejected"]=True
            t=threading.Thread(target=worker);t.start();assert gate.wait(3)
            if kind=="retract": assert s.retract_memory(mid)
            elif kind=="archive": assert s.archive_memory(mid)
            elif kind=="correct": s.correct_memory(mid,"postdispatch replacement")
            else: raise AssertionError(kind)
            finish.set();t.join(3);assert not t.is_alive()
            assert out.get("stale_rejected") is True,(kind,out)
            assert "reply" not in out,(kind,out)
            assert s.actual_progress()["assistant_replies"]==0
        finally:
            finish.set();b.close();s.close()

for k in ("retract","archive","correct"):
    run(k);print("PASS",k)
print("SUMMARY 3 / 3 PASS")
