"""Ensure XiaoYu's private plugin is installed through N.E.K.O's native package workflow.

The executable plugin tree remains owned by N.E.K.O. Persistent plugin state stays
under the normal plugin state root. This helper never copies plugin code directly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import tomllib
from pathlib import Path


PLUGIN_ID = "xiaoyu_interaction_policy"
CLASSIFIER_MODEL_USAGE = "interaction_classifier"
CLASSIFIER_HOST_API = "agent_small"
CLASSIFIER_SLOT_NAME = "Small familiar model"
CLASSIFIER_SLOT_TIMEOUT_SECONDS = 8.0
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TEXT_PAYLOAD_SUFFIXES = {
    ".py", ".toml", ".json", ".md", ".txt", ".yaml", ".yml",
    ".html", ".css", ".js", ".ts", ".tsx", ".ps1", ".cmd",
}


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


def _classifier_binding_status(service) -> dict[str, object]:
    """Return the host-owned binding state for the classifier usage."""
    bindings = service.get_bindings(PLUGIN_ID)
    usages = bindings.get("requirements") if isinstance(bindings, dict) else None
    usage = usages.get(CLASSIFIER_MODEL_USAGE) if isinstance(usages, dict) else None
    if not isinstance(usage, dict):
        return {"declared": False, "status": "not_declared"}

    slot_id = str(usage.get("slot_id") or "")
    version = int(usage.get("version") or 0)
    if not slot_id:
        return {
            "declared": True,
            "status": "unbound",
            "slot_id": "",
            "version": version,
        }
    slot = service.get_slot(slot_id)
    return {
        "declared": True,
        "status": str(usage.get("status") or "bound"),
        "slot_id": slot_id,
        "version": version,
        "source": str(slot.get("source") or ""),
        "host_api": str(slot.get("host_api") or ""),
    }


def _ensure_classifier_model_binding(service=None) -> dict[str, object]:
    """Prefer the native small familiar tier without overriding user choices.

    N.E.K.O automatically binds a newly declared usage to its seeded agent
    host-follow slot and records binding version 1. That exact state is the only
    binding we migrate. Any later version or non-default slot is user-managed
    and is preserved.
    """
    if service is None:
        from plugin.server.application.model_config_service import ModelConfigService
        service = ModelConfigService()

    state = _classifier_binding_status(service)
    if not state.get("declared"):
        return state

    # N.E.K.O normally performs this after install commit on a daemon thread.
    # XiaoYu's installer is intentionally short-lived, so that background
    # thread can be terminated with the CLI process before it fsyncs. Reuse
    # the same native auto-bind synchronously only for a never-touched usage.
    if state.get("status") == "unbound" and int(state.get("version") or 0) == 0:
        ensure_native = getattr(service, "ensure_host_follow_binding", None)
        if callable(ensure_native):
            ensure_native(PLUGIN_ID)
            state = _classifier_binding_status(service)
        if state.get("status") == "unbound" and int(state.get("version") or 0) == 0:
            return {**state, "migration": "native_autobind_unavailable"}

    if state.get("host_api") == CLASSIFIER_HOST_API:
        return {**state, "migration": "already_small"}

    auto_agent = (
        state.get("status") == "bound"
        and state.get("source") == "host_follow"
        and state.get("host_api") == "agent"
        and state.get("version") == 1
    )
    if not auto_agent:
        return {**state, "migration": "user_binding_preserved"}

    slots_payload = service.list_slots()
    slots = slots_payload.get("slots") if isinstance(slots_payload, dict) else []
    target = next(
        (
            item for item in (slots or [])
            if isinstance(item, dict)
            and item.get("source") == "host_follow"
            and item.get("host_api") == CLASSIFIER_HOST_API
            and "text" in (item.get("capabilities") or [])
        ),
        None,
    )
    if target is None:
        target = service.create_slot({
            "name": CLASSIFIER_SLOT_NAME,
            "source": "host_follow",
            "host_api": CLASSIFIER_HOST_API,
            "capabilities": ["text"],
            "timeout_seconds": CLASSIFIER_SLOT_TIMEOUT_SECONDS,
        })

    target_id = str(target.get("id") or "")
    if not target_id:
        raise RuntimeError("N.E.K.O did not return an id for the agent_small model slot")
    service.set_binding(
        PLUGIN_ID,
        CLASSIFIER_MODEL_USAGE,
        target_id,
        expected_version=int(state.get("version") or 0),
    )
    return {
        **_classifier_binding_status(service),
        "migration": "auto_agent_to_agent_small",
    }

def _runtime_ports_open(
    ports: tuple[int, ...] = (48911, 48916),
    *,
    host: str = "127.0.0.1",
    timeout: float = 0.15,
) -> list[int]:
    """Return XiaoYu/N.E.K.O runtime ports that currently accept connections.

    Replacing an executable plugin tree while the host has that tree loaded can
    invalidate the active runtime and trigger a coordinated backend shutdown.
    Startup installs happen before these ports exist, so block only live
    replacements; verification remains read-only and is always allowed.
    """
    open_ports: list[int] = []
    for port in ports:
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                open_ports.append(int(port))
        except OSError:
            continue
    return open_ports


def _should_block_live_replacement(*, exact: bool, verify_only: bool, open_ports: list[int]) -> bool:
    return (not exact) and (not verify_only) and bool(open_ports)


def _payload_content_matches(source_path: Path, target_path: Path) -> bool:
    """Compare plugin payload without treating text EOL style as executable drift.

    Git worktrees may materialize the same tracked text as LF or CRLF. N.E.K.O's
    package/install workflow remains authoritative; this helper only prevents a
    private verify-only preflight from demanding a reinstall for newline-only
    differences. Binary payloads remain byte-exact.
    """
    source_bytes = source_path.read_bytes()
    target_bytes = target_path.read_bytes()
    if source_bytes == target_bytes:
        return True
    if source_path.suffix.lower() not in TEXT_PAYLOAD_SUFFIXES:
        return False
    try:
        source_text = source_bytes.decode("utf-8-sig")
        target_text = target_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    normalize = lambda value: value.replace("\r\n", "\n").replace("\r", "\n")
    return normalize(source_text) == normalize(target_text)


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
        if not _payload_content_matches(source / rel, target):
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
        model_binding = _ensure_classifier_model_binding()
        return {
            "ok": True,
            "changed": False,
            "plugin_id": PLUGIN_ID,
            "version": desired_version,
            "status": "current",
            "installed_dir": str(installed),
            "classifier_model_binding": model_binding,
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

    open_ports = _runtime_ports_open()
    if _should_block_live_replacement(exact=exact, verify_only=False, open_ports=open_ports):
        return {
            "ok": False,
            "changed": False,
            "plugin_id": PLUGIN_ID,
            "version": desired_version,
            "status": "live_runtime_replacement_blocked",
            "reason": "restart XiaoYu before replacing a loaded private plugin",
            "open_ports": open_ports,
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
    exact_after, after_reason = _installed_matches_source(source, installed)
    if not exact_after:
        raise RuntimeError(f"installed XiaoYu plugin does not match private source: {after_reason}")
    model_binding = _ensure_classifier_model_binding()

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
        "classifier_model_binding": model_binding,
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
