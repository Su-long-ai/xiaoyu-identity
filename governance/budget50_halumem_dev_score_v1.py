#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-seal QA budget-worthiness scorer for the RMB50 HaluMem dev gate.

Prediction is completed and sealed before this script may decode pilot gold.
The scorer uses the official HaluMem question prompt with the project's frozen
qwen3.8-flash binding. It intentionally scores only the fixed 51 pilot QA cases:
this is a budget decision gate, not a full HaluMem leaderboard claim.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
FROZEN = GOV / "confirmatory_frozen"
RUNTIME = GOV / "budget50_halumem_dev_runtime_v1"
DEV_MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_GATE_V1.json"
SCORE_MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_SCORE_V1.json"
SEAL = RUNTIME / "PREDICTION_SEAL.json"
QA_INPUTS = RUNTIME / "QA_INPUTS_POST_SEAL.json"
CAL_RESULT = RUNTIME / "JUDGE_CALIBRATION_RESULT.json"
SCORE_PROGRESS = RUNTIME / "QA_SCORE_PROGRESS.json"
FINAL = RUNTIME / "BUDGET_WORTHINESS_RESULT.json"
JUDGE_WRAPPER = GOV / "budget50_halumem_dev_judge_v1.py"
EVAL_TOOLS = FROZEN / "HALUMEM_OFFICIAL_EVAL_TOOLS.PY"
JUDGE_BINDING = FROZEN / "HALUMEM_JUDGE_BINDING.json"
CALIBRATION = FROZEN / "HALUMEM_JUDGE_CALIBRATION_V1.json"
MEDIUM = ROOT / "external" / "halumem_dataset_cache" / "HaluMem-Medium.jsonl"
LONG = ROOT / "external" / "halumem_dataset_cache" / "HaluMem-Long.jsonl"


class ScoreError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def atomic(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _require_seal():
    if not SEAL.is_file():
        raise ScoreError("prediction seal required before any gold decoding")
    seal = load(SEAL)
    if seal.get("sealed") is not True or int(seal.get("gold_fields_materialized_before_seal") or 0) != 0:
        raise ScoreError("invalid prediction seal")
    return seal


def _prediction_question_map(dev: dict) -> dict:
    out = {}
    for spec in dev["streams"]:
        p = RUNTIME / "predictions" / f"{spec['variant']}-{spec['uuid_hash_prefix']}.json"
        d = load(p)
        if d.get("complete") is not True:
            raise ScoreError("prediction incomplete: " + p.name)
        for sess in d.get("sessions") or []:
            for q in sess.get("questions") or []:
                qid = str(q.get("qa_case_id") or "")
                if not qid or qid in out:
                    raise ScoreError("QA prediction id missing/duplicate")
                out[qid] = q
    return out


def _full_rows(path: Path, wanted: set[str]) -> dict:
    rows = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            obj = json.loads(raw)
            u = str(obj.get("uuid") or "")
            if u in wanted:
                rows[u] = obj
    if set(rows) != wanted:
        raise ScoreError("post-seal pilot UUID set mismatch")
    return rows


_QID = re.compile(r"^hm-([ml])-q-([0-9a-f]{12})-(\d+)-(\d+)$")


def prepare() -> dict:
    seal = _require_seal()
    dev = load(DEV_MANIFEST)
    pred = _prediction_question_map(dev)
    if len(pred) != 51:
        raise ScoreError(f"prediction QA cardinality {len(pred)} != 51")

    by_variant = {"m": {}, "l": {}}
    for spec in dev["streams"]:
        by_variant[spec["variant"]][spec["uuid_hash_prefix"]] = spec["uuid"]
    medium_uuids = set(by_variant["m"].values())
    long_uuids = set(by_variant["l"].values())
    gold_rows = {
        "m": _full_rows(MEDIUM, medium_uuids),
        "l": _full_rows(LONG, long_uuids),
    }

    rows = []
    for qid in dev["pilot_membership"]["qa_case_ids"]:
        m = _QID.fullmatch(qid)
        if not m:
            raise ScoreError("bad frozen QA id: " + qid)
        variant, pref, si_s, qi_s = m.groups()
        uuid_value = by_variant[variant].get(pref)
        if not uuid_value:
            raise ScoreError("QA prefix outside pilot streams")
        si = int(si_s)
        qi = int(qi_s)
        session = gold_rows[variant][uuid_value]["sessions"][si]
        questions = session.get("questions") or []
        if qi >= len(questions):
            raise ScoreError("QA question index outside gold session")
        g = questions[qi]
        pq = pred.get(qid)
        if pq is None:
            raise ScoreError("selected QA missing from prediction: " + qid)
        if str(g.get("question")) != str(pq.get("question")):
            raise ScoreError("gold/prediction question text drift: " + qid)
        evidence = g.get("evidence") or []
        rows.append(
            {
                "qa_case_id": qid,
                "variant": variant,
                "uuid": uuid_value,
                "session_index": si,
                "question_index": qi,
                "question": g["question"],
                "answer": g["answer"],
                "evidence": evidence,
                "system_response": pq["system_response"],
            }
        )
    if len(rows) != 51 or len({x["qa_case_id"] for x in rows}) != 51:
        raise ScoreError("post-seal QA input cardinality mismatch")
    atomic(
        QA_INPUTS,
        {
            "schema": "xiaoyu-budget50-halumem-dev-qa-inputs-v1",
            "prediction_seal_sha256": sha(SEAL),
            "gold_decoded_after_seal": True,
            "rows": rows,
        },
    )

    score_manifest = {
        "schema": "xiaoyu-budget50-halumem-dev-score-v1",
        "status": "READY_FOR_QA_SCORING",
        "purpose": "Budget-worthiness QA screen only; not a full HaluMem leaderboard or E2 claim.",
        "prediction_seal_sha256": sha(SEAL),
        "dev_manifest_sha256": sha(DEV_MANIFEST),
        "qa_inputs_sha256": sha(QA_INPUTS),
        "qa_count": 51,
        "implementation": {
            "judge_wrapper_path": "governance/budget50_halumem_dev_judge_v1.py",
            "judge_wrapper_sha256": sha(JUDGE_WRAPPER),
            "official_eval_tools_path": "governance/confirmatory_frozen/HALUMEM_OFFICIAL_EVAL_TOOLS.PY",
            "official_eval_tools_sha256": sha(EVAL_TOOLS),
        },
        "judge": {
            "provider": "alibaba_model_studio",
            "model": "qwen3.8-flash",
            "binding_sha256": sha(JUDGE_BINDING),
            "calibration_sha256": sha(CALIBRATION),
            "required_calibration": "12/12",
            "max_total_calls": 63,
            "qwen_budget_reserve_cny": 10.0,
        },
        "screening_thresholds": dev["screening_thresholds"],
        "hard_boundaries": [
            "Only the frozen 51 already-exposed pilot QA cases may be judged.",
            "The official HaluMem question-evaluation prompt is used unchanged.",
            "The dev judge ledger is separate from formal confirmatory judge receipts.",
            "A FAIL keeps formal confirmatory paused; no holdout retuning is authorized.",
        ],
    }
    atomic(SCORE_MANIFEST, score_manifest)
    return {
        "qa_inputs": str(QA_INPUTS.relative_to(GOV)).replace("\\", "/"),
        "qa_inputs_sha256": sha(QA_INPUTS),
        "score_manifest_sha256": sha(SCORE_MANIFEST),
        "qa_count": 51,
        "gold_decoded_after_seal": True,
        "judge_calls_made": 0,
    }


def _tools():
    if not SCORE_MANIFEST.is_file():
        raise ScoreError("score manifest missing")
    jspec = importlib.util.spec_from_file_location("llms", JUDGE_WRAPPER)
    llms = importlib.util.module_from_spec(jspec)
    sys.modules["llms"] = llms
    jspec.loader.exec_module(llms)
    espec = importlib.util.spec_from_file_location("_budget50_eval_tools", EVAL_TOOLS)
    tools = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(tools)
    return tools


def calibrate() -> dict:
    _require_seal()
    if not SCORE_MANIFEST.is_file():
        raise ScoreError("run prepare after prediction seal")
    if CAL_RESULT.is_file():
        old = load(CAL_RESULT)
        if old.get("score_manifest_sha256") != sha(SCORE_MANIFEST):
            raise ScoreError("existing calibration result manifest drift")
        if int(old.get("passed") or 0) != 12 or int(old.get("total") or 0) != 12:
            raise ScoreError("existing calibration is not 12/12")
        return old

    tools = _tools()
    cal = load(CALIBRATION)
    rows = []
    passed = 0
    for case in cal.get("cases") or []:
        metric = case["metric"]
        x = case["input"]
        expected = case["expected"]
        if metric == "memory_integrity":
            got = tools.evaluation_for_memory_integrity(x["memories"], x["expected_memory_point"])
        elif metric == "memory_accuracy":
            got = tools.evaluation_for_memory_accuracy(x["dialogue"], x["golden_memories"], x["candidate_memory"])
        elif metric == "memory_update":
            got = tools.evaluation_for_update_memory(x["memories"], x["updated_memory"], x["original_memory"])
        elif metric == "question_answering":
            got = tools.evaluation_for_question(
                x["question"], x["reference_answer"], x["key_memory_points"], x["response"]
            )
        else:
            raise ScoreError("unknown calibration metric")
        ok = all(str(got.get(k)) == str(v) for k, v in expected.items())
        rows.append({"id": case["id"], "metric": metric, "ok": ok, "expected": expected, "got": got})
        passed += int(ok)
    out = {
        "schema": "xiaoyu-budget50-halumem-dev-calibration-v1",
        "score_manifest_sha256": sha(SCORE_MANIFEST),
        "passed": passed,
        "total": len(rows),
        "rows": rows,
    }
    atomic(CAL_RESULT, out)
    if passed != 12 or len(rows) != 12:
        raise ScoreError(f"qwen judge calibration failed {passed}/{len(rows)}")
    return out


def _semantic_reject_stats(dev: dict):
    calls = 0
    rejects = 0
    for spec in dev["streams"]:
        p = RUNTIME / "predictions" / f"{spec['variant']}-{spec['uuid_hash_prefix']}.json"
        d = load(p)
        calls += int(d.get("semantic_calls") or 0)
        rejects += int(d.get("semantic_rejects_fail_closed") or 0)
    return calls, rejects


def score() -> dict:
    _require_seal()
    cal = calibrate()
    if int(cal.get("passed") or 0) != 12:
        raise ScoreError("judge calibration not 12/12")
    score_manifest = load(SCORE_MANIFEST)
    qa = load(QA_INPUTS)
    if sha(QA_INPUTS) != score_manifest.get("qa_inputs_sha256"):
        raise ScoreError("QA input byte drift")
    tools = _tools()

    progress = {
        "schema": "xiaoyu-budget50-halumem-dev-qa-score-progress-v1",
        "score_manifest_sha256": sha(SCORE_MANIFEST),
        "rows": [],
    }
    if SCORE_PROGRESS.is_file():
        progress = load(SCORE_PROGRESS)
        if progress.get("score_manifest_sha256") != sha(SCORE_MANIFEST):
            raise ScoreError("QA score progress manifest drift")
    done = {x["qa_case_id"]: x for x in progress.get("rows") or []}

    for row in qa["rows"]:
        qid = row["qa_case_id"]
        if qid in done:
            continue
        evidence = "\n".join(str(x.get("memory_content") or "") for x in row.get("evidence") or [])
        got = tools.evaluation_for_question(
            row["question"],
            row["answer"],
            evidence,
            row["system_response"],
        )
        rec = {
            "qa_case_id": qid,
            "variant": row["variant"],
            "evaluation_result": got.get("evaluation_result"),
            "judge_result": got,
        }
        progress["rows"].append(rec)
        atomic(SCORE_PROGRESS, progress)
        done[qid] = rec

    if len(done) != 51:
        raise ScoreError(f"QA judged count {len(done)} != 51")

    counts = {}
    by_variant = {"m": {}, "l": {}}
    for rec in done.values():
        label = str(rec.get("evaluation_result") or "UNKNOWN")
        counts[label] = counts.get(label, 0) + 1
        d = by_variant[rec["variant"]]
        d[label] = d.get(label, 0) + 1

    def nlabel(d, name):
        return sum(v for k, v in d.items() if k.lower() == name.lower())

    correct = nlabel(counts, "Correct")
    hall = nlabel(counts, "Hallucination")
    m_total = sum(by_variant["m"].values())
    l_total = sum(by_variant["l"].values())
    m_correct = nlabel(by_variant["m"], "Correct")
    l_correct = nlabel(by_variant["l"], "Correct")

    dev = load(DEV_MANIFEST)
    th = dev["screening_thresholds"]
    semantic_calls, semantic_rejects = _semantic_reject_stats(dev)
    metrics = {
        "qa_n": 51,
        "qa_correct": correct,
        "qa_correct_rate": correct / 51,
        "qa_hallucination": hall,
        "qa_hallucination_rate": hall / 51,
        "medium_n": m_total,
        "medium_correct": m_correct,
        "medium_correct_rate": m_correct / m_total if m_total else 0,
        "long_n": l_total,
        "long_correct": l_correct,
        "long_correct_rate": l_correct / l_total if l_total else 0,
        "semantic_calls": semantic_calls,
        "semantic_rejects": semantic_rejects,
        "semantic_reject_rate": semantic_rejects / semantic_calls if semantic_calls else 1,
        "counts": counts,
        "by_variant": by_variant,
    }
    checks = {
        "qa_correct_overall": metrics["qa_correct_rate"] >= float(th["qa_correct_overall_min"]),
        "qa_correct_medium": metrics["medium_correct_rate"] >= float(th["qa_correct_medium_min"]),
        "qa_correct_long": metrics["long_correct_rate"] >= float(th["qa_correct_long_min"]),
        "qa_hallucination": metrics["qa_hallucination_rate"] <= float(th["qa_hallucination_overall_max"]),
        "semantic_reject_rate": metrics["semantic_reject_rate"] <= float(th["semantic_reject_rate_max"]),
        "judge_calibration": int(cal["passed"]) == 12 and int(cal["total"]) == 12,
    }
    passed = all(checks.values())
    out = {
        "schema": "xiaoyu-budget50-halumem-dev-worthiness-v1",
        "decision": "PASS_RESUME_BUDGET_REVIEW" if passed else "FAIL_KEEP_CONFIRMATORY_PAUSED",
        "formal_claim_allowed": False,
        "score_manifest_sha256": sha(SCORE_MANIFEST),
        "metrics": metrics,
        "checks": checks,
        "thresholds": th,
        "next_rule": (
            "PASS permits a separate remaining-budget review; it does not automatically restart formal confirmatory."
            if passed
            else "FAIL routes to pilot/dev remediation; do not tune on or restart the formal holdout."
        ),
    }
    atomic(FINAL, out)
    return out


def status() -> dict:
    return {
        "prediction_seal": SEAL.is_file(),
        "qa_inputs": QA_INPUTS.is_file(),
        "score_manifest": SCORE_MANIFEST.is_file(),
        "calibration": CAL_RESULT.is_file(),
        "score_progress": SCORE_PROGRESS.is_file(),
        "final": FINAL.is_file(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", nargs="?", default="status", choices=["status", "prepare", "calibrate", "score"])
    a = ap.parse_args()
    try:
        if a.action == "status":
            out = status()
        elif a.action == "prepare":
            out = prepare()
        elif a.action == "calibrate":
            out = calibrate()
        else:
            out = score()
    except Exception as exc:
        print(json.dumps({"ok": False, "action": a.action, "error": type(exc).__name__ + ":" + str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps({"ok": True, "action": a.action, "result": out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
