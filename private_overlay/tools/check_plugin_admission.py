from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
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


def _manifest(path: Path) -> dict[str, Any]:
    manifest_path = path / "plugin.toml"
    if not manifest_path.is_file():
        raise RuntimeError(f"admitted plugin manifest missing: {manifest_path}")
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot parse plugin manifest {manifest_path}: {exc}") from exc
    plugin = data.get("plugin")
    if not isinstance(plugin, dict):
        raise RuntimeError(f"plugin manifest lacks [plugin]: {manifest_path}")
    return plugin


def _dict_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError(f"malformed {label}")
    return value


def _string_set(value: Any, label: str) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"malformed {label}")
    return set(value)


def _dependency_key(item: dict[str, Any]) -> str:
    try:
        return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"malformed plugin.dependency: {exc}") from exc


def validate_manifest_allowance(
    plugin_id: str,
    manifest: dict[str, Any],
    allowance: dict[str, Any],
) -> None:
    if not isinstance(allowance, dict):
        raise RuntimeError(f"missing reviewed manifest allowance: {plugin_id}")
    for field in ("entry", "type"):
        if manifest.get(field) != allowance.get(field):
            raise RuntimeError(f"{plugin_id} manifest {field} drifted beyond reviewed allowance")

    current_dependencies = {
        _dependency_key(item)
        for item in _dict_list(manifest.get("dependency"), "plugin.dependency")
    }
    allowed_dependencies = {
        _dependency_key(item)
        for item in _dict_list(allowance.get("dependency"), "reviewed plugin.dependency")
    }
    if not current_dependencies <= allowed_dependencies:
        raise RuntimeError(f"{plugin_id} dependency expansion beyond reviewed allowance")

    current_models = manifest.get("models") or {}
    allowed_models = allowance.get("models") or {}
    if not isinstance(current_models, dict) or not isinstance(allowed_models, dict):
        raise RuntimeError(f"malformed plugin.models allowance: {plugin_id}")
    if not set(current_models) <= set(allowed_models):
        raise RuntimeError(f"{plugin_id} model capability expansion beyond reviewed allowance")
    for model_id, model in current_models.items():
        if not isinstance(model, dict) or not isinstance(allowed_models[model_id], dict):
            raise RuntimeError(f"malformed plugin.models.{model_id}: {plugin_id}")
        capabilities = _string_set(
            model.get("capabilities"), f"plugin.models.{model_id}.capabilities"
        )
        allowed = _string_set(
            allowed_models[model_id].get("capabilities"),
            f"reviewed plugin.models.{model_id}.capabilities",
        )
        if not capabilities <= allowed:
            raise RuntimeError(f"{plugin_id} model capability expansion beyond reviewed allowance")

    current_ui = manifest.get("ui") or {}
    allowed_ui = allowance.get("ui") or {}
    if not isinstance(current_ui, dict) or not isinstance(allowed_ui, dict):
        raise RuntimeError(f"malformed plugin.ui allowance: {plugin_id}")
    if current_ui.get("enabled") is True and allowed_ui.get("enabled") is not True:
        raise RuntimeError(f"{plugin_id} UI expansion beyond reviewed allowance")
    surface_kinds = {
        key for key, value in current_ui.items() if isinstance(value, list)
    } | {
        key for key, value in allowed_ui.items() if isinstance(value, list)
    }
    for surface_kind in sorted(surface_kinds):
        current_surfaces = _dict_list(
            current_ui.get(surface_kind), f"plugin.ui.{surface_kind}"
        )
        allowed_surfaces = _dict_list(
            allowed_ui.get(surface_kind), f"reviewed plugin.ui.{surface_kind}"
        )
        allowed_by_identity = {
            (item.get("id"), item.get("entry"), item.get("context")): item
            for item in allowed_surfaces
        }
        for surface in current_surfaces:
            identity = (surface.get("id"), surface.get("entry"), surface.get("context"))
            reviewed = allowed_by_identity.get(identity)
            if reviewed is None:
                raise RuntimeError(f"{plugin_id} UI surface expansion beyond reviewed allowance")
            permissions = _string_set(surface.get("permissions"), "plugin.ui permissions")
            allowed_permissions = _string_set(
                reviewed.get("permissions"), "reviewed plugin.ui permissions"
            )
            if not permissions <= allowed_permissions:
                raise RuntimeError(f"{plugin_id} UI permission expansion beyond reviewed allowance")

    # N.E.K.O declares host-managed actions under [plugin.install.kinds]. Compare
    # the real kind names only when present; do not synthesize private grants.
    current_install = manifest.get("install") or {}
    allowed_install = allowance.get("install") or {}
    if not isinstance(current_install, dict) or not isinstance(allowed_install, dict):
        raise RuntimeError(f"malformed plugin.install allowance: {plugin_id}")
    current_kinds = current_install.get("kinds") or {}
    allowed_kinds = allowed_install.get("kinds") or {}
    if not isinstance(current_kinds, dict) or not isinstance(allowed_kinds, dict):
        raise RuntimeError(f"malformed plugin.install.kinds allowance: {plugin_id}")
    if not set(current_kinds) <= set(allowed_kinds):
        raise RuntimeError(f"{plugin_id} install kind expansion beyond reviewed allowance")


def validate_active_manifests(
    policy: dict[str, Any], active: set[str], neko_root: Path
) -> None:
    entries = policy.get("admitted_autostart_plugins") or {}
    for plugin_id in sorted(active):
        item = entries[plugin_id]
        base = ROOT if item.get("provenance") == "private_reviewed" else neko_root
        plugin = _manifest(base / str(item.get("source") or ""))
        validate_manifest_allowance(plugin_id, plugin, item.get("reviewed_manifest"))


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
    validate_active_manifests(policy, active, neko_root)

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
