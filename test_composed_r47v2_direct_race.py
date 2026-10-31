from pathlib import Path
import tempfile
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge

def ids(rows): return [int(x["memory_id"]) for x in rows]

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
    home=Path(td)/"home"
    store=IdentityStore(home)
    text="composed r47 v2 race sapphire"
    mid=store.add_memory(text,category="shared",priority=5)
    bridge=ProductMemoryBridge(home,store,component_root=Path(__file__).resolve().parent)
    try:
        before=bridge.recall(text,limit=7)
        assert mid in ids(before),before
        sid=bridge._r47.source_message_id("xiaoyu-product-confirmed-memory",f"memory-{mid}")
        original=bridge._r47_authority_batch
        fired={"v":False}
        def hooked(mids, authoritative):
            result=original(mids,authoritative)
            if mid in [int(x) for x in mids] and not fired["v"]:
                fired["v"]=True
                bridge.pipeline.store.set_source_lifecycle(sid,"quarantined")
            return result
        bridge._r47_authority_batch=hooked
        raced=bridge.recall(text,limit=7)
        assert mid not in ids(raced),raced
        assert bridge.linearization_retries >= 1,bridge.linearization_retries
        assert str(bridge.pipeline.store._source(sid)["lifecycle"])=="quarantined"
        print("PASS composed_r47v2_direct_race_no_leak")
        print("PASS retries",bridge.linearization_retries)
    finally:
        bridge.close(); store.close()
