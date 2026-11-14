# -*- coding: utf-8 -*-
"""Bounded contract-driven evidence completion over an existing authorized pool.

Ranking is delegated to the existing product/research ranker. This module:
- never reads gold/reference labels;
- never expands authority;
- keeps existing source IDs;
- derives at most two extra subqueries from the answer contract;
- adds at most three previously-unselected sources.
"""
from __future__ import annotations

def contract_queries(question,contract,max_queries=3):
    out=[str(question)]
    for r in contract.get("answer_requirements") or []:
        q=(str(r.get("question_span") or "")+" "+str(r.get("requirement") or "")).strip()
        if q and q.casefold() not in {x.casefold() for x in out}:
            out.append(q)
        if len(out)>=max_queries:break
    return out[:max_queries]

def supplement_sources(question,contract,docs,current_source_keys,ranker,max_extra=3,per_query=2):
    """Return current IDs + bounded extras selected by an existing ranker."""
    current=[str(x) for x in current_source_keys or []]
    selected=set(current);extras=[];trace=[]
    for query in contract_queries(question,contract):
        ranked,_report=ranker(query,docs)
        hits=[]
        for d in ranked:
            sid=str(d.get("id") or d.get("source_key") or "")
            if not sid or sid in selected:continue
            hits.append(sid)
            if len(hits)>=per_query:break
        trace.append({"query":query,"new_candidates":hits})
        for sid in hits:
            if sid in selected:continue
            selected.add(sid);extras.append(sid)
            if len(extras)>=max_extra:
                return {"source_keys":current+extras,"extra_source_keys":extras,
                        "queries":trace,"triggered":bool(extras)}
    return {"source_keys":current+extras,"extra_source_keys":extras,
            "queries":trace,"triggered":bool(extras)}


def supplement_gap_queries(gap_plan,docs,current_source_keys,ranker,max_extra=3,per_query=2):
    """Rank only analyzer-proposed unresolved-node queries; preserve current IDs."""
    current=[str(x) for x in current_source_keys or []]
    selected=set(current);extras=[];trace=[]
    if gap_plan.get("stop"):
        return {"source_keys":current,"extra_source_keys":[],"queries":[],
                "triggered":False,"reason":"GAP_ANALYZER_STOP"}
    for row in gap_plan.get("search_queries") or []:
        query=str(row.get("query") or "")
        ranked,_=ranker(query,docs)
        hits=[]
        for d in ranked:
            sid=str(d.get("id") or d.get("source_key") or "")
            if not sid or sid in selected:continue
            hits.append(sid)
            if len(hits)>=per_query:break
        trace.append({"query":query,"node_ids":row.get("node_ids") or row.get("output_ids") or [],
                      "new_candidates":hits})
        for sid in hits:
            if sid in selected:continue
            selected.add(sid);extras.append(sid)
            if len(extras)>=max_extra:
                return {"source_keys":current+extras,"extra_source_keys":extras,
                        "queries":trace,"triggered":True,"reason":"BOUNDED_EXTRA_REACHED"}
    return {"source_keys":current+extras,"extra_source_keys":extras,
            "queries":trace,"triggered":bool(extras),
            "reason":"GAP_QUERY_COMPLETED"}
