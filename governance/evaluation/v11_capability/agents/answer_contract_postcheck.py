# -*- coding: utf-8 -*-
"""Deterministic regression guard for the default-OFF answer-contract executor.

This module has no model or retrieval calls. It only rejects candidate answers
that contradict already-established contract state. Rejection is fail-closed:
the product bridge falls back to the unchanged legacy product answer path.

Two deliberately narrow checks:
1. A supported historical answer cannot override baseline while a REQUIRED
   event/source binding remains unresolved.
2. A supported numeric answer cannot contradict an unambiguous scalar count
   already stated by the gap coverage for that exact output node.

Material-current-state preconditions are intentionally excluded from (1):
surfacing an unresolved health/location/commitment constraint can itself be the
useful behavior for current-action requests.
"""
from __future__ import annotations

import re

STRICT_BINDING_PRECONDITIONS={
    "event_exists","event_binding","source_version","exhaustive_scope"
}

_NUMERIC_PATTERNS=(
    r"(?i)\byields?\s+(?:a\s+)?total\s+of\s+(\d+)\b",
    r"(?i)\btotal\s+(?:count\s+)?(?:is|of)\s+(\d+)\b",
    r"(?i)\bcontains?\s+(\d+)\s+columns?\b",
    r"(?i)\bhas\s+(\d+)\s+columns?\b",
    r"(?i)\bthere\s+are\s+(\d+)\s+(?:entries|items|columns|rows)\b",
)


def supported_numeric_from_reason(reason:str):
    values=[]
    text=str(reason or "")
    for pattern in _NUMERIC_PATTERNS:
        values.extend(int(x) for x in re.findall(pattern,text))
    unique=set(values)
    return next(iter(unique)) if len(unique)==1 else None


def postcheck_execution(contract:dict,gap:dict,checked:dict)->list[str]:
    errors=[]
    coverage={
        str(x.get("node_id") or ""):x
        for x in (gap.get("coverage") or [])
        if isinstance(x,dict)
    }
    answers=checked.get("answers") or {}
    unresolved=[str(x) for x in (checked.get("unresolved") or []) if str(x).strip()]

    # Historical/event identity must be closed before a supported candidate can
    # replace the baseline answer. Current-state constraints are excluded.
    if unresolved:
        for pre in contract.get("preconditions") or []:
            if not isinstance(pre,dict) or not pre.get("required"):
                continue
            if pre.get("kind") not in STRICT_BINDING_PRECONDITIONS:
                continue
            pid=str(pre.get("id") or "")
            status=str((coverage.get(pid) or {}).get("status") or "")
            if status=="supported":
                continue
            affected={str(x) for x in (pre.get("affects_output_ids") or [])}
            if any(
                rid in affected and isinstance(ans,dict) and ans.get("status")=="supported"
                for rid,ans in answers.items()
            ):
                errors.append(
                    "unresolved_required_"+str(pre.get("kind"))+":"+pid+":"+status
                )

    # Only use a scalar if the coverage text itself gives one unambiguous count
    # for the exact output node. This is a conflict veto, never a source of a
    # new answer.
    reqs={str(x.get("id") or ""):x for x in (contract.get("answer_requirements") or [])
          if isinstance(x,dict)}
    for rid,req in reqs.items():
        if req.get("value_type")!="number":
            continue
        c=coverage.get(rid) or {}
        if c.get("status")!="supported":
            continue
        expected=supported_numeric_from_reason(c.get("reason"))
        if expected is None:
            continue
        ans=answers.get(rid)
        if not isinstance(ans,dict) or ans.get("status")!="supported":
            continue
        value=ans.get("value")
        if isinstance(value,bool) or not isinstance(value,(int,float)):
            continue
        if float(value)!=float(expected):
            errors.append(
                "numeric_coverage_conflict:"+rid+":"+str(value)+"!="+str(expected)
            )
    return errors
