# -*- coding: utf-8 -*-
"""Deterministic product-level longitudinal smoke for XiaoYu memory.

This is not a scientific benchmark. It protects the real product contract:
large-memory retrieval, correction, retraction, restart continuity, incremental sync,
and canonical-source authority non-amplification.
No provider/model/network calls are made.
"""
from __future__ import annotations
import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge


def timed(fn, repeat=1):
    xs=[]
    out=None
    for _ in range(repeat):
        t=time.perf_counter()
        out=fn()
        xs.append((time.perf_counter()-t)*1000)
    return out, xs


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--repeat", type=int, default=20)
    ap.add_argument("--max-median-recall-ms", type=float, default=75.0)
    ap.add_argument("--max-restart-ms", type=float, default=1000.0)
    args=ap.parse_args()
    n=max(50,int(args.count))
    repeat=max(3,int(args.repeat))

    with tempfile.TemporaryDirectory() as td:
        home=Path(td)
        store=IdentityStore(home)
        target=None
        for i in range(n):
            mid=store.add_memory(
                f"长期记忆编号{i}，主题{i%97}，偏好项目{i%31}，阶段{i%13}",
                category="preference", priority=3+(i%3)
            )
            if i == n//2:
                target=mid

        # Regression for the provenance-laundering P1: restored/legacy/direct-DB
        # active rows may exist even though current add_memory() rejects them.
        # They must never become model-visible user_state.
        invalid_ids=[]
        invalid_events=[
            store.record("conversation.assistant","assistant","错误来源：助手声称用户喜欢薄荷茶"),
            store.record("system.synthetic","system","错误来源：系统假定用户喜欢爵士乐"),
        ]
        invalid_texts=["错误来源：助手声称用户喜欢薄荷茶","错误来源：系统假定用户喜欢爵士乐"]
        with store.conn:
            for event_id,text in zip(invalid_events,invalid_texts):
                seq=store._next_memory_change_seq()
                cur=store.conn.execute(
                    """INSERT INTO memories(
                           created_at,updated_at,category,text,source_event,
                           priority,status,change_seq)
                       VALUES(datetime('now'),datetime('now'),'preference',?,?,?,?,?)""",
                    (text,event_id,5,"active",seq),
                )
                invalid_ids.append(int(cur.lastrowid))

        t=time.perf_counter()
        bridge=ProductMemoryBridge(home,store,component_root=ROOT)
        initial_build_ms=(time.perf_counter()-t)*1000

        rows, recall_ms=timed(
            lambda: bridge.recall(
                f"长期记忆编号{n//2} 主题{(n//2)%97} 偏好项目{(n//2)%31}",
                limit=7
            ),
            repeat=repeat,
        )
        target_hit=any(x["memory_id"]==target for x in rows)
        provenance_invalid_initial_absent=all(
            all(x["memory_id"]!=mid for x in bridge.recall(text,limit=20))
            for mid,text in zip(invalid_ids,invalid_texts)
        )
        provenance_invalid_initial_quarantined=all(
            bridge.index.execute(
                "SELECT status FROM product_memory_meta WHERE memory_id=?",(mid,)
            ).fetchone()["status"]=="quarantined"
            for mid in invalid_ids
        )

        corrected=store.correct_memory(target,"长期更正：我现在固定偏好低重心安静鞋")
        bridge.sync()
        correction_hit=any(
            x["memory_id"]==corrected
            for x in bridge.recall("我的鞋子偏好 低重心 安静",limit=7)
        )
        old_absent=all(x["memory_id"]!=target for x in bridge.recall("旧偏好",limit=20))

        store.retract_memory(corrected)
        bridge.sync()
        retraction_absent=all(
            x["memory_id"]!=corrected
            for x in bridge.recall("低重心安静鞋",limit=20)
        )
        bridge.close()
        store.close()

        store2=IdentityStore(home)
        t=time.perf_counter()
        bridge2=ProductMemoryBridge(home,store2,component_root=ROOT)
        restart_ms=(time.perf_counter()-t)*1000
        restart_rows=bridge2.recall(
            f"长期记忆编号{n//3} 主题{(n//3)%97}",limit=7
        )
        restart_continuity=bool(restart_rows)
        provenance_invalid_restart_absent=all(
            all(x["memory_id"]!=mid for x in bridge2.recall(text,limit=20))
            for mid,text in zip(invalid_ids,invalid_texts)
        )
        provenance_invalid_restart_quarantined=all(
            bridge2.index.execute(
                "SELECT status FROM product_memory_meta WHERE memory_id=?",(mid,)
            ).fetchone()["status"]=="quarantined"
            for mid in invalid_ids
        )
        sync_state=bridge2.status()["last_sync"]
        bridge2.close()
        store2.close()

    median_recall=statistics.median(recall_ms)
    p95=sorted(recall_ms)[max(0,int(len(recall_ms)*0.95)-1)]
    checks={
        "target_hit":target_hit,
        "correction_hit":correction_hit,
        "old_absent_after_correction":old_absent,
        "retraction_absent":retraction_absent,
        "restart_continuity":restart_continuity,
        "provenance_invalid_initial_absent":provenance_invalid_initial_absent,
        "provenance_invalid_initial_quarantined":provenance_invalid_initial_quarantined,
        "provenance_invalid_restart_absent":provenance_invalid_restart_absent,
        "provenance_invalid_restart_quarantined":provenance_invalid_restart_quarantined,
        "median_recall_within_budget":median_recall <= args.max_median_recall_ms,
        "restart_within_budget":restart_ms <= args.max_restart_ms,
        "restart_not_full_reconcile":not bool(sync_state.get("full_reconcile")),
    }
    result={
        "schema":"xiaoyu-longitudinal-product-smoke-v2",
        "count":n,
        "initial_build_ms":round(initial_build_ms,2),
        "recall_median_ms":round(median_recall,2),
        "recall_p95_ms":round(p95,2),
        "restart_ms":round(restart_ms,2),
        "restart_sync":sync_state,
        "checks":checks,
        "pass":all(checks.values()),
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["pass"] else 2)


if __name__=="__main__":
    main()
