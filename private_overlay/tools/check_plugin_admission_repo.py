#!/usr/bin/env python3
"""Repository-only plugin admission gate for GitHub/online development.

This gate intentionally does not pretend to validate the installed N.E.K.O
runtime. It verifies everything the XiaoYu repository itself can author:
reviewed capability floors, private-plugin manifest drift, approved reuse
review, and pinned external lock consistency. The normal local
check_plugin_admission.py remains the full installed-runtime gate.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from check_plugin_admission import (
    ROOT,
    _git_head,
    _load,
    _manifest,
    validate_manifest_allowance,
)


def _validate_reviewed_allowance(plugin_id: str, item: dict[str, Any]) -> None:
    allowance = item.get("reviewed_manifest")
    if not isinstance(allowance, dict):
        raise RuntimeError(f"missing reviewed manifest allowance: {plugin_id}")
    entry = allowance.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        raise RuntimeError(f"reviewed manifest entry missing: {plugin_id}")
    # Exercise the common validator against the allowance itself. This catches
    # malformed dependency/model/UI/install shapes without inventing a second
    # permission vocabulary.
    validate_manifest_allowance(plugin_id, allowance, allowance)


def _validate_checked_out_manifest(
    plugin_id: str,
    item: dict[str, Any],
    neko_root: Path,
) -> None:
    source = neko_root / str(item.get("source") or "")
    if not source.is_dir():
        raise RuntimeError(f"checked-out admitted plugin missing: {plugin_id}: {source}")
    manifest = _manifest(source)
    validate_manifest_allowance(
        plugin_id,
        manifest,
        item.get("reviewed_manifest"),
    )

    if item.get("provenance") == "pinned_external":
        expected = str(item.get("tested_commit") or "")
        actual = _git_head(source)
        if actual != expected:
            raise RuntimeError(
                f"pinned plugin checkout drifted: {plugin_id}: {actual} != {expected}"
            )


def validate_repo(
    policy: dict[str, Any],
    *,
    neko_root: Path | None = None,
) -> list[str]:
    if policy.get("policy_id") != "XIAOYU_PLUGIN_AUTOSTART_ADMISSION_V1":
        raise RuntimeError("plugin admission policy id changed or missing")

    security = policy.get("security_model") or {}
    if security.get("admission_only_not_sandbox") is not True:
        raise RuntimeError("plugin admission must not claim to be a sandbox")
    if security.get("capability_grants_are_not_malicious_plugin_isolation") is not True:
        raise RuntimeError("native capability-grant limitation must remain explicit")
    if security.get("no_private_permission_store") is not True:
        raise RuntimeError("XiaoYu must not create a second permission store")
    if security.get("no_private_plugin_host") is not True:
        raise RuntimeError("XiaoYu must not create a second plugin host")

    entries = policy.get("admitted_autostart_plugins")
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError("admitted autostart plugin inventory missing")

    reviews = _load(ROOT / "governance" / "reuse_reviews.json")
    review_ids = {
        str(item.get("id"))
        for item in reviews.get("reviews", [])
        if isinstance(item, dict) and item.get("status") == "approved"
    }

    checked: list[str] = []
    for plugin_id, raw in sorted(entries.items()):
        if not isinstance(raw, dict):
            raise RuntimeError(f"malformed admitted plugin policy: {plugin_id}")
        _validate_reviewed_allowance(plugin_id, raw)

        provenance = raw.get("provenance")
        if provenance == "private_reviewed":
            source = ROOT / str(raw.get("source") or "")
            manifest = _manifest(source)
            validate_manifest_allowance(
                plugin_id,
                manifest,
                raw.get("reviewed_manifest"),
            )
            review_id = str(raw.get("reuse_review_id") or "")
            if review_id not in review_ids:
                raise RuntimeError(
                    f"private admitted plugin lacks approved reuse review: "
                    f"{plugin_id}: {review_id}"
                )
        elif provenance == "pinned_external":
            lock_path = ROOT / str(raw.get("lock") or "")
            lock = _load(lock_path)
            expected = str(raw.get("tested_commit") or "")
            if not expected or lock.get("tested_commit") != expected:
                raise RuntimeError(
                    f"pinned external admission disagrees with lock: {plugin_id}"
                )
            if neko_root is not None:
                _validate_checked_out_manifest(plugin_id, raw, neko_root)
        elif provenance == "neko_native":
            # The early repository-only invocation intentionally runs before a
            # N.E.K.O checkout exists. A later invocation passes --neko-root
            # and validates the real pinned native manifest against the same
            # reviewed allowance without inventing another permission model.
            if neko_root is not None:
                _validate_checked_out_manifest(plugin_id, raw, neko_root)
        else:
            raise RuntimeError(f"unknown plugin provenance: {plugin_id}: {provenance}")
        checked.append(plugin_id)

    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", type=Path)
    args = parser.parse_args()

    policy = _load(ROOT / "governance" / "plugin_admission_v1.json")
    neko_root = args.neko_root.resolve() if args.neko_root is not None else None
    checked = validate_repo(policy, neko_root=neko_root)
    print(
        "PASS: repository-only plugin admission "
        + ("with checked-out manifests " if neko_root is not None else "")
        + f"({len(checked)} reviewed plugin(s): {', '.join(checked)})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
