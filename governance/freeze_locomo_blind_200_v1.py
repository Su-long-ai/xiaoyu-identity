#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze a one-shot LoCoMo blind holdout without exposing gold plaintext.

Selection uses ONLY sample_id, QA index, and category. It never uses question,
answer, evidence, summaries, or observations to decide membership.

Outputs:
- LOCOMO_BLIND_200_MEMBERSHIP_V1.json : indices/category/question hashes only
- locomo_blind_200_input_v1.json      : conversation + selected question text only
- LOCOMO_BLIND_200_GOLD_HASH_SEAL_V1.json : hashes of selected answer/evidence only
- LOCOMO_BLIND_200_PROTOCOL_V1.json   : immutable evaluation policy

The original LoCoMo file remains the sole gold source. Gold plaintext must not
be materialized before BOTH baseline and candidate prediction seals exist.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
DATA = ROOT / "external" / "OmniMemEval" / "data" / "locomo" / "locomo10.json"

EXPECTED_DATA_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
SEED = "xiaoyu-locomo-blind-200-v1-20261030"

# Primary memory gate: every conversation contributes 6 of each memory-centric category.
PER_SAMPLE_PRIMARY = {"1": 6, "2": 6, "4": 6}
# Category 3 needs external/common-sense knowledge; diagnostic only.
OPEN_DOMAIN_DIAGNOSTIC_N = 20

MEMBERSHIP = GOV / "LOCOMO_BLIND_200_MEMBERSHIP_V1.json"
BLIND_INPUT = GOV / "locomo_blind_200_input_v1.json"
GOLD_SEAL = GOV / "LOCOMO_BLIND_200_GOLD_HASH_SEAL_V1.json"
PROTOCOL = GOV / "LOCOMO_BLIND_200_PROTOCOL_V1.json"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return sha_bytes(p.read_bytes())


def stable_bytes(x) -> bytes:
    return json.dumps(
        x, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def rank_hash(sample_id: str, qa_index: int, category: str) -> str:
    return sha_bytes(f"{SEED}|{sample_id}|{qa_index}|{category}".encode())


def question_hash(question: str) -> str:
    return sha_bytes(str(question).encode("utf-8"))


def gold_hash(q: dict) -> str:
    # Hash only. Plaintext gold is never written to freeze artifacts.
    payload = {"answer": q.get("answer"), "evidence": q.get("evidence")}
    return sha_bytes(stable_bytes(payload))


def main() -> None:
    if sha_file(DATA) != EXPECTED_DATA_SHA256:
        raise SystemExit("LoCoMo dataset SHA drift")
    data = json.loads(DATA.read_text("utf-8"))
    if not isinstance(data, list) or len(data) != 10:
        raise SystemExit("LoCoMo top-level shape drift")

    selected = []
    by_sample_selected = defaultdict(list)

    # 180 primary questions: 18 per conversation, selected without question/gold content.
    for sample in data:
        sid = str(sample["sample_id"])
        qa = sample.get("qa") or []
        for cat, quota in PER_SAMPLE_PRIMARY.items():
            pool = [
                (rank_hash(sid, i, str(q.get("category"))), i)
                for i, q in enumerate(qa)
                if str(q.get("category")) == cat
            ]
            pool.sort()
            if len(pool) < quota:
                raise SystemExit(f"insufficient category {cat} in {sid}: {len(pool)}")
            for rh, i in pool[:quota]:
                selected.append((sid, i, cat, "PRIMARY_MEMORY_GATE", rh))
                by_sample_selected[sid].append(i)

    # 20 category-3 questions globally, diagnostic only.
    diagnostic_pool = []
    for sample in data:
        sid = str(sample["sample_id"])
        for i, q in enumerate(sample.get("qa") or []):
            cat = str(q.get("category"))
            if cat == "3":
                diagnostic_pool.append((rank_hash(sid, i, cat), sid, i))
    diagnostic_pool.sort()
    if len(diagnostic_pool) < OPEN_DOMAIN_DIAGNOSTIC_N:
        raise SystemExit("insufficient category-3 pool")
    for rh, sid, i in diagnostic_pool[:OPEN_DOMAIN_DIAGNOSTIC_N]:
        selected.append((sid, i, "3", "OPEN_DOMAIN_DIAGNOSTIC", rh))
        by_sample_selected[sid].append(i)

    if len(selected) != 200:
        raise SystemExit(f"selection size drift: {len(selected)}")
    if len({(s, i) for s, i, *_ in selected}) != 200:
        raise SystemExit("duplicate selected QA")

    sample_map = {str(x["sample_id"]): x for x in data}
    membership_rows = []
    gold_rows = []
    for sid, i, cat, role, rh in sorted(selected, key=lambda x: (x[0], x[1])):
        q = sample_map[sid]["qa"][i]
        blind_id = f"locomo-b200-{sid}-{i:03d}"
        membership_rows.append({
            "blind_id": blind_id,
            "sample_id": sid,
            "qa_index": i,
            "category": cat,
            "evaluation_role": role,
            "question_sha256": question_hash(q.get("question", "")),
            "selection_rank_sha256": rh,
        })
        gold_rows.append({
            "blind_id": blind_id,
            "gold_answer_evidence_sha256": gold_hash(q),
        })

    # Stripped model-visible input. No answer/evidence/event_summary/observation/session_summary.
    input_samples = []
    for sample in data:
        sid = str(sample["sample_id"])
        chosen = sorted(set(by_sample_selected.get(sid, [])))
        if not chosen:
            continue
        qs = []
        for i in chosen:
            q = sample["qa"][i]
            row = next(
                x for x in membership_rows
                if x["sample_id"] == sid and x["qa_index"] == i
            )
            qs.append({
                "blind_id": row["blind_id"],
                "qa_index": i,
                "category": row["category"],
                "evaluation_role": row["evaluation_role"],
                "question": q.get("question"),
                "question_sha256": row["question_sha256"],
            })
        input_samples.append({
            "sample_id": sid,
            "conversation": sample.get("conversation"),
            "questions": qs,
        })

    membership_obj = {
        "schema": "xiaoyu-locomo-blind-membership-v1",
        "status": "FROZEN_ONE_SHOT",
        "dataset_sha256": EXPECTED_DATA_SHA256,
        "selection_seed": SEED,
        "selection_uses_question_text": False,
        "selection_uses_answer": False,
        "selection_uses_evidence": False,
        "selection_uses_summary_or_observation": False,
        "primary_per_sample": PER_SAMPLE_PRIMARY,
        "open_domain_diagnostic_n": OPEN_DOMAIN_DIAGNOSTIC_N,
        "primary_n": 180,
        "diagnostic_n": 20,
        "total_n": 200,
        "rows": membership_rows,
    }
    MEMBERSHIP.write_text(
        json.dumps(membership_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    blind_obj = {
        "schema": "xiaoyu-locomo-blind-input-v1",
        "status": "MODEL_VISIBLE_GOLD_STRIPPED",
        "dataset_sha256": EXPECTED_DATA_SHA256,
        "membership_sha256": sha_file(MEMBERSHIP),
        "contains_answer": False,
        "contains_evidence": False,
        "contains_event_summary": False,
        "contains_observation": False,
        "contains_session_summary": False,
        "samples": input_samples,
    }
    BLIND_INPUT.write_text(
        json.dumps(blind_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    gold_obj = {
        "schema": "xiaoyu-locomo-blind-gold-hash-seal-v1",
        "status": "SEALED_HASHES_ONLY_NO_PLAINTEXT",
        "dataset_sha256": EXPECTED_DATA_SHA256,
        "membership_sha256": sha_file(MEMBERSHIP),
        "selected_n": 200,
        "plaintext_gold_materialized": False,
        "rows": gold_rows,
    }
    GOLD_SEAL.write_text(
        json.dumps(gold_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cats = Counter(x["category"] for x in membership_rows)
    per_sample = Counter(x["sample_id"] for x in membership_rows)
    primary_cats = Counter(
        x["category"] for x in membership_rows
        if x["evaluation_role"] == "PRIMARY_MEMORY_GATE"
    )
    protocol_obj = {
        "schema": "xiaoyu-locomo-blind-200-protocol-v1",
        "status": "FROZEN_BEFORE_ANY_BLIND_PREDICTION",
        "purpose": "One-shot prospective generalization gate after exposed HaluMem dev/regression tuning.",
        "scientific_role": {
            "exposed_10_case_sets": "DEBUG_REGRESSION_ONLY",
            "exposed_halumem_51qa": "DEV_REGRESSION_ONLY",
            "locomo_blind_200": "ONE_SHOT_PROSPECTIVE_GENERALIZATION_GATE",
            "halumem_18_user_confirmatory": "FORMAL_CONFIRMATORY_UNTOUCHED_BY_THIS_PROTOCOL",
        },
        "dataset": {
            "name": "LoCoMo / OmniMemEval locomo10",
            "path": "external/OmniMemEval/data/locomo/locomo10.json",
            "sha256": EXPECTED_DATA_SHA256,
            "license": "CC BY-NC 4.0",
            "sample_count": 10,
        },
        "selection": {
            "seed": SEED,
            "primary": "For each of 10 conversations, hash-rank by sample_id+qa_index+category and take 6 category-1, 6 category-2, 6 category-4.",
            "diagnostic": "Hash-rank all category-3 questions globally and take 20.",
            "category_5_adversarial_excluded": True,
            "selection_content_blind": True,
            "counts_by_category": dict(sorted(cats.items())),
            "primary_counts_by_category": dict(sorted(primary_cats.items())),
            "counts_by_sample": dict(sorted(per_sample.items())),
        },
        "anti_overfit": {
            "one_shot": True,
            "do_not_tune_on_selected_200": True,
            "do_not_read_selected_gold_before_prediction_seals": True,
            "baseline_and_candidate_predictions_must_both_be_sealed_before_gold_decode": True,
            "after_gold_decode_selected_200_becomes_exposed_and_may_only_be_used_for_postmortem": True,
            "unselected_locomo_questions_remain_reserve_and_must_not_be inspected during this gate": True,
        },
        "evaluation_design": {
            "baseline_binding": "PENDING_FROZEN_BASELINE",
            "candidate_binding": "PENDING_POST_DEV_CANDIDATE",
            "primary_n": 180,
            "open_domain_diagnostic_n": 20,
            "primary_metric": "paired LLM-judge accuracy over categories 1,2,4",
            "secondary_metrics": [
                "accuracy by category 1/2/4",
                "open-domain category-3 diagnostic accuracy",
                "hallucination/unsupported-detail rate",
            ],
            "promotion_rule": {
                "candidate_primary_accuracy_must_not_be_lower_than_baseline": True,
                "candidate_primary_absolute_gain_pp_min": 5.0,
                "no_primary_category_drop_pp_more_than": 5.0,
                "open_domain_is_non_gating": True,
                "formal_confirmatory_auto_authorized": False,
            },
        },
        "execution_boundary": {
            "gold_decode_allowed_now": False,
            "paid_execution_authorized_now": False,
            "formal_confirmatory_authorized": False,
            "next_required_step": "Freeze exact baseline and post-dev candidate, independently audit stripped-input/gold boundary, then execute both predictions without gold access.",
        },
        "bindings": {
            "freeze_script": "governance/freeze_locomo_blind_200_v1.py",
            "freeze_script_sha256": sha_file(Path(__file__)),
            "membership": "governance/LOCOMO_BLIND_200_MEMBERSHIP_V1.json",
            "membership_sha256": sha_file(MEMBERSHIP),
            "blind_input": "governance/locomo_blind_200_input_v1.json",
            "blind_input_sha256": sha_file(BLIND_INPUT),
            "gold_hash_seal": "governance/LOCOMO_BLIND_200_GOLD_HASH_SEAL_V1.json",
            "gold_hash_seal_sha256": sha_file(GOLD_SEAL),
        },
    }
    PROTOCOL.write_text(
        json.dumps(protocol_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "status": protocol_obj["status"],
        "dataset_sha256": EXPECTED_DATA_SHA256,
        "membership_sha256": sha_file(MEMBERSHIP),
        "blind_input_sha256": sha_file(BLIND_INPUT),
        "gold_hash_seal_sha256": sha_file(GOLD_SEAL),
        "protocol_sha256": sha_file(PROTOCOL),
        "total_n": 200,
        "primary_n": 180,
        "diagnostic_n": 20,
        "counts_by_category": dict(sorted(cats.items())),
        "primary_counts_by_category": dict(sorted(primary_cats.items())),
        "counts_by_sample": dict(sorted(per_sample.items())),
        "gold_plaintext_written": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
