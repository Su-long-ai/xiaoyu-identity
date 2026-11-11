# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
from typing import Any, Dict, List

import product_memory_bridge_base as base
from compositional_query_state_view import QueryUnknown, evaluate, isvar
from status_partitioned_history_view import (
    _needs_history, _active_descendant, evaluate_status_partitioned_history,
)

DEFAULT_MAX_EXACT_ANCHORS=8
DEFAULT_MAX_DEPTH=16

_LITERAL_POS={
    "history_previous":1,
    "history_first":1,
    "as_of":2,
    "node_text":1,
}

def _history_literals(plan: Dict[str, Any]) -> List[str]:
    out=[]
    seen=set()
    for atom in plan.get("atoms",[]):
        pred=str(atom.get("pred",""))
        pos=_LITERAL_POS.get(pred)
        args=atom.get("args",[])
        if pos is None or len(args)<=pos:
            continue
        value=args[pos]
        if isvar(value) or not isinstance(value,str):
            continue
        if value not in seen:
            seen.add(value);out.append(value)
    return out

def _exact_anchor_ids(store: Any, bridge: Any, plan: Dict[str, Any], max_anchors: int):
    literals=_history_literals(plan)
    if not literals:
        raise QueryUnknown("history_literal_required")
    limit=int(max_anchors)
    if limit<1:
        raise QueryUnknown("invalid_exact_anchor_bound")
    anchors=[]
    seen=set()
    hash_rows_read=0
    verified=0
    hashes=[]
    for literal in literals:
        h=hashlib.sha256(literal.encode("utf-8")).hexdigest()
        hashes.append(h)
        rows=bridge.index.execute(
            """SELECT memory_id,text_sha256
               FROM product_memory_history_exact
               WHERE text_sha256=?
               ORDER BY memory_id
               LIMIT ?""",(h,limit+1)
        ).fetchall()
        hash_rows_read += len(rows)
        if len(rows)>limit:
            raise QueryUnknown("exact_anchor_fanout_exceeded")
        for hit in rows:
            mid=int(hit["memory_id"])
            row=store.conn.execute(
                """SELECT m.memory_id,m.category,m.text,m.status,m.source_event,
                          e.kind AS event_kind,e.actor AS event_actor,e.content AS event_content
                   FROM memories m
                   LEFT JOIN events e ON e.event_id=m.source_event
                   WHERE m.memory_id=?""",(mid,)
            ).fetchone()
            if row is None:
                raise QueryUnknown("exact_anchor_missing_row")
            text=str(row["text"])
            if str(hit["text_sha256"])!=h:
                raise QueryUnknown("exact_anchor_hash_metadata_mismatch")
            if str(row["status"])!="superseded":
                raise QueryUnknown("exact_anchor_not_superseded")
            if row["event_actor"]!="user" or row["event_kind"] not in base.USER_MEMORY_SOURCE_KINDS:
                raise QueryUnknown("exact_anchor_inadmissible_source")
            if str(row["event_content"])!=text:
                raise QueryUnknown("exact_anchor_source_text_mismatch")
            if hashlib.sha256(text.encode("utf-8")).hexdigest()!=h:
                raise QueryUnknown("exact_anchor_raw_hash_mismatch")
            if text!=literal:
                raise QueryUnknown("exact_anchor_literal_mismatch")
            verified += 1
            if mid not in seen:
                seen.add(mid);anchors.append(mid)
            if len(anchors)>limit:
                raise QueryUnknown("exact_anchor_fanout_exceeded")
    if not anchors:
        raise QueryUnknown("exact_anchor_not_found")
    return anchors,{"literals":literals,"hashes":hashes,
                    "hash_rows_read":hash_rows_read,"verified_exact_anchors":verified}

def evaluate_exact_anchor_history(
    store: Any,
    bridge: Any,
    plan: Dict[str, Any],
    *,
    max_exact_anchors: int=DEFAULT_MAX_EXACT_ANCHORS,
    max_depth: int=DEFAULT_MAX_DEPTH,
) -> Dict[str, Any]:
    if not _needs_history(plan):
        return evaluate_status_partitioned_history(
            store,bridge,plan,max_anchors=max_exact_anchors,max_depth=max_depth)

    current=list(bridge.recall(str(plan.get("query_text","")),limit=int(plan.get("limit",7))))
    current_ids=[int(r["memory_id"]) for r in current if "memory_id" in r]
    anchor_ids,probe=_exact_anchor_ids(store,bridge,plan,max_exact_anchors)
    descendant_ids=[]
    seen_desc=set()
    for aid in anchor_ids:
        did=_active_descendant(store,aid,max_depth)
        if did is not None and did not in seen_desc:
            seen_desc.add(did);descendant_ids.append(did)

    candidate_ids=[]
    seen=set()
    for mid in current_ids+descendant_ids:
        if mid not in seen:
            seen.add(mid);candidate_ids.append(mid)
    if len(candidate_ids)>15:
        raise QueryUnknown("exact_anchor_candidate_budget_exceeded")

    res=evaluate(store,plan,mechanism="full_snapshot_join",candidate_ids=candidate_ids)
    unique=[]
    for row in res["rows"]:
        if row not in unique:
            unique.append(row)
    if len(unique)>1:
        raise QueryUnknown("ambiguous_exact_anchor_projection")
    res["rows"]=unique
    res["selection"]={
        "current_ids":current_ids,
        "history_anchor_ids":anchor_ids,
        "history_descendant_ids":descendant_ids,
        "candidate_ids":candidate_ids,
        "max_exact_anchors":int(max_exact_anchors),
        "max_depth":int(max_depth),
        **probe,
    }
    return res
