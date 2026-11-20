"""Ensure XiaoYu's private plugin is installed through N.E.K.O's native package workflow.

The executable plugin tree remains owned by N.E.K.O. Persistent plugin state stays
under the normal plugin state root. This helper never copies plugin code directly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tomllib
from pathlib import Path


PLUGIN_ID = "xiaoyu_interaction_policy"
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def _configure_environment(neko_root: Path, storage_root: Path) -> None:
    neko_root = neko_root.resolve()
    storage_root = storage_root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(storage_root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(storage_root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(storage_root / ".runtime")
    if str(neko_root) not in sys.path:
        sys.path.insert(0, str(neko_root))


def _manifest(path: Path) -> dict:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    plugin = data.get("plugin")
    if not isinstance(plugin, dict):
        raise RuntimeError(f"missing [plugin] table: {path}")
    return plugin


def _source_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if any(part in IGNORED_PARTS for part in rel.parts):
            continue
        if path.suffix == ".pyc":
            continue
        files.append(rel)
    return sorted(files, key=lambda p: p.as_posix())


def _migrate_known_v1_owner_state(
    storage_root: Path,
    *,
    from_version: str,
    target_version: str,
) -> bool:
    """Preserve this installation's known no-speech intent across v1 -> v2.

    The historical v1 schema only stored proactive quiet. This private
    installation is known to have entered quiet via the owner's explicit
    no-speech instruction. Scope the migration tightly to the 0.1.3 -> 0.2.0
    transition and the exact quiet:user state; ambiguous legacy states keep the
    conservative speech_muted=False default.
    """
    if from_version != "0.1.3" or target_version != "0.2.0":
        return False
    path = storage_root / "plugins" / PLUGIN_ID / "data" / "state.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(raw, dict):
        return False
    if raw.get("version") != 1 or not bool(raw.get("quiet")):
        return False
    if "speech_muted" in raw or str(raw.get("last_action") or "") != "quiet:user":
        return False

    raw["speech_muted"] = True
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return True


def _installed_matches_source(source: Path, installed: Path) -> tuple[bool, str]:
    if not installed.is_dir():
        return False, "not_installed"
    source_manifest = _manifest(source / "plugin.toml")
    try:
        installed_manifest = _manifest(installed / "plugin.toml")
    except (OSError, RuntimeError, tomllib.TOMLDecodeError):
        return False, "installed_manifest_missing_or_invalid"
    if str(source_manifest.get("id") or "") != PLUGIN_ID:
        raise RuntimeError(f"unexpected source plugin id: {source_manifest.get('id')!r}")
    if str(installed_manifest.get("id") or "") != PLUGIN_ID:
        return False, "installed_identity_mismatch"
    if str(source_manifest.get("version") or "") != str(installed_manifest.get("version") or ""):
        return False, "version_mismatch"

    for rel in _source_files(source):
        target = installed / rel
        if not target.is_file():
            return False, f"missing:{rel.as_posix()}"
        if (source / rel).read_bytes() != target.read_bytes():
            return False, f"content_mismatch:{rel.as_posix()}"
    return True, "exact_source_match"


async def _ensure(args: argparse.Namespace) -> dict[str, object]:
    # Import only after storage environment is pinned for this process.
    from plugin import settings as plugin_settings
    from plugin.neko_plugin_cli.public import build_plugin
    from plugin.server.application.install_source import (
        build_install_source_manager,
        get_install_source_manager,
        set_global_manager,
    )
    from plugin.server.application.plugin_cli.service import PluginCliService

    source = args.source.resolve()
    storage_root = args.storage_root.resolve()
    installed_root = Path(plugin_settings.USER_PLUGIN_EXEC_ROOT).resolve()
    installed = installed_root / PLUGIN_ID
    exact, reason = _installed_matches_source(source, installed)
    desired_version = str(_manifest(source / "plugin.toml").get("version") or "")
    current_version = ""
    try:
        current_version = str(_manifest(installed / "plugin.toml").get("version") or "")
    except (OSError, RuntimeError, tomllib.TOMLDecodeError):
        pass

    if exact:
        return {
            "ok": True,
            "changed": False,
            "plugin_id": PLUGIN_ID,
            "version": desired_version,
            "status": "current",
            "installed_dir": str(installed),
        }

    if args.verify_only:
        return {
            "ok": False,
            "changed": False,
            "plugin_id": PLUGIN_ID,
            "version": desired_version,
            "status": "stale",
            "reason": reason,
            "installed_dir": str(installed),
        }

    package_root = Path(plugin_settings.USER_PLUGIN_PACKAGES_ROOT).resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    package_path = package_root / f"{PLUGIN_ID}-{desired_version}.neko-plugin"
    build = build_plugin(source, package_path)

    service = PluginCliService()
    verified = await service.verify(package=str(package_path))
    if not bool(verified.get("ok")):
        raise RuntimeError("N.E.K.O rejected the freshly built XiaoYu plugin package")
    if str(verified.get("package_id") or "") != PLUGIN_ID:
        raise RuntimeError(f"package identity mismatch: {verified.get('package_id')!r}")

    manager = get_install_source_manager()
    if manager is None:
        manager = build_install_source_manager()
        set_global_manager(manager)
    load = getattr(manager, "load", None)
    if callable(load):
        await asyncio.to_thread(load)
    reconcile = getattr(manager, "reconcile", None)
    if callable(reconcile):
        # Legacy XiaoYu packages predate source ownership tracking. Native
        # reconcile seeds an existing user executable directory as manual;
        # the normal install-plan then requires a bound takeover token.
        await asyncio.to_thread(reconcile)

    plan = await service.plan_install(package=str(package_path))
    action = str(plan.get("action") or "")
    if action == "blocked":
        raise RuntimeError(
            "N.E.K.O blocked XiaoYu private plugin replacement: "
            + json.dumps(plan, ensure_ascii=False, sort_keys=True)
        )

    install_kwargs: dict[str, object] = {
        "package": str(package_path),
        "install_source": "imported",
    }
    if action != "install":
        token = str(plan.get("confirmation_token") or "")
        if not token:
            raise RuntimeError(
                "N.E.K.O replacement plan did not provide a confirmation token: "
                + json.dumps(plan, ensure_ascii=False, sort_keys=True)
            )
        install_kwargs["confirm_upgrade"] = True
        install_kwargs["confirmation_token"] = token

    result = await service.install(**install_kwargs)
    state_migrated = _migrate_known_v1_owner_state(
        storage_root,
        from_version=current_version,
        target_version=desired_version,
    )
    exact_after, after_reason = _installed_matches_source(source, installed)
    if not exact_after:
        raise RuntimeError(f"installed XiaoYu plugin does not match private source: {after_reason}")

    return {
        "ok": True,
        "changed": True,
        "plugin_id": PLUGIN_ID,
        "version": desired_version,
        "status": "installed",
        "operation": str(result.get("operation") or action),
        "installed_dir": str(installed),
        "package_path": str(build.package_path),
        "payload_hash": str(build.payload_hash),
        "state_migrated": state_migrated,
    }


def main() -> int:
    args = _parse_args()
    args.neko_root = args.neko_root.resolve()
    args.storage_root = args.storage_root.resolve()
    args.source = args.source.resolve()
    if not (args.neko_root / "plugin").is_dir():
        raise SystemExit(f"N.E.K.O plugin tree not found: {args.neko_root}")
    if not (args.source / "plugin.toml").is_file():
        raise SystemExit(f"private plugin source missing plugin.toml: {args.source}")

    _configure_environment(args.neko_root, args.storage_root)
    result = asyncio.run(_ensure(args))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if bool(result.get("ok")) else 3


if __name__ == "__main__":
    raise SystemExit(main())
