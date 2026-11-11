#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exact current companion.send ordering recheck for tombstone-write failure."""
from __future__ import annotations
import json,tempfile,gc,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge,safe_product_recall
from model_adapter import project_history
rows=[]
for i in range(16):
    td=Path(tempfile.mkdtemp(prefix="exact-send-",dir=HERE))
    home=td/"home";home.mkdir()
    s=IdentityStore(home);b=None
    oldtok=f"EXACT_DELETE_{i}"; keeptok=f"EXACT_KEEP_{i}"
    try:
        ev=s.record("conversation.user","user",f"My old preference is {oldtok}; my sibling fact is {keeptok}.")
        s.record("conversation.assistant","assistant","Acknowledged.")
        old=s.add_memory(f"My old preference is {oldtok}.",category="preference",priority=5,source_event=ev)
        keep=s.add_memory(f"My sibling fact is {keeptok}.",category="shared",priority=5,source_event=ev)
        b=ProductMemoryBridge(home,s,component_root=ROOT)
        assert any(int(x["memory_id"])==old for x in safe_product_recall(b,oldtok,7)[0])
        with s.conn:
            s.conn.execute("DELETE FROM memories WHERE memory_id=?",(old,))
        original=b._record_physical_delete
        def fail(mid,source_event):
            if int(mid)==int(old):
                raise RuntimeError("synthetic_identity_tombstone_write_failure")
            return original(mid,source_event)
        b._record_physical_delete=fail

        # Exact current companion.send order:
        query="Please answer using my saved information."
        current_event=s.record("conversation.user","user",query)
        memory_rows,recall_error=safe_product_recall(b,query,limit=7)
        sysmsg=s.identity_context(query,memories_override=memory_rows)
        hard_memory_failure=bool(recall_error and not str(recall_error).startswith("quarantined_memories:"))
        history=[
          {"role":m["role"],"content":m["content"],"event_id":m.get("event_id")}
          for m in project_history(
            s,16,
            fail_closed_current_event_id=current_event if hard_memory_failure else None,
          )
        ]
        packed=json.dumps([{"role":"system","content":sysmsg}]+history,ensure_ascii=False)
        during={
          "recall_error":recall_error,
          "hard_memory_failure":hard_memory_failure,
          "history_count":len(history),
          "history_event_ids":[x.get("event_id") for x in history],
          "current_event_only":len(history)==1 and int(history[0].get("event_id") or -1)==int(current_event),
          "deleted_visible":oldtok in packed,
          "sibling_visible":keeptok in packed,
          "current_query_visible":query in packed,
          "memory_rows":len(memory_rows),
          "tombstone_count":s.conn.execute("SELECT count(*) FROM events WHERE kind='memory.deleted' AND content=?",(str(old),)).fetchone()[0]
        }

        b._record_physical_delete=original
        b.sync()
        rows.append({"id":i,"during_failure":during})
    finally:
        if b is not None:
            try:b.close()
            except:pass
        try:s.close()
        except:pass
        gc.collect();shutil.rmtree(td,ignore_errors=True)

out={
 "schema":"xiaoyu-product-exact-send-tombstone-failure-recheck-v1",
 "n":len(rows),
 "deleted_visible":sum(x["during_failure"]["deleted_visible"] for x in rows),
 "current_event_only":sum(x["during_failure"]["current_event_only"] for x in rows),
 "long_term_failclosed":sum(bool(x["during_failure"]["memory_rows"]==0 and x["during_failure"]["recall_error"]) for x in rows),
 "current_query_visible":sum(x["during_failure"]["current_query_visible"] for x in rows),
 "rows":rows,
 "provider_calls":0,
 "private_identity_reads":0
}
(HERE/"PRODUCT_EXACT_SEND_TOMBSTONE_FAILURE_RECHECK_20261029.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),"utf-8")
print(json.dumps({k:v for k,v in out.items() if k!="rows"},ensure_ascii=False,indent=2))
if out["deleted_visible"] or out["current_event_only"]!=len(rows) or out["long_term_failclosed"]!=len(rows):
    raise SystemExit(2)
