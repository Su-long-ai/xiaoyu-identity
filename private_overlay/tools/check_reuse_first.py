from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "governance" / "reuse_reviews.json"
SERIES = ROOT / "patches" / "series.json"
PLUGINS = ROOT / "plugins" / "manifest.json"
CANDIDATES = ROOT / "candidates"

ALLOWED_DECISIONS = {"reuse_native", "reuse_external", "thin_adapter", "self_implement"}
ALLOWED_ARTIFACT_KINDS = {
    "external_patch",
    "runtime_adapter",
    "state_store",
    "router",
    "daemon",
}
RUNTIME_SOURCE_EXTENSIONS = {".py", ".ps1", ".js", ".cjs", ".mjs", ".ts", ".tsx"}
NON_RUNTIME_SCAN_ROOTS = {
    "candidates",
    "evals",
    "governance",
    "identity",
    "migration",
    "patches",
    "plugins",
    "release",
    "tests",
}


HIERARCHY_POLICY_ID = "HIERARCHICAL_REUSE_V1"
HIERARCHY_LAYERS = (
    "L0_authority",
    "L1_neko_current_pin",
    "L2_neko_upstream_extensions",
    "L3_existing_pinned_external",
    "L4_broader_external_ecosystem",
    "L5_thin_integration",
    "L6_private_implementation",
)
HIERARCHY_LAYER_STATUSES = {"checked", "not_applicable"}
HIERARCHY_DISCOVERY_LAYERS = HIERARCHY_LAYERS[:5]

HIERARCHY_LEGACY_REVIEW_IDS = frozenset({
    "patch:0001-proactive-autostart-idle-gate.patch",
    "patch:0002-full-chat-native-voice-entry.patch",
    "patch:0003-qwen38-server-vad-reliability.patch",
    "patch:0004-native-ingress-activity-before-backpressure.patch",
    "patch:0005-latest-character-switch-intent-replay.patch",
    "patch:0006-private-speech-output-gate.patch",
    "patch:0007-private-first-round-tool-route.patch",
    "plugin:xiaoyu_interaction_policy",
    "patch:0008-qwen-clone-provider-routing.patch",
    "patch:0009-proactive-interruptibility-gate.patch",
    "patch:0010-startup-event-loop-responsiveness.patch",
    "upstream:neko-6fccfb72",
    "plugin:xiaoyu_interaction_policy-model-slot",
    "upstream:neko-e4f87d32",
    "plugin:xiaoyu_interaction_policy-store",
    "upstream:neko-1e8ff0d0",
    "startup:native-plugin-runtime-reconcile",
    "upstream:neko-99b479a0",
    "runtime:plugin-crash-recovery",
    "upstream:neko-c3fc33ff",
})


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)



def _local_or_url_evidence_exists(raw: str) -> bool:
    value = raw.strip()
    if not value:
        return False
    if value.startswith(("http://", "https://")):
        return True
    return (ROOT / value).is_file()


def validate_hierarchy_policy(data: dict, errors: list[str]) -> str:
    policy = data.get("hierarchy_policy")
    require(
        isinstance(policy, dict),
        "reuse reviews missing hierarchy_policy",
        errors,
    )
    if not isinstance(policy, dict):
        return ""

    require(
        policy.get("id") == HIERARCHY_POLICY_ID,
        f"hierarchy policy id must be {HIERARCHY_POLICY_ID}",
        errors,
    )
    require(
        policy.get("layer_order") == list(HIERARCHY_LAYERS),
        "hierarchy policy layer_order must match the frozen reuse hierarchy",
        errors,
    )
    legacy_review_ids = policy.get("legacy_review_ids")
    require(
        isinstance(legacy_review_ids, list),
        "hierarchy policy legacy_review_ids must be a list",
        errors,
    )
    if isinstance(legacy_review_ids, list):
        require(
            set(legacy_review_ids) == set(HIERARCHY_LEGACY_REVIEW_IDS),
            "hierarchy policy legacy_review_ids must match the frozen rollout set",
            errors,
        )
    cutoff = str(policy.get("enforce_reviewed_at_or_after") or "").strip()
    require(
        bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff)),
        "hierarchy policy enforcement cutoff must be YYYY-MM-DD",
        errors,
    )
    return cutoff


def validate_search_layers(
    item: dict,
    cutoff: str,
    errors: list[str],
) -> None:
    reviewed_at = str(item.get("reviewed_at") or "").strip()
    rid = str(item.get("id") or "")
    if rid in HIERARCHY_LEGACY_REVIEW_IDS:
        require(
            bool(reviewed_at) and bool(cutoff) and reviewed_at < cutoff,
            f"legacy hierarchy review must remain before rollout cutoff: {rid}",
            errors,
        )
        return

    require(
        bool(reviewed_at) and bool(cutoff) and reviewed_at >= cutoff,
        f"non-legacy review cannot predate hierarchy rollout: {rid}",
        errors,
    )
    layers = item.get("search_layers")
    require(
        isinstance(layers, dict),
        f"hierarchical reuse review missing search_layers: {rid}",
        errors,
    )
    if not isinstance(layers, dict):
        return

    expected = set(HIERARCHY_LAYERS)
    actual = set(layers)
    for missing in sorted(expected - actual):
        errors.append(f"hierarchical reuse layer missing {missing}: {rid}")
    for extra in sorted(actual - expected):
        errors.append(f"unknown hierarchical reuse layer {extra}: {rid}")

    def checked(layer_name: str) -> bool:
        entry = layers.get(layer_name)
        return isinstance(entry, dict) and entry.get("status") == "checked"

    for layer_name in HIERARCHY_LAYERS:
        entry = layers.get(layer_name)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "")
        require(
            status in HIERARCHY_LAYER_STATUSES,
            f"invalid hierarchy status for {layer_name}: {rid}",
            errors,
        )
        if status == "checked":
            outcome = str(entry.get("outcome") or "").strip()
            evidence = str(entry.get("evidence") or "").strip()
            require(
                bool(outcome),
                f"checked hierarchy layer missing outcome {layer_name}: {rid}",
                errors,
            )
            require(
                bool(evidence),
                f"checked hierarchy layer missing evidence {layer_name}: {rid}",
                errors,
            )
            if evidence:
                require(
                    _local_or_url_evidence_exists(evidence),
                    f"hierarchy evidence missing for {layer_name}: {rid}: {evidence}",
                    errors,
                )
        elif status == "not_applicable":
            rationale = str(entry.get("rationale") or "").strip()
            require(
                len(rationale) >= 20,
                f"not_applicable hierarchy layer needs concrete rationale {layer_name}: {rid}",
                errors,
            )

    require(
        checked("L0_authority"),
        f"hierarchical reuse must check authority ownership first: {rid}",
        errors,
    )
    discovery_checked = sum(1 for layer in HIERARCHY_DISCOVERY_LAYERS if checked(layer))
    require(
        discovery_checked >= 2,
        f"hierarchical reuse is too local; fewer than two discovery layers were checked: {rid}",
        errors,
    )

    decision = item.get("decision")
    if decision in {"thin_adapter", "self_implement"}:
        require(
            any(
                checked(layer)
                for layer in (
                    "L2_neko_upstream_extensions",
                    "L3_existing_pinned_external",
                    "L4_broader_external_ecosystem",
                )
            ),
            (
                "custom implementation search stayed inside the local component; "
                f"check upstream/extensions, pinned external, or broader ecosystem: {rid}"
            ),
            errors,
        )
    if decision == "reuse_native":
        require(
            checked("L1_neko_current_pin") or checked("L2_neko_upstream_extensions"),
            f"reuse_native must check N.E.K.O current pin or upstream/extensions: {rid}",
            errors,
        )
    elif decision == "reuse_external":
        require(
            checked("L3_existing_pinned_external")
            or checked("L4_broader_external_ecosystem"),
            f"reuse_external must check a pinned or broader external layer: {rid}",
            errors,
        )
    elif decision == "thin_adapter":
        require(
            checked("L5_thin_integration"),
            f"thin_adapter must check the thin-integration layer: {rid}",
            errors,
        )
    elif decision == "self_implement":
        require(
            checked("L6_private_implementation"),
            f"self_implement must check the private-implementation layer: {rid}",
            errors,
        )


def _normalize_artifact_path(raw: str) -> str | None:
    text = raw.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or ".." in Path(text).parts:
        return None
    return text


def collect_artifact_claims(
    items: list[dict], errors: list[str]
) -> dict[str, tuple[str, str]]:
    claims: dict[str, tuple[str, str]] = {}
    for item in items:
        rid = str(item.get("id") or "")
        artifacts = item.get("artifacts", [])
        require(
            isinstance(artifacts, list),
            f"reuse review artifacts must be a list: {rid}",
            errors,
        )
        if not isinstance(artifacts, list):
            continue
        for index, artifact in enumerate(artifacts):
            require(
                isinstance(artifact, dict),
                f"artifact {index} must be an object: {rid}",
                errors,
            )
            if not isinstance(artifact, dict):
                continue
            relpath = _normalize_artifact_path(str(artifact.get("path") or ""))
            kind = str(artifact.get("kind") or "")
            retirement = str(artifact.get("retirement_condition") or "").strip()
            require(
                relpath is not None,
                f"artifact {index} has invalid path: {rid}",
                errors,
            )
            require(
                kind in ALLOWED_ARTIFACT_KINDS,
                f"artifact {index} has invalid kind: {rid}",
                errors,
            )
            require(
                bool(retirement),
                f"artifact {index} missing retirement_condition: {rid}",
                errors,
            )
            if relpath is None or kind not in ALLOWED_ARTIFACT_KINDS:
                continue
            require(
                relpath not in claims,
                f"artifact claimed by multiple reuse reviews: {relpath}",
                errors,
            )
            claims.setdefault(relpath, (rid, kind))
    return claims


def classify_runtime_artifact(path: Path, root: Path) -> str | None:
    if path.suffix.lower() not in RUNTIME_SOURCE_EXTENSIONS:
        return None
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if not rel.parts or rel.parts[0].lower() in NON_RUNTIME_SCAN_ROOTS:
        return None

    directory_kinds = {
        "adapters": "runtime_adapter",
        "runtime_adapters": "runtime_adapter",
        "state_stores": "state_store",
        "stores": "state_store",
        "routers": "router",
        "daemons": "daemon",
    }
    for part in (part.lower() for part in rel.parts[:-1]):
        kind = directory_kinds.get(part)
        if kind:
            return kind

    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", path.stem.lower())
        if token
    }
    if "adapter" in tokens:
        return "runtime_adapter"
    if "router" in tokens:
        return "router"
    if "daemon" in tokens:
        return "daemon"
    if "store" in tokens:
        return "state_store"
    return None


def require_artifact_claim(
    relpath: str,
    expected_kind: str,
    claims: dict[str, tuple[str, str]],
    errors: list[str],
) -> None:
    claim = claims.get(relpath)
    require(
        claim is not None,
        f"{expected_kind} has no approved reuse artifact claim: {relpath}",
        errors,
    )
    if claim is not None:
        _rid, actual_kind = claim
        require(
            actual_kind == expected_kind,
            (
                f"reuse artifact kind mismatch for {relpath}: "
                f"expected {expected_kind}, got {actual_kind}"
            ),
            errors,
        )


def check_additional_artifacts(
    root: Path,
    by_id: dict[str, dict],
    claims: dict[str, tuple[str, str]],
    errors: list[str],
) -> tuple[int, int, int]:
    external_patch_count = 0
    plugin_dir_count = 0
    runtime_artifact_count = 0

    for path in sorted(root.rglob("*.patch")):
        relpath = path.relative_to(root).as_posix()
        if relpath.startswith("patches/") or relpath.startswith("candidates/"):
            continue
        external_patch_count += 1
        require_artifact_claim(relpath, "external_patch", claims, errors)

    plugins_root = root / "plugins"
    if plugins_root.is_dir():
        for plugin_toml in sorted(plugins_root.glob("*/plugin.toml")):
            plugin_dir_count += 1
            pid = plugin_toml.parent.name
            require(
                f"plugin:{pid}" in by_id,
                f"private plugin directory has no approved reuse review: {pid}",
                errors,
            )

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        kind = classify_runtime_artifact(path, root)
        if kind is None:
            continue
        runtime_artifact_count += 1
        relpath = path.relative_to(root).as_posix()
        require_artifact_claim(relpath, kind, claims, errors)

    return external_patch_count, plugin_dir_count, runtime_artifact_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-id", help="Check whether one proposed runtime customization is already reuse-admitted")
    args = parser.parse_args()

    errors: list[str] = []
    data = load(REVIEWS)
    require(data.get("schema_version") == 1, "reuse review schema_version must be 1", errors)

    hierarchy_cutoff = validate_hierarchy_policy(data, errors)

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
        validate_search_layers(item, hierarchy_cutoff, errors)
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

    claims = collect_artifact_claims(items, errors)

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

    candidate_patches = []
    if CANDIDATES.is_dir():
        candidate_patches = sorted(
            path.relative_to(CANDIDATES).as_posix()
            for path in CANDIDATES.rglob("*.patch")
            if path.is_file()
        )
    for relpath in candidate_patches:
        review_id = f"candidate:{relpath}"
        require(
            review_id in by_id,
            f"candidate core patch has no approved reuse review: {relpath}",
            errors,
        )

    external_patches, private_plugins, runtime_artifacts = check_additional_artifacts(
        ROOT, by_id, claims, errors
    )

    if args.proposal_id:
        review = by_id.get(args.proposal_id)
        require(review is not None, f"proposal is not reuse-admitted: {args.proposal_id}", errors)
        if review is not None:
            require(review.get("status") == "approved", f"proposal review is not approved: {args.proposal_id}", errors)

    if errors:
        for error in errors:
            print(f"BLOCK_REUSE_FIRST: {error}")
        return 2

    print(
        "PASS: reuse-first gate covers "
        f"{len(managed)} managed patches, "
        f"{len(candidate_patches)} candidate patch(es), "
        f"{external_patches} external patch(es), "
        f"{private_plugins} private plugin directorie(s), "
        f"{runtime_artifacts} adapter/store/router/daemon artifact(s), and "
        f"{len(manifest.get('allowed_private_runtime_plugins', []))} admitted runtime plugin(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
