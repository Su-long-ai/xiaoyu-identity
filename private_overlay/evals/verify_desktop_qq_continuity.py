from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STORAGE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_QQ_PLUGIN = DEFAULT_NEKO / "plugin" / "plugins" / "qq_auto_reply"
EXPECTED_CHARACTER = "XiaoYu"


def _set_storage(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _digest_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _EmptyReflections:
    async def aupdate_suppressions(self, _name: str) -> None:
        return None

    async def aget_pending_reflections(self, _name: str, **_kwargs):
        return []

    async def aget_confirmed_reflections(self, _name: str, **_kwargs):
        return []


class _I18n:
    @staticmethod
    def t(_key: str, *, default: str = "", **_kwargs) -> str:
        return default


class _Logger:
    def warning(self, *_args, **_kwargs) -> None:
        return None


class _Bridge:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[str] = []

    async def fetch_bootstrap_memory(self, her_name: str, **_kwargs) -> str:
        self.calls.append(her_name)
        return self.text


async def _probe_authority(neko_root: Path, storage_root: Path) -> dict:
    _set_storage(storage_root)
    sys.path.insert(0, str(neko_root.resolve()))

    from memory.event_log import EventLog
    from memory.introspection import arender_injected_memory
    from memory.persona import PersonaManager
    from utils.config_manager import get_config_manager
    from plugin.plugins.qq_auto_reply.session_instruction_service import (
        QQSessionInstructionService,
    )

    cm = get_config_manager()
    character_data = cm.get_character_data()
    master_name = str(character_data[0] or "")
    active_character = str(character_data[1] or "")
    character_prompt = str((character_data[5] or {}).get(active_character) or "")

    persona_manager = PersonaManager(event_log=EventLog())
    persona = persona_manager.get_persona(active_character)
    persona_digest = _digest_json(persona)

    injected = await arender_injected_memory(
        persona_manager,
        _EmptyReflections(),
        active_character,
        pinned_fact_store=None,
        lang="zh",
    )
    injected_text = injected.text

    bridge = _Bridge(injected_text)
    plugin = SimpleNamespace(
        _qq_settings={},
        memory_bridge=bridge,
        i18n=_I18n(),
        logger=_Logger(),
    )
    service = object.__new__(QQSessionInstructionService)
    service.plugin = plugin

    qq_core_memory = await service._build_core_memory_section(
        should_use_memory_context=True,
        her_name=active_character,
        master_name=master_name,
        context_ready_template="{name}",
        is_group=False,
        group_id=None,
        sender_id="owner",
        participant_memory=False,
    )

    reply_context_source = (
        neko_root
        / "plugin"
        / "plugins"
        / "qq_auto_reply"
        / "reply_context_node.py"
    ).read_text(encoding="utf-8")
    memory_bridge_source = (
        neko_root
        / "plugin"
        / "plugins"
        / "qq_auto_reply"
        / "memory_bridge.py"
    ).read_text(encoding="utf-8")
    routes_source = (
        neko_root / "app" / "memory_server" / "routes.py"
    ).read_text(encoding="utf-8")

    contracts = {
        "qq_reads_active_character": (
            "config_manager.get_character_data()" in reply_context_source
            and "her_name=her_name" in reply_context_source
        ),
        "qq_private_bootstrap_uses_new_dialog": (
            'f"{self._base_url()}/new_dialog/{her_name}"' in memory_bridge_source
        ),
        "new_dialog_uses_runtime_persona_manager": (
            "arender_injected_memory(" in routes_source
            and "runtime.persona_manager" in routes_source
        ),
    }

    return {
        "active_character": active_character,
        "character_prompt_sha256": hashlib.sha256(
            character_prompt.encode("utf-8")
        ).hexdigest(),
        "persona_sha256": persona_digest,
        "persona_render_sha256": hashlib.sha256(
            injected_text.encode("utf-8")
        ).hexdigest(),
        "persona_render_nonempty": bool(injected_text),
        "qq_memory_bridge_calls": bridge.calls,
        "qq_core_memory_contains_persona_render": bool(
            injected_text and injected_text in qq_core_memory
        ),
        "source_contracts": contracts,
    }


async def _probe_qq_host() -> dict:
    from plugin.core.state import state
    from plugin.server.application.plugins.lifecycle_service import (
        PluginLifecycleService,
    )

    service = PluginLifecycleService()
    started = False
    try:
        start_result = await service.start_plugin(
            "qq_auto_reply",
            persist_user_intent=False,
        )
        started = True
        with state.acquire_plugins_read_lock():
            host = state.plugin_hosts.get("qq_auto_reply")
            meta = state.plugins.get("qq_auto_reply")
        if host is None:
            raise RuntimeError("qq_auto_reply host missing after startup")
        return {
            "started": True,
            "host_type": type(host).__name__,
            "runtime_load_state": (
                meta.get("runtime_load_state") if isinstance(meta, dict) else None
            ),
            "start_success": bool(
                isinstance(start_result, dict)
                and start_result.get("success", True)
            ),
        }
    finally:
        if started:
            await service.stop_plugin("qq_auto_reply")


async def _run(args: argparse.Namespace) -> int:
    _set_storage(args.storage_root)
    sys.path.insert(0, str(args.neko_root.resolve()))

    lock = json.loads(args.qq_lock.read_text(encoding="utf-8-sig"))
    plugin_toml = (args.qq_plugin_root / "plugin.toml").read_text(encoding="utf-8")
    plugin_head = os.popen(
        f'git -C "{args.qq_plugin_root}" rev-parse HEAD'
    ).read().strip()

    authority = await _probe_authority(args.neko_root, args.storage_root)
    host = await _probe_qq_host()

    checks = {
        "character_is_xiaoyu": authority["active_character"] == EXPECTED_CHARACTER,
        "persona_render_nonempty": authority["persona_render_nonempty"],
        "qq_uses_same_character": authority["qq_memory_bridge_calls"] == [EXPECTED_CHARACTER],
        "qq_contains_same_persona_render": authority[
            "qq_core_memory_contains_persona_render"
        ],
        "source_contracts": all(authority["source_contracts"].values()),
        "qq_host_started": bool(host.get("started")),
        "qq_plugin_pin_matches": plugin_head == lock["tested_commit"],
        "qq_plugin_version_matches": f'version = "{lock["tested_version"]}"' in plugin_toml,
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "verdict": verdict,
        "neko_commit": lock["neko_commit"],
        "storage_root": str(args.storage_root.resolve()),
        "product_data_touched": False,
        "network_qq_login_or_send": False,
        "authority": authority,
        "qq_plugin": {
            "repository": lock["repository"],
            "commit": plugin_head,
            "version": lock["tested_version"],
            **host,
        },
        "checks": checks,
        "caveat": (
            "This proves the isolated desktop/QQ runtime paths resolve one XiaoYu "
            "persona authority and the real QQ plugin process starts. It does not "
            "claim a live NapCat/QQ account E2E message round-trip."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if verdict == "PASS" else 7


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    ap.add_argument("--qq-plugin-root", type=Path, default=DEFAULT_QQ_PLUGIN)
    ap.add_argument(
        "--qq-lock",
        type=Path,
        default=OVERLAY_ROOT / "QQ_PLUGIN_UPSTREAM.lock.json",
    )
    ap.add_argument("--evidence", type=Path)
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
