# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Optional

import product_memory_bridge_base as base
from compositional_query_state_view import QueryUnknown, _source_ok, evaluate

DEFAULT_MAX_ANCHORS=32
DEFAULT_MAX_DEPTH=16

def _needs_history(plan: Dict[str, Any]) -> bool:
    return any(str(a.get("pred"))!="current" for a in plan.get("atoms",[]))

def _quote_fts(token: str) -> str:
    return '"' + str(token).replace('"','""') + '"'

def _history_anchor_ids(bridge: Any, plan: Dict[str, Any], max_anchors: int) -> List[int]:
    qk=sorted(base._keywords(str(plan.get("query_text",""))))
    if not qk:
        return []
    match=" OR ".join(_quote_fts(x) for x in qk[:256])
    rows=bridge.index.execute(
        """SELECT CAST(product_memory_history_fts.memory_id AS INTEGER) AS memory_id
           FROM product_memory_history_fts
           JOIN product_memory_meta
             ON product_memory_meta.memory_id=CAST(product_memory_history_fts.memory_id AS INTEGER)
           WHERE product_memory_history_fts MATCH ?
             AND product_memory_meta.status='superseded'
           ORDER BY bm25(product_memory_history_fts)
           LIMIT ?""",
        (match,max(1,min(int(max_anchors),128))),
    ).fetchall()
    return [int(r["memory_id"]) for r in rows]

def _row(store: Any, memory_id: int):
    return store.conn.execute(
        "SELECT memory_id,category,text,status,source_event,priority "
        "FROM memories WHERE memory_id=?",(int(memory_id),)
    ).fetchone()

def _forward_children(store: Any, parent_memory_id: int):
    return list(store.conn.execute(
        """
        SELECT m.memory_id,m.category,m.text,m.status,m.source_event,m.priority,
               e.kind,e.actor
        FROM events e
        JOIN memories m ON m.source_event=e.event_id
        WHERE e.kind='memory.corrected'
          AND CAST(json_extract(e.extra,'$.supersedes_memory_id') AS INTEGER)=?
        ORDER BY m.memory_id
        """,(int(parent_memory_id),)
    ))

def _active_descendant(store: Any, anchor_id: int, max_depth: int) -> Optional[int]:
    anchor=_row(store,anchor_id)
    if anchor is None or str(anchor["status"])!="superseded" or not _source_ok(store,anchor):
        return None
    category=str(anchor["category"])
    cur=int(anchor["memory_id"])
    seen={cur}
    for _ in range(int(max_depth)):
        children=_forward_children(store,cur)
        if not children:
            return None
        if len(children)!=1:
            raise QueryUnknown("ambiguous_forward_lineage")
        child=children[0]
        cid=int(child["memory_id"])
        if cid in seen:
            raise QueryUnknown("forward_lineage_cycle")
        seen.add(cid)
        if str(child["category"])!=category:
            raise QueryUnknown("forward_category_drift")
        if child["actor"]!="user" or child["kind"]!="memory.corrected" or not _source_ok(store,child):
            return None
        status=str(child["status"])
        if status=="active":
            return cid
        if status=="superseded":
            cur=cid
            continue
        return None
    raise QueryUnknown("forward_lineage_depth_exceeded")

def evaluate_status_partitioned_history(
    store: Any,
    bridge: Any,
    plan: Dict[str, Any],
    *,
    max_anchors: int=DEFAULT_MAX_ANCHORS,
    max_depth: int=DEFAULT_MAX_DEPTH,
) -> Dict[str, Any]:
    current=list(bridge.recall(str(plan.get("query_text","")),limit=int(plan.get("limit",7))))
    current_ids=[int(r["memory_id"]) for r in current if "memory_id" in r]
    anchor_ids=_history_anchor_ids(bridge,plan,max_anchors) if _needs_history(plan) else []
    descendant_ids=[]
    seen_desc=set()
    for aid in anchor_ids:
        did=_active_descendant(store,aid,max_depth)
        if did is not None and did not in seen_desc:
            seen_desc.add(did); descendant_ids.append(did)
    candidate_ids=[]
    seen=set()
    for mid in current_ids+descendant_ids:
        if mid not in seen:
            seen.add(mid); candidate_ids.append(mid)
    res=evaluate(store,plan,mechanism="full_snapshot_join",candidate_ids=candidate_ids)
    res["selection"]={
        "current_ids":current_ids,
        "history_anchor_ids":anchor_ids,
        "history_descendant_ids":descendant_ids,
        "candidate_ids":candidate_ids,
        "max_anchors":int(max_anchors),
        "max_depth":int(max_depth),
    }
    return res
