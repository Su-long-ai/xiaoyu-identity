#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-A QA continuation v2 using the parse-observable Qwen wrapper candidate.

Reuses 16 previously COMMITTED QA labels and permanently carries two historical
v1 format UNKNOWNs as conservative abstains. Only the exact 33 never-called QA
prompts may be sent. Any v2 UNKNOWN or FORMAT_REJECTED aborts the continuation.
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

FREEZE = GOV / "BUDGET50_HALUMEM_DEV_SCORE_CONTINUATION_V2.json"
THIS = Path(__file__).resolve()
WRAPPER = GOV / "budget50_halumem_dev_judge_v2_candidate.py"
EVAL_TOOLS = GOV / "confirmatory_frozen" / "HALUMEM_OFFICIAL_EVAL_TOOLS.PY"
DEV_MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_GATE_V1.json"
QA_INPUTS = RUNTIME / "QA_INPUTS_POST_SEAL.json"
CAL_RESULT = RUNTIME / "JUDGE_CALIBRATION_RESULT.json"
V1_RECOVERY_PROGRESS = RUNTIME / "QA_SCORE_RECOVERY_PROGRESS_V1.json"
V1_RECOVERY_ABORT = RUNTIME / "QA_SCORE_RECOVERY_ABORT_V1.json"
V2_LEDGER = RUNTIME / "judge_ledger_qwen38_flash_dev_v2.sqlite3"
V2_PROGRESS = RUNTIME / "QA_SCORE_CONTINUATION_V2_PROGRESS.json"
V2_ABORT = RUNTIME / "QA_SCORE_CONTINUATION_V2_ABORT.json"
FINAL = RUNTIME / "BUDGET_WORTHINESS_CONTINUATION_V2.json"


class ContinuationError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def atomic(path: Path, obj):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "utf-8")
    tmp.replace(path)


def _load_tools():
    if ".PY" not in importlib.machinery.SOURCE_SUFFIXES:
        importlib.machinery.SOURCE_SUFFIXES.append(".PY")
    wspec = importlib.util.spec_from_file_location("llms", WRAPPER)
    if wspec is None or wspec.loader is None:
        raise ContinuationError("v2 wrapper loader unavailable")
    wrapper = importlib.util.module_from_spec(wspec)
    sys.modules["llms"] = wrapper
    wspec.loader.exec_module(wrapper)
    espec = importlib.util.spec_from_file_location("_stagea_eval_tools_v2", EVAL_TOOLS)
    if espec is None or espec.loader is None:
        raise ContinuationError("official eval loader unavailable")
    tools = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(tools)
    return wrapper, tools


def _v2_ledger_state():
    if not V2_LEDGER.exists():
        return {}, [], 0
    con = sqlite3.connect(V2_LEDGER)
    con.row_factory = sqlite3.Row
    try:
        counts = {r["status"]: int(r["n"]) for r in con.execute(
            "SELECT status,count(*) n FROM judge_calls GROUP BY status"
        )}
        bad = [dict(r) for r in con.execute(
            "SELECT prompt_sha256,status,error,response_text,prompt_tokens,completion_tokens,total_tokens "
            "FROM judge_calls WHERE status!='COMMITTED' ORDER BY created_at"
        )]
        total = int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])
        return counts, bad, total
    finally:
        con.close()


def _state():
    fr = load(FREEZE)
    if fr.get("schema") != "xiaoyu-budget50-halumem-dev-score-continuation-v2":
        raise ContinuationError("continuation freeze schema drift")
    if fr.get("status") != "EXECUTION_AUTHORIZED":
        raise ContinuationError("continuation not authorized")
    if (fr.get("implementation") or {}).get("scorer_sha256") != sha(THIS):
        raise ContinuationError("continuation scorer byte drift")
    if (fr.get("implementation") or {}).get("judge_wrapper_sha256") != sha(WRAPPER):
        raise ContinuationError("v2 judge wrapper byte drift")
    if (fr.get("bindings") or {}).get("qa_inputs_sha256") != sha(QA_INPUTS):
        raise ContinuationError("QA inputs drift")
    if (fr.get("bindings") or {}).get("calibration_result_sha256") != sha(CAL_RESULT):
        raise ContinuationError("calibration result drift")
    if (fr.get("bindings") or {}).get("v1_recovery_progress_sha256") != sha(V1_RECOVERY_PROGRESS):
        raise ContinuationError("v1 recovery progress drift")
    if (fr.get("bindings") or {}).get("v1_recovery_abort_sha256") != sha(V1_RECOVERY_ABORT):
        raise ContinuationError("v1 recovery abort drift")

    cal = load(CAL_RESULT)
    if int(cal.get("passed") or 0) != 12 or int(cal.get("total") or 0) != 12:
        raise ContinuationError("reused calibration is not 12/12")

    qa = load(QA_INPUTS)
    qa_rows = qa.get("rows") or []
    if len(qa_rows) != 51:
        raise ContinuationError("QA cardinality drift")

    v1 = load(V1_RECOVERY_PROGRESS)
    committed = v1.get("rows") or []
    historical_abstains = list(v1.get("abstains") or [])
    abort = load(V1_RECOVERY_ABORT)
    historical_abstains.append({
        "qa_case_id": abort["failed_qa_case_id"],
        "variant": next(x["variant"] for x in qa_rows if x["qa_case_id"] == abort["failed_qa_case_id"]),
        "reason": "JUDGE_FORMAT_ABSTAIN_NO_RETRY",
        "counts_as_correct": False,
        "counts_as_hallucination": False,
        "source": "v1_second_unknown_abort",
    })

    committed_qids = [x["qa_case_id"] for x in committed]
    abstain_qids = [x["qa_case_id"] for x in historical_abstains]
    pending_qids = [x["qa_case_id"] for x in qa_rows if x["qa_case_id"] not in set(committed_qids + abstain_qids)]

    pre = fr.get("pre_state") or {}
    if committed_qids != pre.get("committed_qids"):
        raise ContinuationError("committed QA set drift")
    if abstain_qids != pre.get("historical_abstain_qids"):
        raise ContinuationError("historical abstain set drift")
    if pending_qids != pre.get("pending_qids"):
        raise ContinuationError("pending QA set drift")
    if len(committed_qids) != 16 or len(abstain_qids) != 2 or len(pending_qids) != 33:
        raise ContinuationError("continuation cardinality drift")

    return fr, qa_rows, committed, historical_abstains, pending_qids


def dry_run():
    fr, qa_rows, committed, abstains, pending = _state()
    counts, bad, total = _v2_ledger_state()
    if bad:
        raise ContinuationError("v2 ledger already contains non-COMMITTED rows")
    if total not in (0, len(load(V2_PROGRESS).get("rows") or []) if V2_PROGRESS.exists() else 0):
        raise ContinuationError("v2 ledger/progress cardinality mismatch")
    return {
        "schema": "xiaoyu-budget50-halumem-dev-score-continuation-v2-dry-run",
        "reused_committed": len(committed),
        "historical_abstains": len(abstains),
        "pending_new_calls": len(pending),
        "new_call_cap": int((fr.get("judge") or {}).get("new_call_cap") or 0),
        "calibration_reused": "12/12",
        "parser_replay_equivalence": fr.get("parser_validation"),
        "provider_calls_made_by_dry_run": 0,
    }


def execute():
    fr, qa_rows, committed, abstains, pending = _state()
    wrapper, tools = _load_tools()

    if V2_PROGRESS.exists():
        prog = load(V2_PROGRESS)
        if prog.get("freeze_sha256") != sha(FREEZE):
            raise ContinuationError("v2 progress freeze drift")
    else:
        prog = {
            "schema": "xiaoyu-budget50-halumem-dev-score-continuation-v2-progress",
            "freeze_sha256": sha(FREEZE),
            "rows": [],
        }
        atomic(V2_PROGRESS, prog)

    done = {x["qa_case_id"] for x in prog.get("rows") or []}
    pending_set = set(pending)
    for row in qa_rows:
        qid = row["qa_case_id"]
        if qid not in pending_set or qid in done:
            continue

        counts, bad, total = _v2_ledger_state()
        if bad:
            raise ContinuationError("v2 ledger non-COMMITTED state before next call")
        if total >= 33:
            raise ContinuationError("v2 call cap exhausted before completion")

        evidence = "\n".join(str(x.get("memory_content") or "") for x in row.get("evidence") or [])
        try:
            got = tools.evaluation_for_question(
                row["question"], row["answer"], evidence, row["system_response"]
            )
        except Exception as exc:
            counts2, bad2, total2 = _v2_ledger_state()
            abort = {
                "schema": "xiaoyu-budget50-halumem-dev-score-continuation-v2-abort",
                "freeze_sha256": sha(FREEZE),
                "failed_qa_case_id": qid,
                "error": type(exc).__name__ + ":" + str(exc),
                "v2_ledger_counts": counts2,
                "v2_bad_rows": bad2,
                "v2_total_rows": total2,
                "rule": "No retry. Any v2 UNKNOWN or FORMAT_REJECTED keeps formal confirmatory paused.",
            }
            atomic(V2_ABORT, abort)
            raise

        prog["rows"].append({
            "qa_case_id": qid,
            "variant": row["variant"],
            "evaluation_result": got.get("evaluation_result"),
            "judge_result": got,
        })
        atomic(V2_PROGRESS, prog)
        done.add(qid)

    counts, bad, total = _v2_ledger_state()
    if bad or total != 33 or counts.get("COMMITTED", 0) != 33:
        raise ContinuationError("v2 final ledger must be exactly 33 COMMITTED")
    if len(prog.get("rows") or []) != 33:
        raise ContinuationError("v2 progress must contain 33 rows")

    all_scored = list(committed) + list(prog["rows"])
    if len(all_scored) != 49 or len(abstains) != 2:
        raise ContinuationError("combined QA cardinality must be 49 scored + 2 abstain")

    counts_label = {}
    by_variant = {"m": {}, "l": {}}
    for rec in all_scored:
        label = str(rec.get("evaluation_result") or "UNKNOWN")
        counts_label[label] = counts_label.get(label, 0) + 1
        d = by_variant[rec["variant"]]
        d[label] = d.get(label, 0) + 1
    for abst in abstains:
        counts_label["JudgeAbstain"] = counts_label.get("JudgeAbstain", 0) + 1
        d = by_variant[abst["variant"]]
        d["JudgeAbstain"] = d.get("JudgeAbstain", 0) + 1

    def nlabel(d, name):
        return sum(v for k, v in d.items() if k.lower() == name.lower())

    correct = nlabel(counts_label, "Correct")
    hall = nlabel(counts_label, "Hallucination")
    m_total = sum(by_variant["m"].values())
    l_total = sum(by_variant["l"].values())
    m_correct = nlabel(by_variant["m"], "Correct")
    l_correct = nlabel(by_variant["l"], "Correct")

    dev = load(DEV_MANIFEST)
    th = dev["screening_thresholds"]
    sem_calls = sem_rejects = 0
    for spec in dev["streams"]:
        p = RUNTIME / "predictions" / f"{spec['variant']}-{spec['uuid_hash_prefix']}.json"
        d = load(p)
        sem_calls += int(d.get("semantic_calls") or 0)
        sem_rejects += int(d.get("semantic_rejects_fail_closed") or 0)

    metrics = {
        "qa_n": 51,
        "qa_semantically_scored": 49,
        "qa_judge_abstain": 2,
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
        "semantic_calls": sem_calls,
        "semantic_rejects": sem_rejects,
        "semantic_reject_rate": sem_rejects / sem_calls if sem_calls else 1,
        "counts": counts_label,
        "by_variant": by_variant,
        "v2_judge_ledger": counts,
    }
    checks = {
        "qa_correct_overall": metrics["qa_correct_rate"] >= float(th["qa_correct_overall_min"]),
        "qa_correct_medium": metrics["medium_correct_rate"] >= float(th["qa_correct_medium_min"]),
        "qa_correct_long": metrics["long_correct_rate"] >= float(th["qa_correct_long_min"]),
        "qa_hallucination": metrics["qa_hallucination_rate"] <= float(th["qa_hallucination_overall_max"]),
        "semantic_reject_rate": metrics["semantic_reject_rate"] <= float(th["semantic_reject_rate_max"]),
        "judge_calibration_reused_12_12": True,
        "historical_abstains_conservative": len(abstains) == 2,
        "v2_new_calls_exact": total == 33,
        "v2_no_unknown_or_format_reject": not bad,
    }
    passed = all(checks.values())
    out = {
        "schema": "xiaoyu-budget50-halumem-dev-worthiness-continuation-v2",
        "decision": "PASS_RESUME_BUDGET_REVIEW" if passed else "FAIL_KEEP_CONFIRMATORY_PAUSED",
        "formal_claim_allowed": False,
        "freeze_sha256": sha(FREEZE),
        "metrics": metrics,
        "checks": checks,
        "thresholds": th,
        "historical_abstain_policy": {
            "count": 2,
            "retry_allowed": False,
            "counts_as_correct": False,
            "counts_as_hallucination": False,
        },
        "next_rule": (
            "PASS permits only a separate remaining-budget review; formal confirmatory is not auto-started."
            if passed
            else "FAIL keeps formal confirmatory paused; remediation must stay on dev/pilot data."
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
