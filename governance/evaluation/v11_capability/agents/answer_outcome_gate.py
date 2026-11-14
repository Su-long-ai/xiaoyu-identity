# -*- coding: utf-8 -*-
"""Outcome-evidence checks shared by product promotion and exposed-dev audits.

This is a conservative quality veto, not a semantic grader. It never promotes
retrieval-only scores, never repairs old prediction seals, and never opens gold
to a candidate answerer. Positive answer quality still needs paired judging.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

VALID_SOURCE_ROLES = {"disjoint_validation", "independent_test"}
VALID_FINISH = {"stop", "end_turn", "eos", "completed"}
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12,
}

DELIVERY_FAILURE_STAGES = {
    "retrieval_miss", "evidence_incomplete", "source_conflict",
    "temporal_reasoning", "general_reasoning", "answer_incomplete", "unknown",
}
TRACE_BASES = {"human_verified", "independent_adjudication", "deterministic"}


def classify_delivery_trace(trace):
    """Locate the earliest H->R->P->W->A answer-delivery breakpoint.

    H: authorized history contains sufficient evidence.
    R: retrieval actually returned sufficient raw evidence.
    P: the final answer model actually received sufficient, untruncated evidence.
    W: execution/reasoning state (conflict, temporal/general reasoning).
    A: final visible answer completeness.

    This is a diagnostic classifier, not a correctness grader. A model's own
    self-assessment is never treated as verified trace provenance.
    """
    if not isinstance(trace, dict):
        return {"stage": "unknown", "verified": False,
                "reason": "delivery_trace_missing"}

    basis = str(trace.get("basis") or "").strip().casefold()
    verified = basis in TRACE_BASES
    h = trace.get("history_sufficient")
    r = trace.get("retrieval_sufficient")
    p = trace.get("prompt_sufficient")

    # If H is false, the item may be unanswerable or the reference may be
    # wrong. Do not launder that into a retrieval/model failure.
    if h is False:
        return {"stage": "unknown", "verified": verified,
                "reason": "authorized_history_not_sufficient"}
    if h is True and r is False:
        return {"stage": "retrieval_miss", "verified": verified,
                "reason": "history_sufficient_but_retrieval_incomplete"}
    if r is True and p is False:
        return {"stage": "evidence_incomplete", "verified": verified,
                "reason": "retrieval_sufficient_but_prompt_lost_evidence"}

    if p is True:
        if (trace.get("source_conflict_present") is True and
                trace.get("source_conflict_resolved") is False):
            return {"stage": "source_conflict", "verified": verified,
                    "reason": "delivered_conflict_not_resolved"}
        if (trace.get("temporal_required") is True and
                trace.get("temporal_reasoning_correct") is False):
            return {"stage": "temporal_reasoning", "verified": verified,
                    "reason": "sufficient_prompt_but_temporal_reasoning_wrong"}
        if trace.get("general_reasoning_correct") is False:
            return {"stage": "general_reasoning", "verified": verified,
                    "reason": "sufficient_prompt_but_reasoning_wrong"}
        if trace.get("required_output_complete") is False:
            return {"stage": "answer_incomplete", "verified": verified,
                    "reason": "supported_required_output_missing"}

    return {"stage": "unknown", "verified": verified,
            "reason": "no_verified_breakpoint_identified"}


def evidence_eligibility(provenance):
    """Whether a paired benefit is eligible for PRODUCT pilot review.

    Missing information is not a claim of failure: the benefit remains in
    isolated trial; only the claim of fresh product validation is withheld.
    """
    if not isinstance(provenance, dict):
        return {"pilot_eligible": False, "reasons": ["evaluation_provenance_missing"]}
    reasons = []
    role = provenance.get("source_role")
    if role not in VALID_SOURCE_ROLES:
        reasons.append("development_or_unknown_source_cannot_confirm_generalization")
    for key in ("predictions_sealed_before_gold", "same_frozen_product_sha",
                "all_counted_answers_integrity_checked",
                "suite_frozen_before_candidate_run",
                "suite_disjoint_from_candidate_tuning"):
        if provenance.get(key) is not True:
            reasons.append(key + "_not_proven")
    for key in ("gold_seen_during_candidate_selection", "cases_reused_for_candidate_tuning",
                "contains_invalid_answer_counted_correct"):
        if provenance.get(key) is not False:
            reasons.append(key + "_not_ruled_out")
    return {"pilot_eligible": not reasons, "source_role": role, "reasons": reasons}


def inspect_answer(answer, finish_reason=None):
    """Deterministic veto for *visible* corruption, never a proof of correctness.

    finish_reason is REQUIRED for a fully verified new output. Missing legacy
    metadata is classified unverified, not confidently 'truncated'.
    """
    text = str(answer or "").strip()
    errors = []
    warnings = []
    if not text:
        errors.append("empty_answer")
    if finish_reason is None:
        warnings.append("missing_finish_reason")
    elif str(finish_reason).strip().lower() not in VALID_FINISH:
        errors.append("nonterminal_finish_reason")
    if text:
        if text.endswith((",", ":", ";", "(", "[", "{", "—", "\\")):
            errors.append("dangling_terminal_punctuation")
        if text.startswith("{") or text.startswith("["):
            try:
                json.loads(text)
            except json.JSONDecodeError:
                errors.append("malformed_structured_output")
        if text.count("&#34;") % 2 or text.count("\"") % 2:
            # Only a hard veto when the *final* raw characters leave a quoted
            # fragment unfinished. Valid prose can contain lone quote marks.
            if re.search(r'(?s)"[^"]{0,180}$', text):
                errors.append("unclosed_final_quote")
        if text.count("```") % 2:
            errors.append("unclosed_code_fence")
        if text.count("`") % 2 and not text.count("```"):
            errors.append("unclosed_inline_code")
        if text.count("**") % 2 and re.search(r'\*\*[^*]{0,180}$', text):
            errors.append("unclosed_final_bold")
    return {"status": "invalid" if errors else ("unverified" if warnings else "valid"),
            "errors": list(dict.fromkeys(errors)), "warnings": warnings}


def _quantity(text):
    """Read an explicitly stated count near the start, without inferring it."""
    text = re.sub(r"[*_`#]", "", str(text or "")).strip()
    pattern = r"(?i)\b(" + "|".join(NUMBER_WORDS) + r"|\d{1,3})\b"
    m = re.search(pattern, text[:140])
    if not m:
        return None
    val = m.group(1).lower()
    return NUMBER_WORDS[val] if val in NUMBER_WORDS else int(val)



_TIME_RE = re.compile(
    r"(?i)\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b|"
    r"\b\d{1,2}:\d{2}\b|(?:上午|下午|晚上)\s*\d{1,2}[点时]")
_DATE_RE = re.compile(
    r"(?i)\b\d{4}-\d{1,2}-\d{1,2}\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b|"
    r"\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日")


def requested_field_guidance(question):
    """High-precision requested-fields contract, not benchmark answer leakage.

    No inference about missing facts is made here: the instruction only asks
    the model to include fields explicitly requested by the user.
    """
    q=str(question or "").casefold()
    date_time=(bool(re.search(r"\b(?:date|day)\s*(?:and|&|/)\s*"
        r"(?:time|hours?)\b",q)) or
        bool(re.search(r"(?:日期|哪天).{0,6}(?:时间|几点|时段)",q)))
    if date_time:
        return {"activated":True,"fields":["date","time"],
                "instruction":"Answer BOTH the date and the time requested. "
                "If the evidence specifies a start and end time, give BOTH. "
                "If a field is not available, say which field is unknown. "
                "Do not invent missing times."}
    return {"activated":False,"fields":[],"instruction":""}



def requested_fields_no_gold(question, answer):
    """A structure-only output check safe to run before any grading gold.

    An explicitly unprovided field is allowed: asking for an unknown time
    must not pressure the model into fabricating it. This check never calls
    models, expands source access, or determines semantic correctness.
    """
    guide=requested_field_guidance(question)
    if not guide["activated"]:
        return {"checked":False,"missing":[]}
    text=str(answer or "")
    def absent(label):
        if label=="time":
            return bool(re.search(r"(?i)(?:time|hours?)\s*(?:is|was|:)?\s*"
              r"(?:unknown|unavailable|not\s+(?:given|provided|specified|recorded|known))|"
              r"(?:unknown|unavailable|unspecified)\s+(?:time|hours?)|"
              r"(?:时间|时段|几点)\s*(?:未知|不详|未(?:提供|记录|说明|提及))",
              text))
        return bool(re.search(r"(?i)(?:date|day)\s*(?:is|was|:)?\s*"
              r"(?:unknown|unavailable|not\s+(?:given|provided|specified|recorded|known))|"
              r"(?:unknown|unavailable|unspecified)\s+(?:date|day)|"
              r"(?:日期|哪天)\s*(?:未知|不详|未(?:提供|记录|说明|提及))",
              text))
    missing=[]
    if not _DATE_RE.search(text) and not absent("date"):
        missing.append("date")
    if not _TIME_RE.search(text) and not absent("time"):
        missing.append("time")
    return {"checked":True,"missing":missing,"complete":not missing}

def missing_requested_fields(question, reference, answer):
    """Post-grading veto only when reference explicitly proves requested fields.

    A bare date in a date-and-time question is not complete just because the
    model finishes normally or a semantic judge favors it.
    """
    guide=requested_field_guidance(question)
    if not guide["activated"]:
        return {"checked":False,"missing":[]}
    ref=str(reference or "")
    ans=str(answer or "")
    required=[]
    if _DATE_RE.search(ref):required.append("date")
    if _TIME_RE.search(ref):required.append("time")
    missing=[field for field in required if not
             (_DATE_RE.search(ans) if field=="date" else _TIME_RE.search(ans))]
    # A date-plus-time question that requires a concrete start/end range
    # cannot pass with only the start or only the end. Count endpoints,
    # not a particular spelling (e.g. 10 AM versus 10:00 AM).
    ref_times={m.group(0).casefold().replace(" ","") for m in _TIME_RE.finditer(ref)}
    ans_times={m.group(0).casefold().replace(" ","") for m in _TIME_RE.finditer(ans)}
    if "time" in required and len(ref_times)>=2 and len(ans_times)<2:
        missing.append("time_range_endpoint")
    return {"checked":bool(required),"missing":missing,
            "complete":not missing,"required_from_reference":required,
            "reference_time_endpoints":len(ref_times),
            "answer_time_endpoints":len(ans_times)}

def count_contradiction(question, reference, answer):
    """High-precision conflict check for explicit counting questions only.

    The reference is used only in a POST-GRADING auditor, never in retrieval
    or generation. An uncertain parse is flagged, not silently asserted.
    """
    q = str(question or "").lower()
    if not (re.search(r"\bhow many\b|\bnumber of\b|\bcount of\b", q)):
        return {"checked": False, "contradiction": False}
    expected = _quantity(reference)
    asserted = _quantity(answer)
    # 'Based on SOURCE 2024...' is not an asserted count. Such long replies
    # must be adjudicated by a semantic checker instead of a fragile regex.
    if re.match(r"(?i)\s*(based on|according to|source |from )", str(answer or "")):
        asserted = None
    return {"checked": expected is not None and asserted is not None,
            "contradiction": expected is not None and asserted is not None
                             and expected != asserted,
            "expected": expected, "asserted": asserted}


def audit_graded_answers(verdict, answer_rows, reference_rows):
    """Audit historical, already exposed DEV scores without changing seals."""
    answers = {r["case_id"]: r for r in answer_rows}
    references = {r["case_id"]: r for r in reference_rows}
    out = []
    for row in verdict["rows"]:
        cid = row["case_id"]
        answer = answers[cid]
        ref = references[cid]
        check = inspect_answer(answer.get("answer"), answer.get("finish_reason"))
        count = count_contradiction(ref["question"], ref["gold_answer"], answer.get("answer"))
        fields = missing_requested_fields(ref["question"], ref["gold_answer"],
                                          answer.get("answer"))
        invalid = (check["status"] == "invalid" or count["contradiction"]
                   or bool(fields["missing"]))
        out.append({"case_id": cid, "reported_candidate_correct": row["new_correct"],
                    "reported_baseline_correct": row["old_correct"],
                    "answer_integrity": check, "count_check": count,
                    "field_completeness_check": fields,
                    "candidate_correct_after_deterministic_veto": bool(row["new_correct"]) and not invalid,
                    "overturned_reported_positive": bool(row["new_correct"]) and invalid})
    original = sum(bool(x["new_correct"]) for x in verdict["rows"])
    adjusted = sum(x["candidate_correct_after_deterministic_veto"] for x in out)
    return {"schema": "xiaoyu-postgrade-answer-integrity-audit-v1",
            "status": "EXPOSED_DEV_DIAGNOSTIC_NOT_FRESH_OR_RELEASE",
            "n": len(out), "reported_candidate_correct": original,
            "candidate_correct_after_veto": adjusted,
            "overturned_wrong_positive_ids":
                [x["case_id"] for x in out if x["overturned_reported_positive"]],
            "answers_missing_finish_reason":
                [x["case_id"] for x in out
                 if "missing_finish_reason" in x["answer_integrity"]["warnings"]],
            "not_independent_audit": True,
            "rows": out}


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text("utf-8").splitlines() if x.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verdict", required=True, type=Path)
    p.add_argument("--answers", required=True, type=Path)
    p.add_argument("--references", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    verdict = json.loads(args.verdict.read_text("utf-8"))
    answers = read_jsonl(args.answers)
    source = json.loads(args.references.read_text("utf-8"))
    report = audit_graded_answers(verdict, answers, source["rows"])
    report["source_sha256"] = {k: hashlib.sha256(v.read_bytes()).hexdigest()
                               for k, v in (("verdict", args.verdict),
                                            ("answers", args.answers),
                                            ("references", args.references))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
