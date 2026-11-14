# -*- coding: utf-8 -*-
"""Execute a prepared manual-full-evidence diagnostic plan.

This runner never reads gold/reference answers. The plan already contains the
exact messages that will be sent. It verifies their SHA before each call and
records the exact messages alongside the raw answer for H/R/P/W/A analysis.

No call occurs unless this script is explicitly executed with a budget task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(r"D:\dsh-fish")
AGENTS = ROOT / "governance/evaluation/v11_capability/agents"
sys.path[:0] = [str(ROOT), str(AGENTS)]

from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_outcome_gate import inspect_answer
from governance.evaluation.v11_capability.agents.evidence_delivery_diagnostic import (
    model_input_record,
)


def jl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def append(path, row):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config(provider, model, reasoning_effort):
    cfg = dict(PROVIDERS[provider])
    cfg.update({
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "temperature": 0,
        "_capture_finish_reason": True,
    })
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--task", required=True,
                    help="Existing authorized budget-scope task ID")
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--reasoning-effort", default="none")
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--cache-only", action="store_true")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text("utf-8"))
    if plan.get("gold_loaded") is not False:
        raise RuntimeError("diagnostic_plan_must_be_gold_free")
    done = {x["case_id"]: x for x in jl(args.output)}
    cfg = config(args.provider, args.model, args.reasoning_effort)

    for case in plan.get("cases", []):
        cid = case["case_id"]
        if cid in done:
            continue
        rec = model_input_record(case["messages"])
        if rec["model_input_sha256"] != case["model_input_sha256"]:
            raise RuntimeError("model_input_drift:" + cid)

        response, usage = cached_chat(
            cfg,
            case["messages"],
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            namespace=args.namespace,
            budget_scope=args.task,
            cache_only=args.cache_only,
        )
        answer = str(response or "").strip()
        finish = usage.get("_finish_reason")
        if not answer:
            raise RuntimeError("empty_answer:" + cid)
        row = {
            "case_id": cid,
            "arm": case.get("arm"),
            "answer": answer,
            "finish_reason": finish,
            "integrity": inspect_answer(answer, finish),
            "model_input_sha256": rec["model_input_sha256"],
            "model_input_bytes": rec["model_input_bytes"],
            "model_messages": rec["messages"],
            "manual_evidence_sha256": case["manual_evidence_sha256"],
            "manual_source_refs": case.get("manual_source_refs") or [],
        }
        append(args.output, row)
        done[cid] = row
        print("ANSWER", len(done), "/", plan["n"], cid, finish, flush=True)

    if len(done) != plan["n"]:
        raise RuntimeError("diagnostic_incomplete")
    seal = args.output.with_suffix(args.output.suffix + ".seal.json")
    seal.write_text(json.dumps({
        "schema": "xiaoyu-manual-full-evidence-diagnostic-seal-v1",
        "n": plan["n"],
        "plan_sha256": sha(args.plan),
        "answers_sha256": sha(args.output),
        "gold_loaded": False,
        "provider": args.provider,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "cache_only": args.cache_only,
        "created_at": time.time(),
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print("SEALED", seal, sha(seal), flush=True)


if __name__ == "__main__":
    main()
