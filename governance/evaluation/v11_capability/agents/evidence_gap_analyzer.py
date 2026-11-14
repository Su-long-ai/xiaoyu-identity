# -*- coding: utf-8 -*-
"""Question-contract evidence gap analysis for one bounded supplemental retrieval.

The analyzer sees only:
- user question,
- answer contract,
- already authorized/model-visible evidence.

It never sees gold/reference answers. Search queries must target unresolved
contract nodes and use entities/events/topics already present in question or
visible evidence; they must not contain a guessed answer.
"""
from __future__ import annotations
import json

GAP_SYSTEM="""Analyze whether the CURRENT AUTHORIZED EVIDENCE is sufficient to execute the ANSWER CONTRACT.
Return strict JSON only. Do not answer the user's question.

Rules:
1. For every answer requirement AND every required precondition, classify status as supported, missing, unbound, conflicted, or scope_open.
2. supported means the visible evidence contains the facts and bindings needed to answer, not merely related words.
2a. A material_current_state precondition is supported only when the visible evidence is sufficient to determine whether a relevant current personal constraint exists. The fact that the user supplied enough words to draft/act is NOT evidence that personal constraints are absent.
3. If any required output/precondition is unresolved, propose at most 3 targeted memory-search queries.
4. Search queries may use only entities, events, relationships, dates/time anchors, document names, and topic words explicitly present in the user question or CURRENT AUTHORIZED EVIDENCE. Never put a guessed answer into a search query.
5. Build queries from unresolved requirements plus confirmed anchors. Prefer a specific event/person/document relation over broad restatements of the whole question.
6. For 'all', 'count', 'earliest/latest', or 'never' questions, mark scope_open unless the visible evidence supports checking the relevant scope.
7. If all requirements are supported and no material conflict/scope issue remains, stop=true and return no search queries.

Schema:
{
 "coverage":[{"node_id":"o1|p1","status":"supported|missing|unbound|conflicted|scope_open","reason":string}],
 "search_queries":[{"node_ids":["o1","p1"],"query":string,"anchor_reason":string}],
 "stop":boolean
}"""

def gap_messages(question,contract,current_evidence):
    return [
      {"role":"system","content":GAP_SYSTEM},
      {"role":"user","content":
       "USER QUESTION:\n"+str(question)+
       "\n\nANSWER CONTRACT:\n"+json.dumps(contract,ensure_ascii=False,indent=2)+
       "\n\nCURRENT AUTHORIZED EVIDENCE:\n"+str(current_evidence)}
    ]

def _contract_nodes(contract,required_only=False):
    outputs=[str(r["id"]) for r in contract.get("answer_requirements") or []]
    pres=[r for r in contract.get("preconditions") or []]
    if required_only:
        return set(outputs+[str(r["id"]) for r in pres if r.get("required",True)])
    return set(outputs+[str(r["id"]) for r in pres])

def validate_gap_plan(contract,obj):
    if not isinstance(obj,dict):raise ValueError("gap_plan_must_be_object")
    allowed=_contract_nodes(contract,required_only=False)
    req=_contract_nodes(contract,required_only=True)
    cov=obj.get("coverage")
    if not isinstance(cov,list):raise ValueError("coverage_must_be_list")
    seen=set();clean=[]
    for row in cov:
        if not isinstance(row,dict):raise ValueError("coverage_row_invalid")
        oid=str(row.get("node_id") or row.get("output_id") or "")
        if oid not in allowed or oid in seen:raise ValueError("coverage_node_invalid")
        st=row.get("status")
        if st not in {"supported","missing","unbound","conflicted","scope_open"}:
            raise ValueError("coverage_status_invalid")
        seen.add(oid);clean.append({"node_id":oid,"status":st,
          "reason":str(row.get("reason") or "")[:500]})
    if not req<=seen:raise ValueError("coverage_missing_nodes")
    queries=obj.get("search_queries") or []
    if not isinstance(queries,list) or len(queries)>3:raise ValueError("search_queries_invalid")
    cq=[]
    for q in queries:
        if not isinstance(q,dict):raise ValueError("search_query_invalid")
        ids=[str(x) for x in (q.get("node_ids") or q.get("output_ids") or [])]
        if not ids or any(x not in allowed for x in ids):raise ValueError("search_query_node_invalid")
        text=str(q.get("query") or "").strip()
        if not text or len(text)>220:raise ValueError("search_query_text_invalid")
        cq.append({"node_ids":ids,"query":text,
                   "anchor_reason":str(q.get("anchor_reason") or "")[:500]})
    stop=bool(obj.get("stop"))
    required_rows=[x for x in clean if x["node_id"] in req]
    if stop and cq:raise ValueError("stop_with_search_queries")
    if stop and any(x["status"]!="supported" for x in required_rows):
        raise ValueError("stop_with_unresolved_required_node")
    if not stop and all(x["status"]=="supported" for x in required_rows) and not cq:
        raise ValueError("nonstop_without_gap_or_query")
    return {"coverage":clean,"search_queries":cq,"stop":stop}


def repair_gap_plan(question,contract,obj):
    """Deterministically make a partial gap plan conservative and complete.

    Missing required nodes are never treated as supported. They become
    missing, and if capacity permits receive one query derived only from the
    question-only contract node text. No gold, guessed answer, or hidden
    evidence is introduced.
    """
    if not isinstance(obj,dict):
        obj={}
    required=_contract_nodes(contract,required_only=True)
    allowed=_contract_nodes(contract,required_only=False)
    cov=[]
    seen=set()
    allowed={"supported","missing","unbound","conflicted","scope_open"}
    for row in obj.get("coverage") or []:
        if not isinstance(row,dict):continue
        nid=str(row.get("node_id") or row.get("output_id") or "")
        if nid not in allowed or nid in seen:continue
        st=row.get("status")
        if st not in allowed:st="missing"
        cov.append({"node_id":nid,"status":st,
                    "reason":str(row.get("reason") or "")[:500]})
        seen.add(nid)

    outputs={str(x["id"]):x for x in contract.get("answer_requirements") or []}
    pres={str(x["id"]):x for x in contract.get("preconditions") or []
          if x.get("required",True)}
    missing=sorted(required-seen)
    for nid in missing:
        cov.append({"node_id":nid,"status":"missing",
                    "reason":"Required contract node omitted by analyzer; conservatively unresolved."})

    queries=[]
    for q in obj.get("search_queries") or []:
        if not isinstance(q,dict):continue
        ids=[str(x) for x in (q.get("node_ids") or q.get("output_ids") or [])]
        ids=[x for x in ids if x in allowed]
        text=str(q.get("query") or "").strip()
        if ids and text and len(text)<=220 and len(queries)<3:
            queries.append({"node_ids":ids,"query":text,
                            "anchor_reason":str(q.get("anchor_reason") or "")[:500]})

    queried={nid for q in queries for nid in q["node_ids"]}
    for nid in missing:
        if len(queries)>=3 or nid in queried:break
        if nid in pres:
            text=str(pres[nid].get("description") or "").strip()
        else:
            r=outputs[nid]
            text=(str(r.get("question_span") or "")+" "+
                  str(r.get("requirement") or "")).strip()
        if text:
            queries.append({"node_ids":[nid],"query":text[:220],
                            "anchor_reason":"Deterministic query from omitted required contract node."})

    stop=bool(obj.get("stop")) and not missing and all(x["status"]=="supported" for x in cov if x["node_id"] in required)
    return {"coverage":cov,"search_queries":queries,"stop":stop,
            "_deterministic_repair":{"missing_nodes":missing,
                                     "repaired":bool(missing)}}
