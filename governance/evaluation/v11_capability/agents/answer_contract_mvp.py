# -*- coding: utf-8 -*-
"""Research-only default-OFF answer-contract executor primitives.

This module is deliberately thin:
- it does not retrieve or admit any source;
- it does not modify persistent memory;
- it separates question planning from evidence consumption;
- it renders only validated structured answer items;
- it treats current-turn user facts as current input, not as claims that must
  already exist in historical memory.

No provider calls occur in this module. Runners supply the model transport.
"""
from __future__ import annotations

import json
import re

TASK_TYPES={"lookup","temporal","aggregation","document","current_request","mixed"}
VALUE_TYPES={"text","date","time","number","person","place","list","boolean","action"}
OPS={"lookup","join","select_version","temporal_select","date_diff",
     "compare","count","enumerate","compose","verify_presupposition"}

PLANNER_SYSTEM = """You create a compact answer contract from the USER QUESTION only.
Do not answer the question and do not invent historical facts.
Return strict JSON only.

Rules:
1. Split every explicitly requested output into atomic answer_requirements.
2. Preserve shared identity/event bindings when outputs must refer to the same event.
3. Create PRECONDITIONS for facts/state whose resolution can materially change the answer, even when they are not requested output fields. Examples: whether a referenced past event actually occurred; which event two fields must share; the relevant time scope; current location/health/dependent-care/commitment state for a personalized action request; or a source/version conflict that must be resolved.
4. For personalized current action/drafting requests using I/my, add at least one material_current_state precondition when prior personal state could reasonably make the requested action unsafe, impossible, contradictory, or materially different. Do NOT assume what that state is; only require it to be checked.
5. If the user asks for N items, set expected_cardinality=N.
6. Mark temporal/order/latest/earliest/count/enumeration operations explicitly.
7. Facts stated by the user in the current question are current_turn_facts. They are usable current input and must NOT be rejected merely because historical memory lacks them, unless the user explicitly asks to verify them.
8. A personalized current request using I/my can still have history_need="uncertain" when prior location, health, relationships, commitments, dependent-care, or current state may materially change the useful answer.
9. Mark presuppositions that historical evidence should verify when wording asks about a past event as if it occurred.
10. Do not narrow the requested identifier beyond the wording. For example, "which podcast episode" may be answered by a descriptive topic; do not require a formal title/episode number unless the question does.
11. question_span must be an exact substring copied from the user question.
12. Do not add outputs the user did not ask for.

Schema:
{
 "history_need":"yes|no|uncertain",
 "task_type":"lookup|temporal|aggregation|document|current_request|mixed",
 "current_turn_facts":[string],
 "answer_requirements":[{
   "id":"o1","question_span":string,"requirement":string,
   "value_type":"text|date|time|number|person|place|list|boolean|action",
   "expected_cardinality":integer|null,"shared_binding":string|null
 }],
 "preconditions":[{
   "id":"p1",
   "kind":"event_exists|event_binding|temporal_scope|material_current_state|source_version|exhaustive_scope",
   "description":string,
   "affects_output_ids":["o1"],
   "required":true
 }],
 "operations":[{"op":"lookup|join|select_version|temporal_select|date_diff|compare|count|enumerate|compose|verify_presupposition",
                "purpose":string}],
 "verify_presupposition":boolean,
 "exhaustive_scope":boolean
}"""

EXECUTOR_SYSTEM = """You execute an answer contract using only the current user question and AUTHORIZED EVIDENCE.
Return strict JSON only. Do not add a free-form final answer.

Critical rules:
1. Current-turn facts explicitly stated in the user question are current input. Do not reject them just because they are absent from historical evidence. Historical evidence may add constraints, corrections, or risks that materially affect the requested action.
1a. Resolve every REQUIRED PRECONDITION before committing to an affected output. A material_current_state precondition can override the naive requested action: if history shows a relevant health, location, dependent-care, commitment, or current-state constraint, the answer must surface it before or instead of blindly executing the requested action.
2. For historical lookup, every supported answer must cite one or more provided SOURCE ids.
3. Respect shared bindings: do not combine a date/person/time from different events when the contract says they share one event.
4. For temporal questions, distinguish event time, record time, plans, and actual events. Use source date/timestamp only when it is a valid anchor for the described event.
5. For enumeration/counts, satisfy expected_cardinality exactly when the evidence supports it. Do not merge two separately requested/listed items into one and compensate with an extra item.
6. For misleading/presupposed historical questions, correct the premise when evidence contradicts it.
7. For action/drafting requests, answer the current request, but surface material historical constraints found in evidence instead of pretending the current-turn facts are unsupported. If history shows a changed current state (for example relocation or a health limitation) that materially changes the request, state that constraint explicitly.
8. Match the semantic subset requested by the question. If a section mixes budgeting and sustainability, do not return the first N bullets; choose the bullets that actually satisfy the requested concept.
9. A descriptive identifier supported by evidence is enough when the question does not demand a formal title/number.
10. For temporal questions, if a dated source uniquely describes the target event and there is no evidence that the date is merely a later record/plan date, use that date as the event date rather than refusing solely because unrelated contextual dates are absent.
11. If evidence is genuinely insufficient, use status=unknown; never guess.
12. Keep answer_text direct and self-contained. The renderer will concatenate it without another model rewrite.

Schema:
{
 "answers":[{
   "id":"o1",
   "status":"supported|unknown|conflicted",
   "value":string|number|boolean|array|null,
   "evidence_ids":[string],
   "answer_text":string
 }],
 "material_constraints":[{
   "status":"supported|conflicted",
   "text":string,
   "evidence_ids":[string]
 }],
 "unresolved":[string]
}"""


def planner_messages(question:str):
    return [
      {"role":"system","content":PLANNER_SYSTEM},
      {"role":"user","content":"USER QUESTION:\n"+str(question)}
    ]


def validate_contract(question:str,obj:dict)->dict:
    if not isinstance(obj,dict):
        raise ValueError("contract_must_be_object")
    if obj.get("history_need") not in {"yes","no","uncertain"}:
        raise ValueError("history_need_invalid")
    if obj.get("task_type") not in TASK_TYPES:
        raise ValueError("task_type_invalid")
    reqs=obj.get("answer_requirements")
    if not isinstance(reqs,list) or not (1<=len(reqs)<=8):
        raise ValueError("answer_requirements_invalid")
    ids=set();q=str(question)
    for r in reqs:
        if not isinstance(r,dict):raise ValueError("requirement_invalid")
        rid=str(r.get("id") or "")
        if not re.fullmatch(r"o[1-8]",rid) or rid in ids:
            raise ValueError("requirement_id_invalid")
        ids.add(rid)
        span=str(r.get("question_span") or "")
        if not span or span.casefold() not in q.casefold():
            raise ValueError("question_span_not_from_question")
        if r.get("value_type") not in VALUE_TYPES:
            raise ValueError("value_type_invalid")
        n=r.get("expected_cardinality")
        if n is not None and (type(n) is not int or n<1 or n>20):
            raise ValueError("expected_cardinality_invalid")
        if not str(r.get("requirement") or "").strip():
            raise ValueError("requirement_text_missing")
    pre=obj.get("preconditions") or []
    if not isinstance(pre,list) or len(pre)>8:
        raise ValueError("preconditions_invalid")
    pre_ids=set()
    allowed_pre={"event_exists","event_binding","temporal_scope","material_current_state",
                 "source_version","exhaustive_scope"}
    clean_pre=[]
    for r in pre:
        if not isinstance(r,dict):raise ValueError("precondition_invalid")
        pid=str(r.get("id") or "")
        if not re.fullmatch(r"p[1-8]",pid) or pid in pre_ids:
            raise ValueError("precondition_id_invalid")
        pre_ids.add(pid)
        kind=r.get("kind")
        if kind not in allowed_pre:raise ValueError("precondition_kind_invalid")
        desc=str(r.get("description") or "").strip()
        if not desc:raise ValueError("precondition_description_missing")
        affects=[str(x) for x in (r.get("affects_output_ids") or [])]
        if not affects or any(x not in ids for x in affects):
            raise ValueError("precondition_affects_invalid")
        clean_pre.append({"id":pid,"kind":kind,"description":desc,
                          "affects_output_ids":affects,
                          "required":bool(r.get("required",True))})
    ops=obj.get("operations") or []
    if not isinstance(ops,list) or len(ops)>10:
        raise ValueError("operations_invalid")
    for op in ops:
        if not isinstance(op,dict) or op.get("op") not in OPS:
            raise ValueError("operation_invalid")
    facts=obj.get("current_turn_facts") or []
    if not isinstance(facts,list) or len(facts)>10:
        raise ValueError("current_turn_facts_invalid")
    out=dict(obj)
    out["answer_requirements"]=reqs
    out["preconditions"]=clean_pre
    out["operations"]=ops
    out["current_turn_facts"]=[str(x) for x in facts]
    out["verify_presupposition"]=bool(obj.get("verify_presupposition"))
    out["exhaustive_scope"]=bool(obj.get("exhaustive_scope"))
    return out


def executor_messages(question:str,evidence_text:str,contract:dict):
    return [
      {"role":"system","content":EXECUTOR_SYSTEM},
      {"role":"user","content":
        "USER QUESTION:\n"+str(question)+
        "\n\nANSWER CONTRACT:\n"+json.dumps(contract,ensure_ascii=False,indent=2)+
        "\n\nAUTHORIZED EVIDENCE:\n"+str(evidence_text)}
    ]


def validate_execution(contract:dict,obj:dict)->dict:
    if not isinstance(obj,dict):raise ValueError("execution_must_be_object")
    answers=obj.get("answers")
    if not isinstance(answers,list):raise ValueError("answers_must_be_list")
    req={r["id"]:r for r in contract["answer_requirements"]}
    got={}
    errors=[]
    for a in answers:
        if not isinstance(a,dict):continue
        rid=str(a.get("id") or "")
        if rid not in req or rid in got:
            errors.append("invalid_or_duplicate_output:"+rid);continue
        status=a.get("status")
        if status not in {"supported","unknown","conflicted"}:
            errors.append("invalid_status:"+rid);continue
        ev=a.get("evidence_ids") or []
        if not isinstance(ev,list):errors.append("evidence_ids_not_list:"+rid);continue
        text=str(a.get("answer_text") or "").strip()
        if not text:errors.append("answer_text_missing:"+rid)
        expected=req[rid].get("expected_cardinality")
        value=a.get("value")
        if expected is not None and status=="supported":
            if expected>1:
                if not isinstance(value,list) or len(value)!=expected:
                    errors.append("cardinality_mismatch:"+rid)
            elif expected==1 and isinstance(value,list) and len(value)!=1:
                errors.append("cardinality_mismatch:"+rid)
        got[rid]=dict(a,answer_text=text,evidence_ids=[str(x) for x in ev])
    missing=[rid for rid in req if rid not in got]
    errors.extend("missing_output:"+rid for rid in missing)
    constraints=obj.get("material_constraints") or []
    if not isinstance(constraints,list):
        errors.append("material_constraints_not_list");constraints=[]
    clean_constraints=[]
    for c in constraints[:8]:
        if not isinstance(c,dict):continue
        st=c.get("status")
        tx=str(c.get("text") or "").strip()
        ev=c.get("evidence_ids") or []
        if st not in {"supported","conflicted"} or not tx or not isinstance(ev,list):
            errors.append("invalid_material_constraint");continue
        clean_constraints.append({"status":st,"text":tx,"evidence_ids":[str(x) for x in ev]})
    return {"valid":not errors,"errors":errors,"answers":got,
            "material_constraints":clean_constraints,
            "unresolved":[str(x) for x in (obj.get("unresolved") or [])][:10]}


def repair_messages(question:str,evidence_text:str,contract:dict,execution:dict,errors:list[str]):
    """One bounded repair: preserve valid items, fix only structural obligations."""
    return [
      {"role":"system","content":EXECUTOR_SYSTEM+
       "\nThis is a STRUCTURAL REPAIR. Preserve already correct supported values. "
       "Fix only the listed contract/structure errors and return the full JSON object."},
      {"role":"user","content":
       "USER QUESTION:\n"+str(question)+
       "\n\nANSWER CONTRACT:\n"+json.dumps(contract,ensure_ascii=False,indent=2)+
       "\n\nAUTHORIZED EVIDENCE:\n"+str(evidence_text)+
       "\n\nPREVIOUS EXECUTION:\n"+json.dumps(execution,ensure_ascii=False,indent=2)+
       "\n\nSTRUCTURE ERRORS:\n"+json.dumps(errors,ensure_ascii=False)}
    ]


def render_execution(contract:dict,checked:dict)->str:
    """Deterministically render validated answer items; no free-form rewrite."""
    if not checked.get("valid"):
        raise ValueError("cannot_render_invalid_execution")
    parts=[]
    for r in contract["answer_requirements"]:
        a=checked["answers"][r["id"]]
        parts.append(a["answer_text"])
    for c in checked["material_constraints"]:
        if c["text"] not in parts:
            parts.append(c["text"])
    return "\n\n".join(x for x in parts if x).strip()
