#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-UNKNOWN recovery for the fixed HaluMem Stage-A dev QA gate.

This is a narrow transport/format reconciliation only. It never retries the
already-UNKNOWN prompt. The single abstain is counted as incorrect in all
correctness denominators and is not counted as hallucination. Any second
UNKNOWN/RESERVED anomaly aborts the gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
RUNTIME = GOV / "budget50_halumem_dev_runtime_v1"

FREEZE = GOV / "BUDGET50_HALUMEM_DEV_SCORE_RECOVERY_V1.json"
THIS = Path(__file__).resolve()
BASE_SCORE = GOV / "budget50_halumem_dev_score_v1.py"
DEV_MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_GATE_V1.json"
SCORE_MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_SCORE_V1.json"
QA_INPUTS = RUNTIME / "QA_INPUTS_POST_SEAL.json"
CAL_RESULT = RUNTIME / "JUDGE_CALIBRATION_RESULT.json"
BASE_PROGRESS = RUNTIME / "QA_SCORE_PROGRESS.json"
JUDGE_LEDGER = RUNTIME / "judge_ledger_qwen38_flash_dev_v1.sqlite3"
RECOVERY_PROGRESS = RUNTIME / "QA_SCORE_RECOVERY_PROGRESS_V1.json"
RECOVERY_ABORT = RUNTIME / "QA_SCORE_RECOVERY_ABORT_V1.json"
FINAL = RUNTIME / "BUDGET_WORTHINESS_RECOVERY_V1.json"


class RecoveryError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def atomic(path: Path, obj):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "utf-8")
    tmp.replace(path)


def _load_base_score():
    if ".PY" not in importlib.machinery.SOURCE_SUFFIXES:
        importlib.machinery.SOURCE_SUFFIXES.append(".PY")
    spec = importlib.util.spec_from_file_location("_stagea_base_score", BASE_SCORE)
    if spec is None or spec.loader is None:
        raise RecoveryError("base score loader unavailable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ledger_counts():
    con = sqlite3.connect(JUDGE_LEDGER)
    con.row_factory = sqlite3.Row
    try:
        counts = {r["status"]: int(r["n"]) for r in con.execute(
            "SELECT status,count(*) n FROM judge_calls GROUP BY status"
        )}
        unknown = [dict(r) for r in con.execute(
            "SELECT prompt_sha256,status,model,binding_sha256,error "
            "FROM judge_calls WHERE status='UNKNOWN' ORDER BY created_at"
        )]
        reserved = [dict(r) for r in con.execute(
            "SELECT prompt_sha256,status FROM judge_calls WHERE status='RESERVED'"
        )]
        total = int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])
        return counts, unknown, reserved, total
    finally:
        con.close()


def _structural_state():
    freeze = load(FREEZE)
    if freeze.get("schema") != "xiaoyu-budget50-halumem-dev-score-recovery-v1":
        raise RecoveryError("recovery freeze schema drift")
    if freeze.get("status") != "EXECUTION_AUTHORIZED":
        raise RecoveryError("recovery execution not authorized")
    if (freeze.get("implementation") or {}).get("runner_sha256") != sha(THIS):
        raise RecoveryError("recovery runner byte drift")
    if (freeze.get("bindings") or {}).get("score_manifest_sha256") != sha(SCORE_MANIFEST):
        raise RecoveryError("score manifest drift")
    if (freeze.get("bindings") or {}).get("qa_inputs_sha256") != sha(QA_INPUTS):
        raise RecoveryError("QA input drift")
    if (freeze.get("bindings") or {}).get("calibration_result_sha256") != sha(CAL_RESULT):
        raise RecoveryError("calibration result drift")
    if (freeze.get("bindings") or {}).get("base_progress_sha256") != sha(BASE_PROGRESS):
        raise RecoveryError("base score progress drift")

    cal = load(CAL_RESULT)
    if int(cal.get("passed") or 0) != 12 or int(cal.get("total") or 0) != 12:
        raise RecoveryError("calibration not 12/12")

    qa = load(QA_INPUTS)
    rows = qa.get("rows") or []
    if len(rows) != 51:
        raise RecoveryError("QA cardinality drift")

    base = load(BASE_PROGRESS)
    base_rows = base.get("rows") or []
    expected_base_qids = (freeze.get("pre_recovery_state") or {}).get("committed_score_qids") or []
    if [x.get("qa_case_id") for x in base_rows] != expected_base_qids:
        raise RecoveryError("base committed QA prefix drift")

    unknown_case = (freeze.get("pre_recovery_state") or {}).get("unknown_case_qid")
    if len(base_rows) >= len(rows) or rows[len(base_rows)].get("qa_case_id") != unknown_case:
        raise RecoveryError("unknown case is not exact next frozen QA")

    counts, unknowns, reserved, total = _ledger_counts()
    if reserved:
        raise RecoveryError("judge ledger has RESERVED rows")
    if len(unknowns) != 1:
        raise RecoveryError("expected exactly one pre-existing UNKNOWN")
    expected_unknown = (freeze.get("pre_recovery_state") or {}).get("unknown_prompt_sha256")
    if unknowns[0].get("prompt_sha256") != expected_unknown:
        raise RecoveryError("UNKNOWN prompt hash drift")
    if counts.get("COMMITTED", 0) != 26 or counts.get("UNKNOWN", 0) != 1 or total != 27:
        # This exact pre-state is required only before first recovery call.
        if not RECOVERY_PROGRESS.exists():
            raise RecoveryError("pre-recovery judge count drift")

    return freeze, rows, base_rows


def dry_run():
    freeze, rows, base_rows = _structural_state()
    pending = len(rows) - len(base_rows) - 1
    if pending != 36:
        raise RecoveryError(f"pending call count {pending} != 36")
    return {
        "schema": "xiaoyu-budget50-halumem-dev-score-recovery-dry-run-v1",
        "base_committed_qa": len(base_rows),
        "format_abstain": 1,
        "pending_new_calls": pending,
        "projected_total_judge_rows": 63,
        "call_cap": 63,
        "labels_used_for_freeze": False,
        "unknown_case_qid": freeze["pre_recovery_state"]["unknown_case_qid"],
    }


def execute():
    freeze, qa_rows, base_rows = _structural_state()
    base_score = _load_base_score()
    tools = base_score._tools()

    if RECOVERY_PROGRESS.exists():
        progress = load(RECOVERY_PROGRESS)
        if progress.get("freeze_sha256") != sha(FREEZE):
            raise RecoveryError("recovery progress freeze drift")
    else:
        abstain_qid = freeze["pre_recovery_state"]["unknown_case_qid"]
        abstain_row = qa_rows[len(base_rows)]
        progress = {
            "schema": "xiaoyu-budget50-halumem-dev-qa-score-recovery-progress-v1",
            "freeze_sha256": sha(FREEZE),
            "rows": [dict(x, recovery_origin="pre_recovery_committed") for x in base_rows],
            "abstains": [{
                "qa_case_id": abstain_qid,
                "variant": abstain_row["variant"],
                "reason": "JUDGE_FORMAT_ABSTAIN_NO_RETRY",
                "prompt_sha256": freeze["pre_recovery_state"]["unknown_prompt_sha256"],
                "counts_as_correct": False,
                "counts_as_hallucination": False,
            }],
        }
        atomic(RECOVERY_PROGRESS, progress)

    done = {x["qa_case_id"] for x in progress.get("rows") or []}
    abstain_qids = {x["qa_case_id"] for x in progress.get("abstains") or []}

    for row in qa_rows:
        qid = row["qa_case_id"]
        if qid in done or qid in abstain_qids:
            continue

        counts, unknowns, reserved, total = _ledger_counts()
        if reserved:
            raise RecoveryError("judge ledger RESERVED before next recovery call")
        if len(unknowns) != 1:
            raise RecoveryError("new UNKNOWN detected; recovery must stop")
        if total >= 63:
            raise RecoveryError("judge call cap exhausted before QA completion")

        evidence = "\n".join(str(x.get("memory_content") or "") for x in row.get("evidence") or [])
        try:
            got = tools.evaluation_for_question(
                row["question"],
                row["answer"],
                evidence,
                row["system_response"],
            )
        except Exception as exc:
            counts2, unknowns2, reserved2, total2 = _ledger_counts()
            abort = {
                "schema": "xiaoyu-budget50-halumem-dev-score-recovery-abort-v1",
                "freeze_sha256": sha(FREEZE),
                "failed_qa_case_id": qid,
                "error": type(exc).__name__ + ":" + str(exc),
                "judge_counts": counts2,
                "unknown_count": len(unknowns2),
                "reserved_count": len(reserved2),
                "judge_total_rows": total2,
                "rule": "No retry. Any second UNKNOWN keeps formal confirmatory paused.",
            }
            atomic(RECOVERY_ABORT, abort)
            raise

        rec = {
            "qa_case_id": qid,
            "variant": row["variant"],
            "evaluation_result": got.get("evaluation_result"),
            "judge_result": got,
            "recovery_origin": "post_abstain_committed",
        }
        progress["rows"].append(rec)
        atomic(RECOVERY_PROGRESS, progress)
        done.add(qid)

    counts, unknowns, reserved, total = _ledger_counts()
    if reserved:
        raise RecoveryError("judge ledger RESERVED at completion")
    if len(unknowns) != 1:
        raise RecoveryError("recovery ended with unexpected UNKNOWN count")
    if total != 63 or counts.get("COMMITTED", 0) != 62 or counts.get("UNKNOWN", 0) != 1:
        raise RecoveryError("final judge ledger must be 62 COMMITTED + 1 UNKNOWN")

    scored = progress.get("rows") or []
    abstains = progress.get("abstains") or []
    if len(scored) != 50 or len(abstains) != 1:
        raise RecoveryError("recovery cardinality must be 50 scored + 1 abstain")

    label_counts = {}
    by_variant = {"m": {}, "l": {}}
    for rec in scored:
        label = str(rec.get("evaluation_result") or "UNKNOWN")
        label_counts[label] = label_counts.get(label, 0) + 1
        d = by_variant[rec["variant"]]
        d[label] = d.get(label, 0) + 1
    for abst in abstains:
        label_counts["JudgeAbstain"] = label_counts.get("JudgeAbstain", 0) + 1
        d = by_variant[abst["variant"]]
        d["JudgeAbstain"] = d.get("JudgeAbstain", 0) + 1

    def nlabel(d, name):
        return sum(v for k, v in d.items() if k.lower() == name.lower())

    correct = nlabel(label_counts, "Correct")
    hall = nlabel(label_counts, "Hallucination")
    m_total = sum(by_variant["m"].values())
    l_total = sum(by_variant["l"].values())
    m_correct = nlabel(by_variant["m"], "Correct")
    l_correct = nlabel(by_variant["l"], "Correct")

    dev = load(DEV_MANIFEST)
    th = dev["screening_thresholds"]
    semantic_calls, semantic_rejects = base_score._semantic_reject_stats(dev)

    metrics = {
        "qa_n": 51,
        "qa_semantically_scored": 50,
        "qa_judge_abstain": 1,
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
        "counts": label_counts,
        "by_variant": by_variant,
        "judge_ledger": counts,
    }

    cal = load(CAL_RESULT)
    checks = {
        "qa_correct_overall": metrics["qa_correct_rate"] >= float(th["qa_correct_overall_min"]),
        "qa_correct_medium": metrics["medium_correct_rate"] >= float(th["qa_correct_medium_min"]),
        "qa_correct_long": metrics["long_correct_rate"] >= float(th["qa_correct_long_min"]),
        "qa_hallucination": metrics["qa_hallucination_rate"] <= float(th["qa_hallucination_overall_max"]),
        "semantic_reject_rate": metrics["semantic_reject_rate"] <= float(th["semantic_reject_rate_max"]),
        "judge_calibration": int(cal["passed"]) == 12 and int(cal["total"]) == 12,
        "single_format_abstain_conservative": len(abstains) == 1,
        "judge_call_cap_exact": total == 63,
    }
    passed = all(checks.values())
    out = {
        "schema": "xiaoyu-budget50-halumem-dev-worthiness-recovery-v1",
        "decision": "PASS_RESUME_BUDGET_REVIEW" if passed else "FAIL_KEEP_CONFIRMATORY_PAUSED",
        "formal_claim_allowed": False,
        "freeze_sha256": sha(FREEZE),
        "metrics": metrics,
        "checks": checks,
        "thresholds": th,
        "abstain_policy": {
            "count": 1,
            "counts_as_correct": False,
            "counts_as_hallucination": False,
            "retry_allowed": False,
        },
        "next_rule": (
            "PASS permits only a separate remaining-budget review; formal confirmatory is not auto-started."
            if passed
            else "FAIL keeps formal confirmatory paused; do not tune on or restart the formal holdout."
        ),
    }
    atomic(FINAL, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["dry_run", "execute"])
    args = ap.parse_args()
    try:
        out = dry_run() if args.action == "dry_run" else execute()
    except Exception as exc:
        print(json.dumps({"ok": False, "action": args.action, "error": type(exc).__name__ + ":" + str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps({"ok": True, "action": args.action, "result": out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
