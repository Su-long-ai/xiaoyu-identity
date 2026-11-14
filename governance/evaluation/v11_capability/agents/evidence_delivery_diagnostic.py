# -*- coding: utf-8 -*-
"""Zero-cost helpers for H->R->P->W->A evidence-delivery diagnostics.

The module does not call any model. It makes a future paired run auditable:
- manual complete raw evidence can replace the normal evidence section;
- exact model input is serialized and hashed before the call;
- no gold/reference answer is allowed in the manual evidence packet;
- trace rows can be classified by answer_outcome_gate.

Use only on public/synthetic or otherwise authorized evaluation material.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from answer_outcome_gate import classify_delivery_trace

DEFAULT_MARKER = "AUTHORIZED EXTERNAL PUBLIC EVIDENCE:\n"
FORBIDDEN_GOLD_KEYS = {
    "gold", "gold_answer", "reference", "reference_answer",
    "expected_answer", "target_answer",
}


def canonical_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages_must_be_nonempty_list")
    clean = []
    for m in messages:
        if not isinstance(m, dict):
            raise ValueError("message_must_be_object")
        role = str(m.get("role") or "").strip()
        if not role:
            raise ValueError("message_role_required")
        clean.append({"role": role, "content": str(m.get("content") or "")})
    return clean


def model_input_record(messages):
    clean = canonical_messages(messages)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return {
        "messages": clean,
        "model_input_sha256": hashlib.sha256(raw).hexdigest(),
        "model_input_bytes": len(raw),
    }


def _reject_gold(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).strip().casefold() in FORBIDDEN_GOLD_KEYS:
                raise ValueError("gold_or_reference_forbidden_in_manual_evidence")
            _reject_gold(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_gold(v)


def load_manual_evidence(path):
    """Load case_id -> raw evidence while rejecting answer-bearing fields."""
    rows = []
    for line in Path(path).read_text("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        _reject_gold(row)
        cid = str(row.get("case_id") or "").strip()
        evidence = str(row.get("evidence_text") or "")
        if not cid or not evidence.strip():
            raise ValueError("manual_evidence_requires_case_id_and_evidence_text")
        rows.append(row)
    if len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate_manual_evidence_case_id")
    return {r["case_id"]: r for r in rows}


def replace_evidence_section(messages, evidence_text, marker=DEFAULT_MARKER):
    """Replace only the evidence payload, preserving question/prompt framing."""
    clean = canonical_messages(messages)
    idx = None
    for i in range(len(clean) - 1, -1, -1):
        if marker in clean[i]["content"]:
            idx = i
            break
    if idx is None:
        raise ValueError("evidence_marker_not_found")
    before, _ = clean[idx]["content"].split(marker, 1)
    clean[idx] = {
        "role": clean[idx]["role"],
        "content": before + marker + str(evidence_text).strip() + "\n",
    }
    return clean


def prepare_manual_fulltext_arm(case, manual_row, marker=DEFAULT_MARKER):
    """Create the exact answer-model input for the manual-evidence intervention."""
    messages = replace_evidence_section(
        case["baseline_messages"], manual_row["evidence_text"], marker=marker
    )
    rec = model_input_record(messages)
    return {
        "case_id": case["case_id"],
        "arm": "baseline_manual_complete_evidence",
        "manual_source_refs": list(manual_row.get("source_refs") or []),
        "manual_evidence_sha256": hashlib.sha256(
            manual_row["evidence_text"].encode("utf-8")
        ).hexdigest(),
        **rec,
    }


def classify_trace_row(row):
    """Classify a human/independently annotated H/R/P/W/A trace row."""
    out = classify_delivery_trace(row)
    return {**row, "classification": out}


def write_plan(suite_path, manual_evidence_path, case_ids, output_path,
               marker=DEFAULT_MARKER):
    suite = json.loads(Path(suite_path).read_text("utf-8"))
    manual = load_manual_evidence(manual_evidence_path)
    wanted = set(case_ids)
    cases = []
    for case in suite.get("cases", []):
        cid = case.get("case_id")
        if cid not in wanted:
            continue
        if cid not in manual:
            raise ValueError("manual_evidence_missing:" + str(cid))
        cases.append(prepare_manual_fulltext_arm(case, manual[cid], marker))
    if len(cases) != len(wanted):
        present = {x["case_id"] for x in cases}
        raise ValueError("suite_case_missing:" + ",".join(sorted(wanted - present)))
    result = {
        "schema": "xiaoyu-manual-full-evidence-diagnostic-plan-v1",
        "gold_loaded": False,
        "purpose": "separate evidence acquisition/packaging from answer consumption",
        "n": len(cases),
        "cases": cases,
    }
    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    return result


def _read_case_ids(path):
    obj = json.loads(Path(path).read_text("utf-8"))
    if isinstance(obj, dict):
        obj = obj.get("case_ids")
    if not isinstance(obj, list) or not obj:
        raise ValueError("case_ids_must_be_nonempty_list")
    return [str(x) for x in obj]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare")
    pp.add_argument("--suite", required=True)
    pp.add_argument("--manual-evidence", required=True)
    pp.add_argument("--case-ids", required=True)
    pp.add_argument("--output", required=True)
    pp.add_argument("--marker", default=DEFAULT_MARKER)

    cp = sub.add_parser("classify")
    cp.add_argument("--trace-jsonl", required=True)
    cp.add_argument("--output", required=True)

    args = ap.parse_args()
    if args.cmd == "prepare":
        result = write_plan(
            args.suite, args.manual_evidence,
            _read_case_ids(args.case_ids), args.output, marker=args.marker
        )
        print(json.dumps({
            "schema": result["schema"], "n": result["n"],
            "gold_loaded": result["gold_loaded"], "output": args.output
        }, ensure_ascii=False, indent=2))
        return

    rows = []
    for line in Path(args.trace_jsonl).read_text("utf-8").splitlines():
        if line.strip():
            rows.append(classify_trace_row(json.loads(line)))
    Path(args.output).write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
        "utf-8",
    )
    print(json.dumps({
        "n": len(rows),
        "stage_counts": {
            k: sum(x["classification"]["stage"] == k for x in rows)
            for k in sorted({x["classification"]["stage"] for x in rows})
        },
        "output": args.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
