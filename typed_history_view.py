# -*- coding: utf-8 -*-
"""Read-only typed correction-history view for MAIN26 Stage A.

Consumes only canonical memory rows and a typed lineage projection from
the correction event. It does not load raw historical payloads and creates no
persistent state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from identity_core import USER_MEMORY_SOURCE_KINDS


class HistoryUnknown(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class HistoryFold:
    first: str
    last: str
    previous: Optional[str]
    change_count: int
    node_count: int
    work_checks: int


def _memory_row(conn, memory_id: int):
    return conn.execute(
        "SELECT memory_id,category,text,status,source_event "
        "FROM memories WHERE memory_id=?",
        (int(memory_id),),
    ).fetchone()


def _typed_lineage(conn, event_id: int):
    return conn.execute(
        "SELECT kind,actor,json_extract(extra,'$.supersedes_memory_id') AS supersedes_memory_id "
        "FROM events WHERE event_id=?",
        (int(event_id),),
    ).fetchone()


def _require_admissible_source(event) -> None:
    if event["actor"] != "user" or event["kind"] not in USER_MEMORY_SOURCE_KINDS:
        raise HistoryUnknown("inadmissible_source")


def fold_history(store: Any, current_memory_id: int) -> HistoryFold:
    conn = store.conn
    work = 0
    row = _memory_row(conn, current_memory_id)
    work += 1
    if row is None:
        raise HistoryUnknown("missing_current_memory")
    if row["status"] != "active":
        raise HistoryUnknown("current_not_active")

    seen = set()
    newest_to_oldest: List[str] = []
    category = row["category"]

    while True:
        memory_id = int(row["memory_id"])
        if memory_id in seen:
            raise HistoryUnknown("cycle")
        seen.add(memory_id)

        if row["category"] != category:
            raise HistoryUnknown("category_mismatch")

        source_event = row["source_event"]
        if source_event is None:
            raise HistoryUnknown("missing_source_event")
        event = _typed_lineage(conn, int(source_event))
        work += 1
        if event is None:
            raise HistoryUnknown("missing_source_event")
        _require_admissible_source(event)
        newest_to_oldest.append(str(row["text"]))

        supersedes = event["supersedes_memory_id"]
        if event["kind"] == "memory.corrected":
            if supersedes is None:
                raise HistoryUnknown("missing_supersedes")
            try:
                predecessor_id = int(supersedes)
            except (TypeError, ValueError):
                raise HistoryUnknown("invalid_supersedes")
            if predecessor_id <= 0:
                raise HistoryUnknown("invalid_supersedes")
            if predecessor_id in seen:
                raise HistoryUnknown("cycle")
            predecessor = _memory_row(conn, predecessor_id)
            work += 1
            if predecessor is None:
                raise HistoryUnknown("missing_memory_row")
            if predecessor["status"] != "superseded":
                raise HistoryUnknown("predecessor_not_superseded")
            row = predecessor
            continue

        if supersedes is not None:
            raise HistoryUnknown("unexpected_supersedes")
        break

    values = list(reversed(newest_to_oldest))
    change_count = sum(a != b for a, b in zip(values, values[1:]))
    return HistoryFold(
        first=values[0],
        last=values[-1],
        previous=values[-2] if len(values) >= 2 else None,
        change_count=change_count,
        node_count=len(values),
        work_checks=work,
    )


def query_history(store: Any, current_memory_id: int, operator: str):
    view = fold_history(store, current_memory_id)
    op = str(operator).upper()
    if op == "FIRST":
        return view.first
    if op == "LAST":
        return view.last
    if op == "PREVIOUS":
        return view.previous
    if op == "CHANGE_COUNT":
        return view.change_count
    raise ValueError("unsupported_history_operator")


def typed_as_of(store: Any, current_memory_id: int, steps_back: int):
    """Matched baseline primitive: reconstruct one typed as-of point from anchor."""
    if int(steps_back) < 0:
        raise ValueError("steps_back must be >= 0")
    conn = store.conn
    row = _memory_row(conn, current_memory_id)
    checks = 1
    if row is None:
        raise HistoryUnknown("missing_current_memory")
    if row["status"] != "active":
        raise HistoryUnknown("current_not_active")
    category = row["category"]
    seen = set()

    for step in range(int(steps_back) + 1):
        memory_id = int(row["memory_id"])
        if memory_id in seen:
            raise HistoryUnknown("cycle")
        seen.add(memory_id)
        if row["category"] != category:
            raise HistoryUnknown("category_mismatch")

        source_event = row["source_event"]
        if source_event is None:
            raise HistoryUnknown("missing_source_event")
        event = _typed_lineage(conn, int(source_event))
        checks += 1
        if event is None:
            raise HistoryUnknown("missing_source_event")
        _require_admissible_source(event)
        supersedes = event["supersedes_memory_id"]

        if step == int(steps_back):
            is_root = event["kind"] != "memory.corrected"
            if is_root and supersedes is not None:
                raise HistoryUnknown("unexpected_supersedes")
            if not is_root and supersedes is None:
                raise HistoryUnknown("missing_supersedes")
            return str(row["text"]), is_root, checks

        if event["kind"] != "memory.corrected" or supersedes is None:
            raise HistoryUnknown("history_shorter_than_requested")
        try:
            predecessor_id = int(supersedes)
        except (TypeError, ValueError):
            raise HistoryUnknown("invalid_supersedes")
        if predecessor_id <= 0 or predecessor_id in seen:
            raise HistoryUnknown("cycle")
        predecessor = _memory_row(conn, predecessor_id)
        checks += 1
        if predecessor is None:
            raise HistoryUnknown("missing_memory_row")
        if predecessor["status"] != "superseded":
            raise HistoryUnknown("predecessor_not_superseded")
        row = predecessor

    raise AssertionError("unreachable")


def repeated_typed_asof_baseline(store: Any, current_memory_id: int) -> HistoryFold:
    """Matched repeated typed-as-of baseline over the same canonical rows/lineage."""
    newest_to_oldest: List[str] = []
    work = 0
    steps = 0
    while True:
        value, is_root, checks = typed_as_of(store, current_memory_id, steps)
        work += checks
        newest_to_oldest.append(value)
        if is_root:
            break
        steps += 1

    values = list(reversed(newest_to_oldest))
    return HistoryFold(
        first=values[0],
        last=values[-1],
        previous=values[-2] if len(values) >= 2 else None,
        change_count=sum(a != b for a, b in zip(values, values[1:])),
        node_count=len(values),
        work_checks=work,
    )
