from __future__ import annotations
import argparse, json, re, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
DB = GOV / "registry.sqlite3"
OUT = GOV / "HISTORICAL_RESCUE_QUEUE_20261101.json"

BROAD_PHRASES = (
    "does not reject", "does not falsify", "not a revocation",
    "broader", "exact candidate", "exact hypothesis",
    "not the impossibility", "not every future", "does not imply",
    "semantically correct", "exact implementation", "exact mechanism",
)
PERF_PHRASES = ("latency", "performance", "cost gate", "steady-recall cost", "overhead")
ADMIN_PHRASES = ("not tested", "provider_calls=0", "provider calls=0", "registration", "scope", "missing", "dependency")
MANUAL_CONSUMED = {
    "identity.cross_model.renderer_invariance": {
        "status": "RECOVERED_CROSS_LINEAGE",
        "successor": "identity.cross_model.compact_semantic_contract",
        "note": "A later compact cross-model semantic-envelope successor is active; do not duplicate-rescue the older static worst-case packing mechanism."
    },
    "portfolio.mainline.query_conditioned_state": {
        "status": "RECOVERED_SAME_PROGRAM",
        "successor": "MAIN36 typed_history_exact_anchor_index and later query-conditioned reconstruction work",
        "note": "Historical reconstruction has already been re-opened through materially different bounded/indexed successors."
    },
    "memory.capability.learned_attribution_factorization": {
        "status": "CONSUMED_BY_RC8_B2",
        "successor": "RC8-B2 / RC8M2 safety-boundary-stratified learned proposal",
        "note": "EXP08 remains negative as an exact hypothesis; its factorization gains are already explicitly consumed by RC-v8 B2."
    },
}

def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", (s or "").lower()))

def jaccard(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    leases = list(conn.execute("select lease_id,family,lineage,capability,hypothesis,state,workspace,claimed_at,backlog_id from leases"))
    by_ws = {Path(r["workspace"]).name: r for r in leases if r["workspace"]}
    rows = []
    total_negative = 0
    positive_delta_negative = 0
    explicit_broad = 0

    for rp in GOV.glob("workspaces/*/result.json"):
        try:
            d = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        outcome = str(d.get("scientific_outcome") or "")
        label = str(d.get("evidence_label") or "")
        if outcome != "NEGATIVE" and label != "NONPASS":
            continue
        total_negative += 1
        delta = d.get("delta")
        pos_delta = isinstance(delta, (int, float)) and delta > 0
        if pos_delta:
            positive_delta_negative += 1
        text = (str(d.get("limitations") or "") + " " + str(d.get("hypothesis") or "")).lower()
        broad = [p for p in BROAD_PHRASES if p in text]
        if broad:
            explicit_broad += 1

        ws = rp.parent.name
        lease = by_ws.get(ws)
        lineage = str(lease["lineage"] if lease else "")
        family = str(lease["family"] if lease else "")
        capability = str(lease["capability"] if lease else "")
        claimed = float(lease["claimed_at"] if lease else 0.0)
        hypothesis = str(d.get("hypothesis") or (lease["hypothesis"] if lease else ""))
        limitations = str(d.get("limitations") or "")

        newer_same = [
            r for r in leases
            if lineage and r["lineage"] == lineage and float(r["claimed_at"] or 0) > claimed
        ]
        newer_same.sort(key=lambda r: float(r["claimed_at"] or 0))

        later_similar = []
        for r in leases:
            if float(r["claimed_at"] or 0) <= claimed or (capability and r["capability"] != capability):
                continue
            sim = jaccard(hypothesis, str(r["hypothesis"] or ""))
            if sim >= 0.28:
                later_similar.append((sim, r))
        later_similar.sort(key=lambda x: x[0], reverse=True)

        score = 0
        reasons = []
        if pos_delta:
            score += 3
            reasons.append("negative_result_with_positive_measured_delta")
        if broad:
            score += 3
            reasons.append("result_text_explicitly_limits_falsification_scope")
        if any(p in text for p in PERF_PHRASES) and pos_delta:
            score += 1
            reasons.append("functional_gain_blocked_by_engineering_gate")
        if newer_same:
            score -= 4
            reasons.append("later_same_lineage_work_exists")
        if later_similar and later_similar[0][0] >= 0.45:
            score -= 2
            reasons.append("high_similarity_later_work_exists")

        manual = MANUAL_CONSUMED.get(lineage)
        if manual:
            status = manual["status"]
        elif newer_same:
            status = "RECOVERED_OR_SUPERSEDED_SAME_LINEAGE"
        elif later_similar and later_similar[0][0] >= 0.45:
            status = "LIKELY_RECOVERED_CROSS_LINEAGE_REVIEW"
        elif score >= 5:
            status = "PENDING_RESCUE_REVIEW"
        elif score >= 3:
            status = "LOW_PRIORITY_RESCUE_REVIEW"
        else:
            status = "ARCHIVE_NEGATIVE"

        rows.append({
            "workspace": ws,
            "lease_id": lease["lease_id"] if lease else None,
            "family": family,
            "lineage": lineage,
            "capability": capability,
            "scientific_outcome": outcome or None,
            "evidence_label": label or None,
            "promotion_evidence_status": d.get("promotion_evidence_status"),
            "delta": delta,
            "status": status,
            "rescue_score": score,
            "reasons": reasons,
            "broad_scope_phrases": broad,
            "hypothesis": hypothesis,
            "limitations": limitations,
            "later_same_lineage": [
                {"lease_id": r["lease_id"], "family": r["family"], "state": r["state"], "backlog_id": r["backlog_id"]}
                for r in newer_same[-6:]
            ],
            "possible_later_cross_lineage": [
                {"similarity": round(sim, 4), "lease_id": r["lease_id"], "family": r["family"], "lineage": r["lineage"], "state": r["state"]}
                for sim, r in later_similar[:3]
            ],
            "manual_routing": manual,
        })

    rows.sort(key=lambda r: (-r["rescue_score"], -(r["delta"] if isinstance(r["delta"], (int,float)) else -999), r["workspace"]))
    pending = [r for r in rows if r["status"] == "PENDING_RESCUE_REVIEW"]
    low = [r for r in rows if r["status"] == "LOW_PRIORITY_RESCUE_REVIEW"]
    recovered = [r for r in rows if r["status"].startswith("RECOVERED") or r["status"].startswith("CONSUMED") or r["status"].startswith("LIKELY_RECOVERED")]

    report = {
        "schema": "xiaoyu-historical-rescue-queue-v1",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "policy": "governance/HISTORICAL_RESCUE_POLICY_20261101.json",
        "historical_results_are_immutable": True,
        "rc_v8_scope_expansion": False,
        "default_destination": "RC-v8.1_or_RC-v9",
        "summary": {
            "negative_or_nonpass_total": total_negative,
            "positive_delta_despite_negative": positive_delta_negative,
            "explicit_scope_limit_text": explicit_broad,
            "pending_rescue_review": len(pending),
            "low_priority_rescue_review": len(low),
            "already_recovered_or_likely_consumed": len(recovered),
        },
        "queue": rows,
    }
    if args.write:
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("TOP_PENDING")
    for x in pending[:12]:
        print(json.dumps({k:x[k] for k in ("workspace","family","lineage","capability","delta","rescue_score","reasons")}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
