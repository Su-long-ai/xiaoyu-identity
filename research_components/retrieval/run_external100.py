# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, collections, hashlib, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "governance"
FAST = G / "fastlane"
EVAL = G / "evaluation"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
import model_adapter
from research_components.retrieval.api import (
    authorized_documents, load_component, prepare_component, rank_component,
    component_fingerprint,
)

INPUT = EVAL / "locomo_stage1_100_input_v1.json"
MEMBERSHIP = EVAL / "locomo_stage1_100_membership_v1.json"
TIERS = EVAL / "EXTERNAL_EVAL_TIERS_V1.json"
SOURCE = G / "locomo_blind_source_v2_gold_stripped.json"
STORES = G / "capability_external_200_20261102" / "stores"
OLDW = G / "workspaces" / "fish-2c13552ab6324dbd" / "external200"
GOLD = OLDW / "gold_joined.json"
OLD_ANSWER_REQUESTS = OLDW / "answer_requests.json"
DIAG = G / "workspaces" / "fish-5e91afcff84e4ef6" / "evidence_diagnostic.json"
BASELINE = FAST / "BASELINE.json"

EXPECTED_INPUT_SHA = "6215dd3c2a0f8d249d2cbce3e69cee3aa8963347e00eb7ad4547151187bc7592"
EXPECTED_MEMBERSHIP_SHA = "fd067ab521f5907a2255bee4f62aa3a0d15fdc31b8499ce908fafd996e809a97"

JUDGE_SYSTEM = "You are an expert grader that determines if answers to questions match a gold standard answer."
JUDGE_PROMPT = """Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given the following data:
(1) a question (posed by one user to another user),
(2) a 'gold' (ground truth) answer,
(3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic. The generated answer might be much longer, but be generous: as long as it touches on the same topic as the gold answer, count it as CORRECT.
For time questions, accept equivalent references to the same date or time period even if format differs.

Question: {question}
Gold answer: {golden_answer}
Generated answer: {response}

Return exactly one JSON object: {{"label":"CORRECT"}} or {{"label":"WRONG"}}."""


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_json(raw: str):
    try:
        x = json.loads(raw)
        if isinstance(x, dict):
            return x
    except Exception:
        pass
    return {}


def deepseek():
    b = model_adapter.PROVIDERS["deepseek"]
    return {
        "provider": "deepseek",
        "url": b["url"],
        "model": "deepseek-flash",
        "key_env": b["key_env"],
        "thinking": "disabled",
        "reasoning_effort": "none",
        "temperature": 0,
        "top_p": 1,
        "response_format": {"type": "json_object"},
    }


def user_home(uid: str) -> Path:
    return STORES / hashlib.sha256(str(uid).encode()).hexdigest()


def raw_maps():
    src = load_json(SOURCE)
    out = {}
    for s in src["samples"]:
        sid = str(s["sample_id"])
        by = collections.defaultdict(collections.deque)
        conv = s["conversation"]
        keys = sorted(
            [k for k, v in conv.items() if k.startswith("session_") and isinstance(v, list)],
            key=lambda k: int(k.split("_")[1]),
        )
        for sk in keys:
            for t in conv[sk]:
                speaker = str(t.get("speaker") or "")
                text = (speaker + ": " + str(t.get("text") or "")).strip()
                by[(sk, speaker, text)].append(str(t["dia_id"]))
        out[sid] = by
    return out


def load_side(sid: str, side: str, raw_by):
    uid = f"cap200_{sid}_{side}"
    home = user_home(uid)
    st = IdentityStore(home)
    br = ProductMemoryBridge(home, st)
    try:
        docs = authorized_documents(br)
        result = []
        for d in docs:
            key = (
                str(d.get("session") or ""),
                str(d.get("speaker") or ""),
                str(d.get("text") or "").strip(),
            )
            q = raw_by.get(key)
            if not q:
                raise RuntimeError(f"raw binding missing {sid}/{side}: {key!r}")
            did = q.popleft()
            x = dict(d)
            x["id"] = f"{side}:{d['id']}"
            x["source_key"] = did
            x["speaker_side"] = side
            result.append(x)
        return result
    finally:
        br.close()
        st.close()


def answer_messages(system: str, question: str, docs):
    mems = []
    for i, d in enumerate(docs, 1):
        mems.append(
            f"[{i}] authority=user_source_history timestamp={d.get('timestamp') or 'unknown'}\n{d['text']}"
        )
    user = "AUTHORIZED MEMORIES:\n" + "\n\n".join(mems) + "\n\nQUESTION:\n" + question
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def summarize_judged(rows):
    by = {}
    for r in rows:
        c = str(r["category"])
        z = by.setdefault(c, {"n": 0, "correct": 0})
        z["n"] += 1
        z["correct"] += int(r["correct"])
    for z in by.values():
        z["accuracy"] = z["correct"] / z["n"]
    correct = sum(int(r["correct"]) for r in rows)
    return {
        "overall": {"n": len(rows), "correct": correct, "accuracy": correct / len(rows)},
        "by_category": by,
    }


def evidence_summary(selected_by_id, member_ids):
    diag = load_json(DIAG)
    rows = [d for d in diag["rows"] if str(d["blind_id"]) in member_ids]
    if len(rows) != len(member_ids):
        raise RuntimeError("stage1 evidence diagnostic membership mismatch")
    agg = {"n": 0, "full": 0, "any": 0, "hit": 0, "total": 0}
    by = {}
    details = []
    for d in rows:
        bid = str(d["blind_id"])
        ev = [str(x) for x in d.get("evidence_ids") or []]
        got = set(selected_by_id[bid])
        hit = sum(x in got for x in ev)
        full = bool(ev) and hit == len(ev)
        anyhit = hit > 0
        c = str(d["category"])
        for z in (agg, by.setdefault(c, {"n": 0, "full": 0, "any": 0, "hit": 0, "total": 0})):
            z["n"] += 1
            z["full"] += int(full)
            z["any"] += int(anyhit)
            z["hit"] += hit
            z["total"] += len(ev)
        details.append(
            {
                "blind_id": bid,
                "category": c,
                "evidence_ids": ev,
                "selected_ids": selected_by_id[bid],
                "full": full,
                "hit": hit,
                "total": len(ev),
            }
        )

    def pack(z):
        return {
            "n": z["n"],
            "full_evidence_recall_rate": z["full"] / z["n"],
            "any_evidence_recall_rate": z["any"] / z["n"],
            "evidence_item_recall": z["hit"] / z["total"] if z["total"] else None,
        }

    return {
        "overall": pack(agg),
        "by_category": {k: pack(v) for k, v in sorted(by.items())},
        "rows": details,
    }


def verify_baseline_source(base, member_ids):
    src = ROOT / str(base["source"])
    run = src.parent
    retrieval = run / "retrieval.json"
    pred = run / "predictions.json"
    rseal = load_json(run / "RETRIEVAL_SEAL.json")
    pseal = load_json(run / "PREDICTION_SEAL.json")
    if sha(retrieval) != str(rseal.get("sha256") or ""):
        raise RuntimeError("baseline retrieval seal mismatch")
    if sha(pred) != str(pseal.get("sha256") or ""):
        raise RuntimeError("baseline prediction seal mismatch")
    if str(pseal.get("retrieval_sha256") or "") != sha(retrieval):
        raise RuntimeError("baseline prediction->retrieval binding mismatch")

    rr = load_json(retrieval)["rows"]
    pp = load_json(pred)["rows"]
    rmap = {str(x["blind_id"]): x for x in rr}
    pmap = {str(x["blind_id"]): x for x in pp}
    if not member_ids <= set(rmap) or not member_ids <= set(pmap):
        raise RuntimeError("baseline external200 artifacts do not cover stage1 membership")
    selected = {bid: [str(x) for x in rmap[bid]["selected_source_ids"]] for bid in member_ids}
    preds = [
        {"blind_id": bid, "sample_id": str(pmap[bid]["sample_id"]), "answer": str(pmap[bid]["answer"])}
        for bid in sorted(member_ids)
    ]
    return {
        "run_dir": str(run.relative_to(ROOT)).replace("\\", "/"),
        "retrieval_sha256": sha(retrieval),
        "prediction_sha256": sha(pred),
        "selected": selected,
        "predictions": preds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    audit_path = Path(args.audit).resolve()
    audit = load_json(audit_path)
    if audit.get("verdict") != "PASS" or audit.get("external_stage1_authorized") is not True:
        raise SystemExit("independent light-audit Stage1 authorization required")
    if not bool((audit.get("ood_gate") or {}).get("pass")):
        raise SystemExit("independent Local-OOD120 generalization PASS required")
    if audit.get("external200_authorized") is True:
        raise SystemExit("use run_external200.py directly for an already Stage2-authorized gate")

    tiers = load_json(TIERS)
    s1 = tiers.get("stage1_100") or {}
    rule = s1.get("pass_rule") or {}
    if rule.get("status") not in {"FROZEN_BEFORE_FIRST_RUN","FROZEN_BEFORE_NEXT_RUN"}:
        raise SystemExit("Stage1 pass rule is not frozen")
    freeze_rel=str(rule.get("freeze") or "")
    freeze_path=(ROOT/freeze_rel).resolve() if freeze_rel else None
    if not freeze_path or not freeze_path.is_file():
        raise SystemExit("Stage1 pass-rule freeze artifact missing")
    if sha(freeze_path) != str(rule.get("freeze_sha256") or ""):
        raise SystemExit("Stage1 pass-rule freeze SHA drift")
    freeze_obj=load_json(freeze_path)
    frozen_rule=freeze_obj.get("pass_rule") or {}
    for key in ("min_candidate_vs_baseline_accuracy_delta","min_candidate_vs_baseline_full_evidence_delta","min_retrieval_changed_questions","material_authority_regressions_max"):
        if key in frozen_rule and frozen_rule.get(key) != rule.get(key):
            raise SystemExit(f"Stage1 inline/frozen rule mismatch: {key}")
    if sha(INPUT) != EXPECTED_INPUT_SHA or str(s1.get("input_sha256")) != EXPECTED_INPUT_SHA:
        raise SystemExit("Stage1 input drift")
    if sha(MEMBERSHIP) != EXPECTED_MEMBERSHIP_SHA or str(s1.get("membership_sha256")) != EXPECTED_MEMBERSHIP_SHA:
        raise SystemExit("Stage1 membership drift")

    comp_path = Path(audit["component"]["path"]).resolve()
    expected_comp_sha = str(audit["component"]["sha256"])
    if sha(comp_path) != expected_comp_sha:
        raise SystemExit("component SHA drift after light audit")

    base = load_json(BASELINE)
    expected_base_id = str(rule.get("baseline_id") or "")
    if str(base.get("baseline_id") or "") != expected_base_id:
        raise SystemExit("current fastlane baseline changed after Stage1 rule freeze")
    if sha(ROOT / base["method"]["component"]) != str(base["method"]["component_sha256"]):
        raise SystemExit("current baseline component drift")

    membership = load_json(MEMBERSHIP)
    members = membership.get("members") or []
    member_ids = {str(x["blind_id"]) for x in members}
    if len(member_ids) != 100:
        raise SystemExit("Stage1 membership must contain exactly 100 unique blind IDs")
    data = load_json(INPUT)
    input_ids = {str(q["blind_id"]) for s in data["samples"] for q in s["questions"]}
    if input_ids != member_ids:
        raise SystemExit("Stage1 input/membership mismatch")

    base_art = verify_baseline_source(base, member_ids)

    if args.verify_only:
        print(
            json.dumps(
                {
                    "status": "VERIFY_PASS_NO_PROVIDER",
                    "audit": str(audit_path),
                    "component_sha256": expected_comp_sha,
                    "baseline_id": expected_base_id,
                    "stage1_input_sha256": sha(INPUT),
                    "stage1_membership_sha256": sha(MEMBERSHIP),
                    "baseline_retrieval_sha256": base_art["retrieval_sha256"],
                    "baseline_prediction_sha256": base_art["prediction_sha256"],
                    "questions": len(member_ids),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    component, module_path = load_component(str(comp_path))
    fp = component_fingerprint(module_path, component.component_id)
    run_id = "ext100_" + time.strftime("%Y%m%d_%H%M%S") + "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", component.component_id)
    outdir = EVAL / "runs" / run_id
    outdir.mkdir(parents=True, exist_ok=False)

    maps = raw_maps()
    docs_by = {}
    state_by = {}
    authorized_ids = {}
    for sample in data["samples"]:
        sid = str(sample["sample_id"])
        rm = maps[sid]
        docs = load_side(sid, "a", rm) + load_side(sid, "b", rm)
        if len({d["source_key"] for d in docs}) != len(docs):
            raise RuntimeError(f"source binding not unique {sid}")
        docs_by[sid] = docs
        authorized_ids[sid] = {str(d["source_key"]) for d in docs}
        state_by[sid] = prepare_component(component, docs)

    ret_rows = []
    cand_selected = {}
    material_authority_regressions = 0
    for sample in data["samples"]:
        sid = str(sample["sample_id"])
        speakers = (sample["conversation"]["speaker_a"], sample["conversation"]["speaker_b"])
        for q in sample["questions"]:
            bid = str(q["blind_id"])
            question = str(q["question"])
            docs = rank_component(component, state_by[sid], docs_by[sid], question, 20, metadata={"speaker_names": speakers})
            ids = [str(d["source_key"]) for d in docs]
            if len(ids) != len(set(ids)) or any(x not in authorized_ids[sid] for x in ids):
                material_authority_regressions += 1
            cand_selected[bid] = ids
            ret_rows.append(
                {
                    "blind_id": bid,
                    "sample_id": sid,
                    "question": question,
                    "selected_source_ids": ids,
                    "authorized_memories": [
                        {
                            "authority": "user_source_history",
                            "timestamp": d.get("timestamp"),
                            "text": d["text"],
                            "source_id": d["source_key"],
                        }
                        for d in docs
                    ],
                }
            )
    if {str(x["blind_id"]) for x in ret_rows} != member_ids:
        raise RuntimeError("candidate retrieval membership drift")

    retrieval = {
        "schema": "xiaoyu-fast-external100-retrieval-v1",
        "input_sha256": sha(INPUT),
        "membership_sha256": sha(MEMBERSHIP),
        "component": fp,
        "context_cap": 20,
        "question_count": len(ret_rows),
        "rows": ret_rows,
    }
    rp = outdir / "retrieval.json"
    rp.write_text(json.dumps(retrieval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (outdir / "RETRIEVAL_SEAL.json").write_text(
        json.dumps({"status": "SEALED_BEFORE_GOLD", "sha256": sha(rp)}, indent=2) + "\n",
        encoding="utf-8",
    )

    oldreq = load_json(OLD_ANSWER_REQUESTS)
    system = oldreq["rows"][0]["messages"][0]["content"]
    cfg = deepseek()
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    workers = max(1, min(8, int(os.environ.get("XIAOYU_FASTLANE_CONCURRENCY", "8"))))

    def answer_one(r):
        raw, u = model_adapter.chat(
            cfg,
            answer_messages(system, r["question"], r["authorized_memories"]),
            max_tokens=96,
            timeout=120,
        )
        return str(parse_json(raw).get("answer") or raw).strip(), u

    baseline_pred_map = {str(x["blind_id"]): str(x["answer"]) for x in base_art["predictions"]}
    changed_retrieval_ids = {
        str(r["blind_id"]) for r in ret_rows
        if [str(x) for x in cand_selected[str(r["blind_id"])]]
        != [str(x) for x in base_art["selected"][str(r["blind_id"])]]
    }
    changed_rows = [r for r in ret_rows if str(r["blind_id"]) in changed_retrieval_ids]
    changed_answer_map = {}
    if changed_rows:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            answer_results = list(ex.map(answer_one, changed_rows))
        for r, (ans, u) in zip(changed_rows, answer_results):
            changed_answer_map[str(r["blind_id"])] = ans
            usage["calls"] += 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[k] += int(u.get(k) or 0)
    cand_pred = []
    for r in ret_rows:
        bid=str(r["blind_id"])
        reused=bid not in changed_retrieval_ids
        ans=baseline_pred_map[bid] if reused else changed_answer_map[bid]
        cand_pred.append({
            "blind_id": bid, "sample_id": r["sample_id"], "answer": ans,
            "reused_baseline_answer": reused,
        })

    pp = outdir / "predictions.json"
    pp.write_text(
        json.dumps(
            {"schema": "xiaoyu-fast-external100-predictions-v1", "rows": cand_pred, "usage": usage},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (outdir / "PREDICTION_SEAL.json").write_text(
        json.dumps(
            {"status": "SEALED_BEFORE_GOLD", "sha256": sha(pp), "retrieval_sha256": sha(rp)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Gold/evidence are loaded only after candidate retrieval + predictions are sealed.
    gold = load_json(GOLD)
    gm = {str(r["blind_id"]): r for r in gold["rows"] if str(r["blind_id"]) in member_ids}
    if set(gm) != member_ids:
        raise RuntimeError("Stage1 gold membership mismatch")

    def judge_predictions(pred_rows):
        judged = []
        jusage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def judge_one(predrow):
            g = gm[predrow["blind_id"]]
            prompt = JUDGE_PROMPT.format(
                question=g["question"], golden_answer=g["gold_answer"], response=predrow["answer"]
            )
            raw, u = model_adapter.chat(
                cfg,
                [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}],
                max_tokens=64,
                timeout=120,
            )
            label = str(parse_json(raw).get("label") or "").upper()
            if label not in {"CORRECT", "WRONG"}:
                raise RuntimeError("invalid judge label")
            return g, label, u

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(judge_one, pred_rows))
        for predrow, (g, label, u) in zip(pred_rows, results):
            judged.append(
                {
                    "blind_id": predrow["blind_id"],
                    "category": str(g["category"]),
                    "answer": predrow["answer"],
                    "gold_answer": g["gold_answer"],
                    "label": label,
                    "correct": label == "CORRECT",
                }
            )
            jusage["calls"] += 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                jusage[k] += int(u.get(k) or 0)
        return judged, jusage

    baseline_judged, baseline_judge_usage = judge_predictions(base_art["predictions"])
    baseline_judged_map = {str(x["blind_id"]): x for x in baseline_judged}
    changed_pred = [x for x in cand_pred if str(x["blind_id"]) in changed_retrieval_ids]
    changed_judged, candidate_judge_usage = judge_predictions(changed_pred) if changed_pred else ([], {"calls":0,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0})
    changed_judged_map = {str(x["blind_id"]): x for x in changed_judged}
    candidate_judged=[]
    for predrow in cand_pred:
        bid=str(predrow["blind_id"])
        if bid in changed_retrieval_ids:
            candidate_judged.append(changed_judged_map[bid])
        else:
            b=dict(baseline_judged_map[bid])
            b["answer"]=predrow["answer"]
            b["reused_baseline_judgement"]=True
            candidate_judged.append(b)

    base_score = summarize_judged(baseline_judged)
    cand_score = summarize_judged(candidate_judged)
    base_ev = evidence_summary(base_art["selected"], member_ids)
    cand_ev = evidence_summary(cand_selected, member_ids)

    delta = {
        "overall_accuracy": cand_score["overall"]["accuracy"] - base_score["overall"]["accuracy"],
        "full_evidence_recall_rate": cand_ev["overall"]["full_evidence_recall_rate"]
        - base_ev["overall"]["full_evidence_recall_rate"],
    }
    pass_stage1 = (
        delta["overall_accuracy"] >= float(rule.get("min_candidate_vs_baseline_accuracy_delta", 0.0))
        and delta["full_evidence_recall_rate"]
        >= float(rule.get("min_candidate_vs_baseline_full_evidence_delta", 0.0))
        and len(changed_retrieval_ids) >= int(rule.get("min_retrieval_changed_questions", 0))
        and material_authority_regressions
        <= int(rule.get("material_authority_regressions_max", 0))
    )

    result = {
        "schema": "xiaoyu-fast-external100-result-v1",
        "status": "PASS_STAGE1" if pass_stage1 else "FAIL_STAGE1",
        "light_audit": str(audit_path),
        "component": fp,
        "baseline_id": base["baseline_id"],
        "baseline_source": base_art["run_dir"],
        "input_sha256": sha(INPUT),
        "membership_sha256": sha(MEMBERSHIP),
        "pass_rule": rule,
        "context_cap": 20,
        "candidate_answer_usage": usage,
        "baseline_judge_usage": baseline_judge_usage,
        "candidate_judge_usage": candidate_judge_usage,
        "baseline_score": base_score,
        "candidate_score": cand_score,
        "baseline_evidence": {"overall": base_ev["overall"], "by_category": base_ev["by_category"]},
        "candidate_evidence": {"overall": cand_ev["overall"], "by_category": cand_ev["by_category"]},
        "delta": delta,
        "material_authority_regressions": material_authority_regressions,
        "retrieval_reuse": {
            "same_as_baseline_questions": len(member_ids)-len(changed_retrieval_ids),
            "changed_questions": len(changed_retrieval_ids),
            "candidate_answer_calls_saved": len(member_ids)-len(changed_retrieval_ids),
            "candidate_judge_calls_saved": len(member_ids)-len(changed_retrieval_ids),
        },
        "stage1_pass": pass_stage1,
        "baseline_promotion": False,
        "no_reselection": True,
        "candidate_prediction_sealed_before_gold": True,
        "baseline_prediction_reused_from_prior_sealed_stage2": True,
    }
    result_path = outdir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gate = {
        "schema": "xiaoyu-fast-external100-stage2-gate-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "verdict": "PASS" if pass_stage1 else "FAIL",
        "component": {"path": str(comp_path), "sha256": expected_comp_sha},
        "source_light_audit": str(audit_path),
        "source_light_audit_sha256": sha(audit_path),
        "stage1_result": str(result_path.relative_to(ROOT)).replace("\\", "/"),
        "stage1_result_sha256": sha(result_path),
        "stage1_input_sha256": sha(INPUT),
        "stage1_membership_sha256": sha(MEMBERSHIP),
        "baseline_id": base["baseline_id"],
        "external_stage1_authorized": True,
        "external200_authorized": bool(pass_stage1),
        "external200_gate": "STAGE1_PASS_REQUIRED",
        "baseline_promotion_authorized": False,
    }
    gate_path = outdir / "STAGE2_GATE.json"
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": result["status"],
                "result": str(result_path),
                "stage2_gate": str(gate_path),
                "baseline_score": base_score,
                "candidate_score": cand_score,
                "baseline_evidence": base_ev["overall"],
                "candidate_evidence": cand_ev["overall"],
                "delta": delta,
                "material_authority_regressions": material_authority_regressions,
                "external200_authorized": bool(pass_stage1),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if pass_stage1 else 3)


if __name__ == "__main__":
    main()
