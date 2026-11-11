# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
DB = GOV / "registry.sqlite3"
OUT = GOV / "PRODUCTIZATION_DEBT_20261101.json"

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--write",action="store_true")
    args=ap.parse_args()
    policy=json.loads((GOV/"policy.json").read_text(encoding="utf-8"))
    effective=float((policy.get("multidimensional_gate_stratification") or {}).get("effective_after_epoch",0) or 0)

    refs=[]
    # Routing/closure evidence is spread across Lead checkpoints and integration
    # records. Scan only small governance-root text records; never recurse into
    # workspaces or large benchmark payloads.
    for pattern in ("*.json","*.md"):
        for path in GOV.glob(pattern):
            if path.name=="PRODUCTIZATION_DEBT_20261101.json":
                continue
            try:
                if path.stat().st_size>2_000_000:
                    continue
                refs.append((path.name,path.read_text(encoding="utf-8",errors="replace")))
            except OSError:
                continue

    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    rows=con.execute("""
        SELECT s.submission_id,s.at AS submitted_at,s.manifest_path,s.evidence_label,
               l.lease_id,l.family,l.lineage,l.capability,l.backlog_id,l.claimed_at,
               r.at AS accepted_at
          FROM submissions s
          JOIN leases l ON l.lease_id=s.lease_id
          JOIN reviews r ON r.submission_id=s.submission_id
         WHERE r.decision='ACCEPT_E1' AND l.role='research_engineer'
         ORDER BY r.at
    """).fetchall()
    items=[]
    for row in rows:
        manifest={}
        try:
            manifest=json.loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
        except Exception:
            pass
        intent=manifest.get("productization_intent")
        hits=[name for name,text in refs if row["submission_id"] in text or row["lease_id"] in text]
        later=con.execute(
            "SELECT lease_id,family,state,backlog_id,claimed_at FROM leases WHERE lineage=? AND claimed_at>? ORDER BY claimed_at LIMIT 8",
            (row["lineage"],row["claimed_at"])).fetchall()
        if hits:
            status="ROUTED_OR_REFERENCED"
        elif isinstance(intent,dict):
            status="INTENT_RECORDED_PENDING_LEAD_DISPOSITION"
        elif float(row["claimed_at"] or 0)>=effective:
            status="POST_POLICY_MISSING_INTENT"
        elif later:
            status="LEGACY_LATER_LINEAGE_WORK_EXISTS"
        else:
            status="LEGACY_UNTRIAGED"
        items.append({
            "submission_id":row["submission_id"],
            "lease_id":row["lease_id"],
            "family":row["family"],
            "lineage":row["lineage"],
            "capability":row["capability"],
            "backlog_id":row["backlog_id"],
            "accepted_at":row["accepted_at"],
            "status":status,
            "productization_intent":intent,
            "routing_references":hits,
            "later_same_lineage":[dict(x) for x in later],
        })
    con.close()
    summary={}
    for x in items:
        summary[x["status"]]=summary.get(x["status"],0)+1
    report={
      "schema":"xiaoyu-productization-debt-v1",
      "generated_at":datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
      "blocking":False,
      "rule":"ACCEPT_E1 accumulation alone is not progress; every material accepted capability needs integration, explicit deferral, research-only rationale, simplification route, or retirement.",
      "summary":summary,
      "items":items,
    }
    if args.write:
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
