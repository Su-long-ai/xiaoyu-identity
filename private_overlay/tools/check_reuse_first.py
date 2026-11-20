from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "governance" / "reuse_reviews.json"
SERIES = ROOT / "patches" / "series.json"
PLUGINS = ROOT / "plugins" / "manifest.json"

ALLOWED_DECISIONS = {"reuse_native", "reuse_external", "thin_adapter", "self_implement"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-id", help="Check whether one proposed runtime customization is already reuse-admitted")
    args = parser.parse_args()

    errors: list[str] = []
    data = load(REVIEWS)
    require(data.get("schema_version") == 1, "reuse review schema_version must be 1", errors)

    items = data.get("reviews")
    require(isinstance(items, list), "reuse reviews must be a list", errors)
    items = items if isinstance(items, list) else []
    by_id: dict[str, dict] = {}
    for item in items:
        rid = str(item.get("id") or "")
        require(bool(rid), "reuse review missing id", errors)
        require(rid not in by_id, f"duplicate reuse review id: {rid}", errors)
        by_id[rid] = item
        require(item.get("status") == "approved", f"reuse review not approved: {rid}", errors)
        require(str(item.get("reviewed_at") or "").strip() != "", f"reuse review missing reviewed_at: {rid}", errors)
        require(item.get("decision") in ALLOWED_DECISIONS, f"invalid reuse decision: {rid}", errors)
        candidates = item.get("candidates")
        require(isinstance(candidates, list) and len(candidates) > 0, f"reuse review has no native/external candidates: {rid}", errors)
        if isinstance(candidates, list):
            for index, candidate in enumerate(candidates):
                require(bool(str(candidate.get("name") or "").strip()), f"candidate {index} missing name: {rid}", errors)
                require(bool(str(candidate.get("type") or "").strip()), f"candidate {index} missing type: {rid}", errors)
                require(bool(str(candidate.get("outcome") or "").strip()), f"candidate {index} missing outcome: {rid}", errors)
                require(bool(str(candidate.get("evidence") or "").strip()), f"candidate {index} missing evidence: {rid}", errors)
        if item.get("decision") in {"thin_adapter", "self_implement"}:
            require(bool(str(item.get("why_reuse_insufficient") or "").strip()), f"custom implementation lacks reuse-gap rationale: {rid}", errors)
            evidence = str(item.get("acceptance_evidence") or "").strip()
            require(bool(evidence), f"custom implementation lacks acceptance evidence: {rid}", errors)
            if evidence and not evidence.startswith(("http://", "https://")):
                require((ROOT / evidence).is_file(), f"acceptance evidence missing for {rid}: {evidence}", errors)

    series = load(SERIES)
    managed = {str(item.get("file") or "") for item in series.get("patches", [])}
    disk_patches = {p.name for p in (ROOT / "patches").glob("*.patch")}
    for filename in sorted(managed):
        require(f"patch:{filename}" in by_id, f"managed core patch has no approved reuse review: {filename}", errors)
    for filename in sorted(disk_patches - managed):
        errors.append(f"unmanaged core patch exists before reuse admission/series registration: {filename}")

    manifest = load(PLUGINS)
    for item in manifest.get("allowed_private_runtime_plugins", []):
        pid = str(item.get("id") or "")
        require(f"plugin:{pid}" in by_id, f"private runtime plugin has no approved reuse review: {pid}", errors)

    if args.proposal_id:
        review = by_id.get(args.proposal_id)
        require(review is not None, f"proposal is not reuse-admitted: {args.proposal_id}", errors)
        if review is not None:
            require(review.get("status") == "approved", f"proposal review is not approved: {args.proposal_id}", errors)

    if errors:
        for error in errors:
            print(f"BLOCK_REUSE_FIRST: {error}")
        return 2

    print(f"PASS: reuse-first gate covers {len(managed)} managed patches and {len(manifest.get('allowed_private_runtime_plugins', []))} private runtime plugin(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
