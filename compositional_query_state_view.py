# -*- coding: utf-8 -*-
"""MAIN28 read-only compositional query-state view.

Product-shaped adapter over canonical IdentityStore correction lineage.
No persistent state, no provider/model calls, no oracle evidence IDs.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from identity_core import USER_MEMORY_SOURCE_KINDS
from typed_history_view import (
    HistoryUnknown, fold_history, typed_as_of,
    _memory_row, _typed_lineage, _require_admissible_source,
)

SUPPORTED = {
    "current",
    "history_first",
    "history_previous",
    "history_change_count",
    "as_of",
    "supersedes",
    "node_text",
}

# Generic operator-dependency graph. These are view primitives, not query families.
OP_DEPS = {
    "current": {"active_row", "admissible_source"},
    "history_first": {"current", "history_chain", "admissible_source"},
    "history_previous": {"current", "history_chain", "admissible_source"},
    "history_change_count": {"current", "history_chain", "admissible_source"},
    "as_of": {"current", "history_chain", "admissible_source"},
    "supersedes": {"current", "typed_lineage", "admissible_source"},
    "node_text": {"typed_lineage", "historical_row", "admissible_source"},
    "active_row": set(),
    "history_chain": {"historical_row", "typed_lineage", "admissible_source"},
    "historical_row": set(),
    "typed_lineage": set(),
    "admissible_source": set(),
}

class QueryUnknown(RuntimeError):
    pass

def isvar(x: Any) -> bool:
    return isinstance(x, str) and x.startswith("?")

def atom(pred: str, *args: Any) -> Dict[str, Any]:
    pred = str(pred)
    if pred not in SUPPORTED:
        raise ValueError("unsupported_predicate")
    return {"pred": pred, "args": list(args)}

def fact(pred: str, *args: Any, source_role: str = "user", active: bool = True) -> Dict[str, Any]:
    return {"pred": str(pred), "args": list(args), "source_role": source_role, "active": bool(active)}

def backward_slice(predicates: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    stack = list(predicates)
    while stack:
        name = stack.pop()
        if name in out:
            continue
        if name not in OP_DEPS:
            raise QueryUnknown("missing_dependency_metadata")
        out.add(name)
        stack.extend(OP_DEPS[name])
    return out

def match_atom(facts: Sequence[Dict[str, Any]], a: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for f in facts:
        if not f.get("active", True) or f.get("source_role") != "user":
            continue
        if f["pred"] != a["pred"] or len(f["args"]) != len(a["args"]):
            continue
        b: Dict[str, Any] = {}
        ok = True
        for q, v in zip(a["args"], f["args"]):
            if isvar(q):
                if q in b and b[q] != v:
                    ok = False
                    break
                b[q] = v
            elif q != v:
                ok = False
                break
        if ok:
            rows.append(b)
    return rows

def compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return all(k not in a or a[k] == v for k, v in b.items())

def natural_join(facts: Sequence[Dict[str, Any]], query: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = [{}]
    for a in query:
        rhs = match_atom(facts, a)
        nxt: List[Dict[str, Any]] = []
        for left in rows:
            for right in rhs:
                if compatible(left, right):
                    z = dict(left)
                    z.update(right)
                    nxt.append(z)
        rows = nxt
        if not rows:
            break
    return rows

def project(rows: Sequence[Dict[str, Any]], outputs: Sequence[str], limit: int = 7) -> List[Dict[str, Any]]:
    uniq = {
        tuple((k, r.get(k)) for k in outputs)
        for r in rows
    }
    ordered = sorted(uniq, key=lambda t: tuple(str(v) for _, v in t))
    return [dict(x) for x in ordered[: max(1, min(20, int(limit)))]]

def _source_ok(store: Any, row: Any) -> bool:
    source_event = row["source_event"]
    if source_event is None:
        return False
    event = _typed_lineage(store.conn, int(source_event))
    if event is None:
        return False
    try:
        _require_admissible_source(event)
    except HistoryUnknown:
        return False
    return True

def _category_constraint(plan: Dict[str, Any]) -> Optional[str]:
    # Both full and sliced mechanisms receive the same typed prefilter.
    for a in plan["atoms"]:
        if a["pred"] == "current" and len(a["args"]) >= 3:
            category = a["args"][1]
            if not isvar(category):
                return str(category)
    return None

def _active_rows(store: Any, plan: Dict[str, Any], ids: Optional[Sequence[int]] = None):
    category = _category_constraint(plan)
    where = ["status='active'"]
    args: List[Any] = []
    if category is not None:
        where.append("category=?")
        args.append(category)
    if ids is not None:
        ids = [int(x) for x in ids]
        if not ids:
            return []
        where.append("memory_id IN (" + ",".join("?" for _ in ids) + ")")
        args.extend(ids)
    sql = (
        "SELECT memory_id,category,text,status,source_event,priority "
        "FROM memories WHERE " + " AND ".join(where) + " ORDER BY memory_id"
    )
    return list(store.conn.execute(sql, args))

def _immediate_predecessor(store: Any, row: Any):
    if not _source_ok(store, row):
        return None
    event = _typed_lineage(store.conn, int(row["source_event"]))
    if event is None or event["kind"] != "memory.corrected":
        return None
    sid = event["supersedes_memory_id"]
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        raise QueryUnknown("invalid_supersedes")
    pred = _memory_row(store.conn, sid)
    if pred is None or pred["status"] != "superseded":
        raise QueryUnknown("invalid_predecessor")
    if not _source_ok(store, pred):
        raise QueryUnknown("inadmissible_predecessor")
    return pred

def _needed_asof_steps(plan: Dict[str, Any]) -> Set[int]:
    out: Set[int] = set()
    for a in plan["atoms"]:
        if a["pred"] == "as_of" and len(a["args"]) >= 3:
            step = a["args"][1]
            if isvar(step):
                raise QueryUnknown("variable_asof_step_forbidden")
            step = int(step)
            if step < 0 or step > 8:
                raise QueryUnknown("asof_step_out_of_bounds")
            out.add(step)
    return out

def materialize(
    store: Any,
    plan: Dict[str, Any],
    *,
    sliced: bool,
    ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    query_preds = {a["pred"] for a in plan["atoms"]}
    closure = backward_slice(query_preds)
    if sliced:
        emit = set(query_preds)
    else:
        emit = set(SUPPORTED)

    rows = _active_rows(store, plan, ids)
    facts: List[Dict[str, Any]] = []
    work = {"active_rows": len(rows), "history_folds": 0, "asof_calls": 0, "relation_reads": 0}
    cross_failures: List[str] = []
    asof_steps = _needed_asof_steps(plan) if "as_of" in emit else set()
    if not sliced:
        asof_steps |= {0, 1, 2}

    for row in rows:
        if not _source_ok(store, row):
            continue
        mid = int(row["memory_id"])
        current_text = str(row["text"])
        if "current" in emit:
            facts.append(fact("current", mid, str(row["category"]), current_text))

        need_hist = bool(emit & {"history_first", "history_previous", "history_change_count"}) or bool(asof_steps)
        hist = None
        if need_hist or (sliced and closure & {"history_chain"}):
            try:
                hist = fold_history(store, mid)
                work["history_folds"] += 1
            except HistoryUnknown:
                hist = None
        if hist is not None:
            if "history_first" in emit:
                facts.append(fact("history_first", mid, hist.first))
            if "history_previous" in emit and hist.previous is not None:
                facts.append(fact("history_previous", mid, hist.previous))
            if "history_change_count" in emit:
                facts.append(fact("history_change_count", mid, hist.change_count))
            if sliced and hist.last != current_text:
                cross_failures.append(f"CURRENT_NE_LAST:{mid}")

        for step in sorted(asof_steps):
            try:
                val, _, _checks = typed_as_of(store, mid, step)
                work["asof_calls"] += 1
                if "as_of" in emit:
                    facts.append(fact("as_of", mid, step, val))
                if sliced and step == 0 and val != current_text:
                    cross_failures.append(f"ASOF0_NE_CURRENT:{mid}")
            except HistoryUnknown:
                pass

        if emit & {"supersedes", "node_text"} or (sliced and closure & {"typed_lineage"}):
            pred = _immediate_predecessor(store, row)
            work["relation_reads"] += 1
            if pred is not None:
                pid = int(pred["memory_id"])
                ptext = str(pred["text"])
                if "supersedes" in emit:
                    facts.append(fact("supersedes", mid, pid))
                if "node_text" in emit:
                    facts.append(fact("node_text", pid, ptext))
                if sliced and hist is not None and hist.previous is not None and hist.previous != ptext:
                    cross_failures.append(f"PREVIOUS_NE_PREDECESSOR:{mid}")

    return {
        "facts": facts,
        "work": work,
        "slice": sorted(closure),
        "cross_failures": cross_failures,
    }

def evaluate(
    store: Any,
    plan: Dict[str, Any],
    *,
    mechanism: str,
    candidate_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    if mechanism not in {"full_snapshot_join", "sliced_snapshot_join"}:
        raise ValueError("unknown_mechanism")
    if store.conn.in_transaction:
        raise QueryUnknown("caller_transaction_not_supported")
    store.conn.execute("BEGIN")
    try:
        mat = materialize(
            store, plan,
            sliced=(mechanism == "sliced_snapshot_join"),
            ids=candidate_ids,
        )
        if mechanism == "sliced_snapshot_join" and mat["cross_failures"]:
            return {
                "status": "UNKNOWN",
                "rows": [],
                "work": mat["work"],
                "slice": mat["slice"],
                "cross_failures": mat["cross_failures"],
            }
        joined = natural_join(mat["facts"], plan["atoms"])
        rows = project(joined, plan["outputs"], plan.get("limit", 7))
        return {
            "status": "OK",
            "rows": rows,
            "work": mat["work"],
            "slice": mat["slice"],
            "cross_failures": mat["cross_failures"],
        }
    finally:
        store.conn.rollback()
