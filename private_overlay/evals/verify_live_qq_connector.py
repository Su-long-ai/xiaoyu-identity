from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_QQ_PLUGIN = DEFAULT_NEKO / "plugin" / "plugins" / "qq_auto_reply"
DEFAULT_NAPCAT_CONFIG = Path(
    r"C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\config"
)
DEFAULT_PLUGIN_STATE = Path(
    r"D:\xiaoyu_private_overlay_state\neko-sandbox\plugins\qq_auto_reply\data"
)


def _load_napcat_server(config_dir: Path) -> tuple[str, str, str]:
    files = sorted(
        config_dir.glob("onebot11_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise RuntimeError("no saved NapCat OneBot config found")
    path = files[0]
    cfg = json.loads(path.read_text(encoding="utf-8"))
    servers = (
        ((cfg.get("network") or {}).get("websocketServers"))
        if isinstance(cfg, dict)
        else None
    ) or []
    server = next(
        (
            item
            for item in servers
            if isinstance(item, dict)
            and item.get("enable") is True
            and int(item.get("port") or 0) == 3001
        ),
        None,
    )
    if not server:
        raise RuntimeError("enabled XiaoYu NapCat websocket server on port 3001 not found")
    host = str(server.get("host") or "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(f"refuse non-local NapCat endpoint: {host}")
    token = str(server.get("token") or "")
    match = re.search(r"onebot11_(\d+)", path.stem)
    expected_account = match.group(1) if match else ""
    return f"ws://{host}:{int(server['port'])}", token, expected_account


async def _wait_connected(client, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.is_connected():
            return True
        await asyncio.sleep(0.1)
    return client.is_connected()


async def _run(args: argparse.Namespace) -> int:
    onebot_url, token, expected_account = _load_napcat_server(args.napcat_config)

    trusted_users_count = 0
    trusted_groups_count = 0
    identity_links_users = 0
    identity_links_groups = 0
    business_path = args.plugin_state / "business_config.json"
    if business_path.exists():
        business = json.loads(business_path.read_text(encoding="utf-8"))
        for key, target in (
            ("trusted_users", "users"),
            ("trusted_groups", "groups"),
        ):
            value = business.get(key)
            if isinstance(value, (list, dict)):
                count = len(value)
            elif isinstance(value, str):
                count = len([part for part in value.split(",") if part.strip()])
            else:
                count = 0
            if target == "users":
                trusted_users_count = count
            else:
                trusted_groups_count = count
    links_path = args.plugin_state / "identity_links.json"
    if links_path.exists():
        links = json.loads(links_path.read_text(encoding="utf-8"))
        identity_links_users = len((links.get("users") or {}))
        identity_links_groups = len((links.get("groups") or {}))

    sys.path.insert(0, str(args.neko_root.resolve()))

    from plugin.plugins.qq_auto_reply import connector_seam

    client = connector_seam.OneBotClient(
        onebot_url=onebot_url,
        token=token,
        direction="forward",
    )
    result: dict = {
        "schema_version": 1,
        "neko_commit": args.neko_commit,
        "qq_plugin_commit": args.qq_plugin_commit,
        "onebot_endpoint": "ws://127.0.0.1:3001",
        "token_present": bool(token),
        "token_recorded": False,
        "account_recorded": False,
        "connector_source": connector_seam.CONNECTOR_SOURCE,
        "connector_module": connector_seam.CONNECTOR_MODULE,
        "external_plugin_used": True,
        "message_sent": False,
        "trusted_users_count": trusted_users_count,
        "trusted_groups_count": trusted_groups_count,
        "identity_links_users": identity_links_users,
        "identity_links_groups": identity_links_groups,
        "safe_message_target_available": any(
            [
                trusted_users_count,
                trusted_groups_count,
                identity_links_users,
                identity_links_groups,
            ]
        ),
    }
    try:
        await client.connect()
        connected = await _wait_connected(client)
        result["connected"] = connected
        if not connected:
            result["verdict"] = "FAIL"
            result["reason"] = "external plugin OneBotClient did not connect"
            return 13

        status = await client.call_action("get_status", timeout=5.0)
        login = await client.get_login_info()
        user_id = str(login.get("user_id") or "").strip()
        login_status = await client.get_login_status()

        result["self_send_receipt_requested"] = bool(args.self_send_receipt)
        result["self_send_receipt_pass"] = None
        if args.self_send_receipt:
            result["safe_self_target_available"] = True
            result["self_send_target"] = "login_self"
            result["self_send_actions"] = ["send_private_msg", "get_msg", "delete_msg"]
            probe_text = "[XiaoYu E2E 自测] QQ 本机回执验证，可忽略。"
            message_id = await client.send_message(user_id, probe_text)
            result["self_send_receipt"] = bool(message_id)
            result["self_send_get_msg_ok"] = False
            result["self_send_content_match"] = False
            result["self_send_recalled"] = False
            if message_id:
                sent = await client.get_msg(message_id)
                result["self_send_get_msg_ok"] = bool(sent)
                raw = sent.get("raw_message") or sent.get("message") or ""
                if isinstance(raw, list):
                    raw = json.dumps(raw, ensure_ascii=False)
                result["self_send_content_match"] = "XiaoYu E2E 自测" in str(raw)
                await client.delete_msg(message_id)
                result["self_send_recalled"] = True
            result["self_send_receipt_pass"] = all(
                [
                    result["self_send_receipt"],
                    result["self_send_get_msg_ok"],
                    result["self_send_content_match"],
                    result["self_send_recalled"],
                ]
            )
            result["message_sent"] = True

        result.update(
            {
                "status_online": bool(status.get("online")),
                "status_good": bool(status.get("good")),
                "login_identity_present": bool(user_id),
                "login_identity_matches_saved_config": bool(
                    expected_account and user_id == expected_account
                ),
                "client_cached_online": login_status.get("status") == "online",
                "client_cached_identity_present": bool(login_status.get("self_id")),
                "read_only_actions": ["get_status", "get_login_info"],
            }
        )
        ok = all(
            [
                result["connected"],
                result["status_online"],
                result["status_good"],
                result["login_identity_present"],
                result["login_identity_matches_saved_config"],
                result["client_cached_online"],
                result["client_cached_identity_present"],
                (result["self_send_receipt_pass"] is True)
                if args.self_send_receipt
                else True,
            ]
        )
        result["verdict"] = "PASS" if ok else "FAIL"
        return 0 if ok else 14
    finally:
        await client.disconnect()
        result["disconnected_cleanly"] = not client.is_connected()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--qq-plugin-root", type=Path, default=DEFAULT_QQ_PLUGIN)
    ap.add_argument("--napcat-config", type=Path, default=DEFAULT_NAPCAT_CONFIG)
    ap.add_argument("--plugin-state", type=Path, default=DEFAULT_PLUGIN_STATE)
    ap.add_argument(
        "--neko-commit",
        default="6261a5f653af066d2a7da8e265f624e3df03e3f7",
    )
    ap.add_argument(
        "--qq-plugin-commit",
        default="54acf36bf978edad4757e5fffc743c5618360700",
    )
    ap.add_argument("--evidence", type=Path)
    ap.add_argument(
        "--self-send-receipt",
        action="store_true",
        help="send one message to the logged-in QQ account itself, verify receipt/content, then recall it",
    )
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
