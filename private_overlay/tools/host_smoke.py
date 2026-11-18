import asyncio
import json
import os
import sys
from pathlib import Path

NEKO_ROOT = Path(os.environ.get("NEKO_ROOT", r"D:\xiaoyu_external_audit\N.E.K.O"))
sys.path.insert(0, str(NEKO_ROOT))

from plugin.core.state import state  # noqa: E402
from plugin.server.application.plugins.lifecycle_service import PluginLifecycleService  # noqa: E402


PLUGIN_ID = "xiaoyu_private"


async def run() -> int:
    service = PluginLifecycleService()
    started = False
    try:
        start_result = await service.start_plugin(
            PLUGIN_ID,
            persist_user_intent=False,
        )
        started = True
        print("START", json.dumps(start_result, ensure_ascii=False, default=str))

        with state.acquire_plugins_read_lock():
            meta = state.plugins.get(PLUGIN_ID)
            host = state.plugin_hosts.get(PLUGIN_ID)

        print(
            "META_LOAD_STATE",
            None if not isinstance(meta, dict) else meta.get("runtime_load_state"),
        )
        print("HOST", type(host).__name__ if host is not None else None)

        if host is None:
            raise RuntimeError(f"{PLUGIN_ID} host missing after start")

        result = await host.trigger("status", {}, timeout=10.0)
        print("STATUS_RESULT", json.dumps(result, ensure_ascii=False, default=str))

        text = json.dumps(result, ensure_ascii=False, default=str)
        required = ["xiaoyu", "private_overlay", "neko_native"]
        if not all(item in text for item in required):
            raise RuntimeError(f"unexpected status payload: {result!r}")

        print("PASS: N.E.K.O host start -> entry trigger")
        return 0
    finally:
        if started:
            stop_result = await service.stop_plugin(PLUGIN_ID)
            print("STOP", json.dumps(stop_result, ensure_ascii=False, default=str))


def main() -> int:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
