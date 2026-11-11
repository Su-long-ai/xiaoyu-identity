#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
RUNTIME = GOV / "budget50_halumem_dev_runtime_v1"
PRED_DIR = RUNTIME / "predictions"
CP_ROOT = RUNTIME / "state_checkpoints"

sys.path.insert(0, str(GOV))
import stagea_exact_retrieval_diagnostic as d1

qa = d1.qa
r52 = d1.r52

D1 = d1.load(GOV / "STAGEA_EXACT_RETRIEVAL_DIAGNOSTIC.json")
QA = d1.load(RUNTIME / "QA_INPUTS_POST_SEAL.json")["rows"]
QA_BY = {x["qa_case_id"]: x for x in QA}
DETAIL_BY = {x["qa_case_id"]: x for x in D1["details"]}
OUT = GOV / "STAGEA_OMISSION_ROOTCAUSE_DEEPDIVE.json"


def best_goldlike(text, evidence):
    best = None
    for ev in evidence:
        et = str(ev.get("memory_content") or "")
        if not et:
            continue
        s = d1.gold_similarity(str(text or ""), et)
        if best is None or (
            s["gold_like"], s["evidence_coverage"], s["jaccard"], s["intersection"]
        ) > (
            best["gold_like"], best["evidence_coverage"], best["jaccard"], best["intersection"]
        ):
            best = s
    return best or {
        "jaccard": 0.0, "evidence_coverage": 0.0, "row_coverage": 0.0,
        "intersection": 0, "substring": False, "gold_like": False,
    }


def goldlike_rows(rows, evidence):
    out = []
    for r in rows:
        s = best_goldlike(r.get("text") if isinstance(r, dict) else r["source_text"], evidence)
        if s["gold_like"]:
            item = dict(r)
            item["gold_similarity"] = s
            out.append(item)
    return out


def support_reject_reason(question: str, row: dict) -> dict:
    text = str(row.get("text") or "")
    auth = str(row.get("authority") or "")
    choice = qa._choice_question(question)
    lexical = qa._lexical_overlap(question, text)
    subject = qa._subject_overlap(question, text)
    nonassertive = qa._nonassertive(text)
    possessive_mismatch = qa._possessive_subject_mismatch(question, text)
    assistant_q = qa._assistant_action_question(question)
    assistant_assert = qa._assistant_action_assertion(text)
    direct_choice = qa._direct_user_choice(text, auth) if choice else None
    raw_user_affirm = bool(
        re.search(
            r"\b(i am|i live|i work|i use|i prefer|i chose|i selected|i decided|i have|my .{1,50} is)\b",
            text.casefold(),
        )
    )
    if not text.strip():
        reason = "EMPTY_TEXT"
    elif choice and subject <= 0:
        reason = "CHOICE_SUBJECT_NO_OVERLAP"
    elif (not choice) and lexical <= 0:
        reason = "LEXICAL_NO_OVERLAP"
    elif nonassertive:
        reason = "NONASSERTIVE_OR_UNCERTAIN"
    elif possessive_mismatch:
        reason = "POSSESSIVE_SUBJECT_MISMATCH"
    elif assistant_q:
        reason = "SUPPORTED" if (auth == "conversation_history" and assistant_assert) else "ASSISTANT_ACTION_AUTHORITY_REJECT"
    elif choice:
        reason = "SUPPORTED" if direct_choice else "CHOICE_NOT_DIRECT_COMMITMENT"
    elif auth in ("user_state", "user_history"):
        reason = "SUPPORTED"
    elif auth == "user_source_history":
        reason = "SUPPORTED" if raw_user_affirm else "RAW_USER_NOT_MATCHING_AFFIRMATIVE_REGEX"
    elif auth == "conversation_history":
        ok = bool(
            re.search(
                r"\b(your .{1,60} is|you (?:are|live|work|use|prefer|chose|selected|decided|have))\b",
                text.casefold(),
            )
            or assistant_assert
        )
        reason = "SUPPORTED" if ok else "CONVERSATION_HISTORY_ASSERTION_REGEX_REJECT"
    else:
        reason = "AUTHORITY_NOT_ADMITTED"
    return {
        "reason": reason,
        "authority": auth,
        "lexical_overlap": lexical,
        "subject_overlap": subject,
        "choice_question": choice,
        "nonassertive": nonassertive,
        "possessive_mismatch": possessive_mismatch,
        "assistant_action_question": assistant_q,
        "raw_user_affirmative_regex": raw_user_affirm,
    }


def main():
    rows_out = []
    retrieval_miss_subtypes = {}
    support_reject_reasons = {}
    answered_omission = []

    for pp in sorted(PRED_DIR.glob("*.json")):
        pred = d1.load(pp)
        variant = pred["variant"]
        pref = pred["uuid_hash_prefix"]
        stream_key = pp.stem

        for local_idx, sess in enumerate(pred.get("sessions") or []):
            global_si = int(sess["session_index"])
            cp = CP_ROOT / stream_key / f"session-{local_idx + 1:03d}.sqlite3"
            with tempfile.TemporaryDirectory(prefix="stagea-deepdive-") as td:
                db = Path(td) / "state.sqlite3"
                shutil.copy2(cp, db)
                comp = r52.R52Composition(db, identity_id=f"budget50-dev:{stream_key}")
                try:
                    d1.bind_current_session_external_ids(comp, variant, pref, global_si)
                    current = [dict(x) for x in comp.current_rows()]
                    history = [dict(x) for x in comp.history_rows()]
                    raw_user = []
                    raw_assistant = []
                    for src in comp.store.source_history():
                        item = {
                            "text": str(src["source_text"]),
                            "source_message_id": str(src["source_message_id"]),
                            "conversation_id": str(src["conversation_id"]),
                            "message_id": str(src["message_id"]),
                            "effective_at": int(src["effective_at"]),
                            "lifecycle": str(src["lifecycle"]),
                            "authority": "user_source_history" if src["source_role"] == "user" else "conversation_history",
                        }
                        if src["source_role"] == "user":
                            raw_user.append(item)
                        elif src["source_role"] == "assistant":
                            raw_assistant.append(item)

                    for q in sess.get("questions") or []:
                        qid = q["qa_case_id"]
                        d = DETAIL_BY[qid]
                        if d["label"] != "Omission":
                            continue
                        gold = QA_BY[qid]
                        evidence = gold.get("evidence") or []
                        rec = {
                            "qa_case_id": qid,
                            "variant": variant,
                            "session_index": global_si,
                            "question": gold["question"],
                            "reference_answer": gold["answer"],
                            "system_response": gold["system_response"],
                            "d1_root_cause": d["root_cause"],
                        }

                        if d["root_cause"] == "RETRIEVAL_MISS_GOLDLIKE":
                            cur_hits = goldlike_rows(current, evidence)
                            hist_hits = goldlike_rows(history, evidence)
                            raw_user_hits = goldlike_rows(raw_user, evidence)
                            raw_asst_hits = goldlike_rows(raw_assistant, evidence)
                            if cur_hits:
                                subtype = "CURRENT_STATE_PRESENT_TOP7_MISS"
                            elif hist_hits:
                                subtype = "SEMANTIC_HISTORY_PRESENT_TOP7_MISS"
                            elif raw_user_hits:
                                subtype = "RAW_USER_SOURCE_PRESENT_TOP7_MISS"
                            elif raw_asst_hits:
                                subtype = "RAW_ASSISTANT_SOURCE_PRESENT_BUT_NOT_ADMISSIBLE_OR_RETRIEVED"
                            else:
                                subtype = "NO_GOLDLIKE_ROW_IN_STATE_OR_RAW_SOURCE"
                            retrieval_miss_subtypes[subtype] = retrieval_miss_subtypes.get(subtype, 0) + 1
                            rec.update({
                                "subtype": subtype,
                                "current_goldlike": cur_hits[:5],
                                "history_goldlike": hist_hits[:5],
                                "raw_user_goldlike": raw_user_hits[:5],
                                "raw_assistant_goldlike": raw_asst_hits[:5],
                            })
                        elif d["root_cause"] == "SUPPORT_GATE_REJECT_GOLDLIKE_RETRIEVED":
                            rejects = []
                            for rr in d["retrieved"]:
                                if not rr["gold_similarity"]["gold_like"]:
                                    continue
                                diag = support_reject_reason(gold["question"], rr)
                                rejects.append({
                                    "rank": rr["rank"],
                                    "text": rr["text"],
                                    "authority": rr["authority"],
                                    "channel": rr.get("channel"),
                                    "gold_similarity": rr["gold_similarity"],
                                    "support_diag": diag,
                                })
                                reason = diag["reason"]
                                support_reject_reasons[reason] = support_reject_reasons.get(reason, 0) + 1
                            rec["goldlike_retrieved_rejects"] = rejects
                        elif d["root_cause"] == "ORIGINAL_ANSWERED":
                            answered_omission.append({
                                "qa_case_id": qid,
                                "variant": variant,
                                "question": gold["question"],
                                "reference_answer": gold["answer"],
                                "system_response": gold["system_response"],
                                "supported": d.get("supported"),
                                "retrieved": d.get("retrieved"),
                            })
                        rows_out.append(rec)
                finally:
                    comp.close()

    out = {
        "schema": "xiaoyu-stagea-omission-rootcause-deepdive-v1",
        "omission_n": len(rows_out),
        "retrieval_miss_subtypes": retrieval_miss_subtypes,
        "support_reject_reasons": support_reject_reasons,
        "answered_omission_n": len(answered_omission),
        "answered_omission": answered_omission,
        "rows": rows_out,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({
        "omission_n": out["omission_n"],
        "retrieval_miss_subtypes": retrieval_miss_subtypes,
        "support_reject_reasons": support_reject_reasons,
        "answered_omission_n": len(answered_omission),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
