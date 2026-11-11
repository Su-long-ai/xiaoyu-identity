#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
FROZEN = GOV / "confirmatory_frozen"
RUNTIME = GOV / "budget50_halumem_dev_runtime_v1"

for p in (str(FROZEN), str(GOV), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import r52_composition_candidate_v8 as r52
import r52_qa_sufficiency_v7 as qa

QA_INPUTS = RUNTIME / "QA_INPUTS_POST_SEAL.json"
PRED_DIR = RUNTIME / "predictions"
CP_ROOT = RUNTIME / "state_checkpoints"
V1_PROGRESS = RUNTIME / "QA_SCORE_RECOVERY_PROGRESS_V1.json"
V1_ABORT = RUNTIME / "QA_SCORE_RECOVERY_ABORT_V1.json"
V2_PROGRESS = RUNTIME / "QA_SCORE_CONTINUATION_V2_PROGRESS.json"
OUT = GOV / "STAGEA_EXACT_RETRIEVAL_DIAGNOSTIC.json"


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def stable(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def basic_tokens(text: str) -> set[str]:
    xs = re.findall(r"[a-z0-9]+", str(text).casefold().replace("_", " "))
    out = set()
    for x in xs:
        if len(x) > 4 and x.endswith("ing"):
            x = x[:-3]
        elif len(x) > 3 and x.endswith("ed"):
            x = x[:-2]
        elif len(x) > 3 and x.endswith("s"):
            x = x[:-1]
        if len(x) > 1:
            out.add(x)
    return out


def norm_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold().replace("_", " ")))


def gold_similarity(row_text: str, evidence_text: str) -> dict:
    a = norm_text(row_text)
    b = norm_text(evidence_text)
    ta = basic_tokens(row_text)
    tb = basic_tokens(evidence_text)
    inter = len(ta & tb)
    union = len(ta | tb)
    jaccard = inter / union if union else 0.0
    evidence_coverage = inter / len(tb) if tb else 0.0
    row_coverage = inter / len(ta) if ta else 0.0
    substring = bool(a and b and (a in b or b in a))
    gold_like = substring or (inter >= 2 and evidence_coverage >= 0.50)
    return {
        "jaccard": round(jaccard, 4),
        "evidence_coverage": round(evidence_coverage, 4),
        "row_coverage": round(row_coverage, 4),
        "intersection": inter,
        "substring": substring,
        "gold_like": gold_like,
    }


def label_map():
    v1 = load(V1_PROGRESS)
    v2 = load(V2_PROGRESS)
    labels = {}
    for rec in (v1.get("rows") or []) + (v2.get("rows") or []):
        labels[rec["qa_case_id"]] = str(rec.get("evaluation_result") or "UNKNOWN")
    abstains = {x["qa_case_id"] for x in (v1.get("abstains") or [])}
    abstains.add(load(V1_ABORT)["failed_qa_case_id"])
    for qid in abstains:
        labels[qid] = "JudgeAbstain"
    return labels


def is_gold_unknown(row: dict) -> bool:
    ans = str(row.get("answer") or "").strip().casefold()
    ev = row.get("evidence") or []
    return (not ev) or ans in {"unknown", "i don't know", "i do not know", "not known", "n/a", "none"}


def bind_current_session_external_ids(comp, variant: str, pref: str, global_si: int):
    conv = f"halumem-confirmatory:{variant}:{pref}:session:{global_si}"
    n = 0
    for src in comp.store.source_history():
        if str(src["conversation_id"]) != conv:
            continue
        internal = str(src["source_message_id"])
        ti = int(src["message_id"])
        comp.external_by_internal[internal] = f"hm:{variant}:{pref}:s{global_si}:t{ti}"
        n += 1
    return n


def main():
    qa_rows = load(QA_INPUTS)["rows"]
    qa_by_id = {x["qa_case_id"]: x for x in qa_rows}
    labels = label_map()

    details = []
    stream_summaries = []
    hash_mismatches = []

    pred_files = sorted(PRED_DIR.glob("*.json"))
    for pp in pred_files:
        pred = load(pp)
        variant = pred["variant"]
        pref = pred["uuid_hash_prefix"]
        wstart = int(pred["window_start"])
        stream_key = pp.stem

        for local_idx, sess in enumerate(pred.get("sessions") or []):
            global_si = int(sess["session_index"])
            expected_global = wstart + local_idx
            if global_si != expected_global:
                raise RuntimeError(f"session mapping drift {stream_key}: {global_si} != {expected_global}")

            cp = CP_ROOT / stream_key / f"session-{local_idx + 1:03d}.sqlite3"
            if not cp.is_file():
                raise RuntimeError(f"checkpoint missing: {cp}")

            with tempfile.TemporaryDirectory(prefix="stagea-retrieval-diag-") as td:
                db = Path(td) / "state.sqlite3"
                shutil.copy2(cp, db)
                comp = r52.R52Composition(db, identity_id=f"budget50-dev:{stream_key}")
                try:
                    bound = bind_current_session_external_ids(comp, variant, pref, global_si)
                    for qrec in sess.get("questions") or []:
                        qid = qrec["qa_case_id"]
                        gold = qa_by_id[qid]
                        question = qrec["question"]

                        retrieved = comp.retrieve(question, limit=7)
                        got_hash = stable(retrieved)
                        expected_hash = qrec["retrieved_sha256"]
                        hash_match = got_hash == expected_hash
                        if not hash_match:
                            hash_mismatches.append({
                                "qa_case_id": qid,
                                "stream": stream_key,
                                "session_index": global_si,
                                "expected": expected_hash,
                                "actual": got_hash,
                                "bound_current_session_sources": bound,
                            })

                        if not qa._assistant_action_question(question):
                            admitted = [
                                r for r in retrieved
                                if str(r.get("authority") or "") != "conversation_history"
                            ]
                        else:
                            admitted = retrieved
                        supported = qa.select_supported(question, admitted)

                        evidence = gold.get("evidence") or []
                        row_diag = []
                        max_sim = None
                        gold_like_indices = []
                        for ri, rr in enumerate(retrieved):
                            sims = []
                            for ev in evidence:
                                ev_text = str(ev.get("memory_content") or "")
                                if ev_text:
                                    sims.append(gold_similarity(str(rr.get("text") or ""), ev_text))
                            best = max(
                                sims,
                                key=lambda x: (x["gold_like"], x["evidence_coverage"], x["jaccard"], x["intersection"]),
                                default={
                                    "jaccard": 0.0,
                                    "evidence_coverage": 0.0,
                                    "row_coverage": 0.0,
                                    "intersection": 0,
                                    "substring": False,
                                    "gold_like": False,
                                },
                            )
                            if best["gold_like"]:
                                gold_like_indices.append(ri)
                            if max_sim is None or (
                                best["gold_like"], best["evidence_coverage"], best["jaccard"], best["intersection"]
                            ) > (
                                max_sim["gold_like"], max_sim["evidence_coverage"], max_sim["jaccard"], max_sim["intersection"]
                            ):
                                max_sim = dict(best)
                            row_diag.append({
                                "rank": ri,
                                "text": rr.get("text"),
                                "authority": rr.get("authority"),
                                "channel": rr.get("channel"),
                                "source_id": rr.get("source_id"),
                                "gold_similarity": best,
                                "qa_evidence_supports": qa.evidence_supports(question, rr)
                                if str(rr.get("authority") or "") != "conversation_history"
                                or qa._assistant_action_question(question)
                                else False,
                            })

                        if max_sim is None:
                            max_sim = {
                                "jaccard": 0.0, "evidence_coverage": 0.0, "row_coverage": 0.0,
                                "intersection": 0, "substring": False, "gold_like": False,
                            }

                        original_abstained = bool(qrec.get("abstained"))
                        gold_unknown = is_gold_unknown(gold)
                        if not original_abstained:
                            root_cause = "ORIGINAL_ANSWERED"
                        elif gold_unknown:
                            root_cause = "LEGIT_OR_GOLD_UNKNOWN_ABSTAIN"
                        elif supported:
                            root_cause = "RECONSTRUCTION_SUPPORTED_BUT_STORED_ABSTAIN"
                        elif gold_like_indices:
                            root_cause = "SUPPORT_GATE_REJECT_GOLDLIKE_RETRIEVED"
                        else:
                            root_cause = "RETRIEVAL_MISS_GOLDLIKE"

                        details.append({
                            "qa_case_id": qid,
                            "label": labels.get(qid, "UNSCORED"),
                            "variant": variant,
                            "stream": stream_key,
                            "session_index": global_si,
                            "question": question,
                            "reference_answer": gold.get("answer"),
                            "evidence_count": len(evidence),
                            "system_response": gold.get("system_response"),
                            "original_abstained": original_abstained,
                            "gold_unknown_or_no_evidence": gold_unknown,
                            "checkpoint": str(cp.relative_to(GOV)).replace("\\", "/"),
                            "retrieved_sha256_expected": expected_hash,
                            "retrieved_sha256_actual": got_hash,
                            "retrieved_hash_match": hash_match,
                            "retrieved_count": len(retrieved),
                            "admitted_count": len(admitted),
                            "supported_count": len(supported),
                            "supported": supported,
                            "gold_like_retrieved_indices": gold_like_indices,
                            "best_gold_similarity": max_sim,
                            "root_cause": root_cause,
                            "retrieved": row_diag,
                        })
                finally:
                    comp.close()

    if len(details) != 51:
        raise RuntimeError(f"QA detail count {len(details)} != 51")

    agg = {}
    by_variant = {}
    by_label = {}
    omission_roots = {}
    omission_authority = {}
    for d in details:
        root = d["root_cause"]
        agg[root] = agg.get(root, 0) + 1
        v = by_variant.setdefault(d["variant"], {})
        v[root] = v.get(root, 0) + 1
        lab = by_label.setdefault(d["label"], {})
        lab[root] = lab.get(root, 0) + 1
        if d["label"] == "Omission":
            omission_roots[root] = omission_roots.get(root, 0) + 1
            for rr in d["retrieved"]:
                if rr["gold_similarity"]["gold_like"]:
                    auth = str(rr.get("authority") or "unknown")
                    omission_authority[auth] = omission_authority.get(auth, 0) + 1

    out = {
        "schema": "xiaoyu-stagea-exact-retrieval-diagnostic-v1",
        "qa_n": len(details),
        "prediction_files": len(pred_files),
        "retrieved_hash_matches": len(details) - len(hash_mismatches),
        "retrieved_hash_mismatches": len(hash_mismatches),
        "hash_mismatch_rows": hash_mismatches,
        "root_cause_counts": agg,
        "root_cause_by_variant": by_variant,
        "root_cause_by_label": by_label,
        "omission_root_causes": omission_roots,
        "omission_goldlike_authorities": omission_authority,
        "details": details,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({
        "qa_n": out["qa_n"],
        "hash_matches": out["retrieved_hash_matches"],
        "hash_mismatches": out["retrieved_hash_mismatches"],
        "root_cause_counts": out["root_cause_counts"],
        "omission_root_causes": out["omission_root_causes"],
        "omission_goldlike_authorities": out["omission_goldlike_authorities"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
