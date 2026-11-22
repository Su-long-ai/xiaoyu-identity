from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def active_autostarts(overrides: dict[str, Any]) -> set[str]:
    active: set[str] = set()
    for plugin_id, raw in overrides.items():
        if not isinstance(raw, dict):
            continue
        if raw.get("enabled") is True and raw.get("auto_start") is True:
            active.add(str(plugin_id))
    return active


def validate_state(
    policy: dict[str, Any],
    overrides: dict[str, Any],
    pending: dict[str, Any] | None = None,
) -> set[str]:
    admitted = set((policy.get("admitted_autostart_plugins") or {}).keys())
    active = active_autostarts(overrides)
    unknown = sorted(active - admitted)
    if unknown:
        raise RuntimeError(
            "unreviewed runtime auto-start plugin(s): " + ", ".join(unknown)
        )

    pending_ids = {
        str(item)
        for item in ((pending or {}).get("pending") or [])
        if isinstance(item, str)
    }
    wrongly_active_pending = sorted(active & pending_ids)
    if wrongly_active_pending:
        raise RuntimeError(
            "pending plugin must not be active auto-start: "
            + ", ".join(wrongly_active_pending)
        )
    return active


def _git_head(path: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        raise RuntimeError(f"cannot read git HEAD for {path}: {exc}") from exc
    return proc.stdout.strip()


def validate_provenance(policy: dict[str, Any], neko_root: Path) -> None:
    entries = policy.get("admitted_autostart_plugins") or {}
    reviews = _load(ROOT / "governance" / "reuse_reviews.json")
    review_ids = {
        str(item.get("id"))
        for item in reviews.get("reviews", [])
        if isinstance(item, dict) and item.get("status") == "approved"
    }

    for plugin_id, item in entries.items():
        provenance = item.get("provenance")
        source = str(item.get("source") or "")
        if provenance == "neko_native":
            path = neko_root / source
            if not path.is_dir():
                raise RuntimeError(f"native admitted plugin missing: {plugin_id}: {path}")
        elif provenance == "private_reviewed":
            path = ROOT / source
            if not path.is_dir():
                raise RuntimeError(f"private admitted plugin missing: {plugin_id}: {path}")
            review_id = str(item.get("reuse_review_id") or "")
            if review_id not in review_ids:
                raise RuntimeError(
                    f"private admitted plugin lacks approved reuse review: {plugin_id}: {review_id}"
                )
        elif provenance == "pinned_external":
            path = neko_root / source
            if not path.is_dir():
                raise RuntimeError(f"pinned external plugin missing: {plugin_id}: {path}")
            lock_path = ROOT / str(item.get("lock") or "")
            lock = _load(lock_path)
            expected = str(item.get("tested_commit") or "")
            if lock.get("tested_commit") != expected:
                raise RuntimeError(
                    f"plugin admission pin disagrees with lock: {plugin_id}"
                )
            actual = _git_head(path)
            if actual != expected:
                raise RuntimeError(
                    f"pinned plugin checkout drifted: {plugin_id}: {actual} != {expected}"
                )
        else:
            raise RuntimeError(f"unknown plugin provenance: {plugin_id}: {provenance}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", required=True)
    parser.add_argument("--storage-root", required=True)
    args = parser.parse_args()

    neko_root = Path(args.neko_root).resolve()
    storage_root = Path(args.storage_root).resolve()
    policy = _load(ROOT / "governance" / "plugin_admission_v1.json")

    if policy.get("policy_id") != "XIAOYU_PLUGIN_AUTOSTART_ADMISSION_V1":
        raise SystemExit("plugin admission policy id changed or missing")
    sec = policy.get("security_model") or {}
    if sec.get("admission_only_not_sandbox") is not True:
        raise SystemExit("plugin admission must not claim to be a sandbox")
    if sec.get("capability_grants_are_not_malicious_plugin_isolation") is not True:
        raise SystemExit("plugin capability-grant limitation must remain explicit")
    if sec.get("no_private_permission_store") is not True:
        raise SystemExit("XiaoYu must not create a second permission store")
    if sec.get("no_private_plugin_host") is not True:
        raise SystemExit("XiaoYu must not create a second plugin host")

    validate_provenance(policy, neko_root)

    config_root = storage_root / "config"
    overrides = _load(config_root / "plugin_runtime_overrides.json")
    pending_path = config_root / "plugin_autostart_pending.json"
    pending = _load(pending_path) if pending_path.is_file() else {"pending": []}
    active = validate_state(policy, overrides, pending)

    print(
        "PASS: plugin autostart admission "
        + f"({len(active)} active reviewed plugin(s): {', '.join(sorted(active))})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
