from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _text(root: Path, relative: str) -> str:
    path = root / relative
    assert path.exists(), f"missing patched file: {relative}"
    return path.read_text(encoding="utf-8")


def _ordered(text: str, *needles: str) -> None:
    pos = -1
    for needle in needles:
        found = text.find(needle, pos + 1)
        assert found >= 0, f"missing expected wiring: {needle}"
        assert found > pos
        pos = found


async def _verify_native_ack(root: Path) -> None:
    sys.path.insert(0, str(root.resolve()))
    from main_logic.proactive_delivery import (  # noqa: PLC0415
        DELIVERY_ACK_FUTURE_KEY,
        resolve_callback_delivery_ack,
    )

    loop = asyncio.get_running_loop()

    delivered = loop.create_future()
    callback = {DELIVERY_ACK_FUTURE_KEY: delivered}
    resolve_callback_delivery_ack(callback, True)
    assert await delivered is True
    # Duplicate resolution is idempotent.
    resolve_callback_delivery_ack(callback, False)
    assert delivered.result() is True

    retracted = loop.create_future()
    callback = {DELIVERY_ACK_FUTURE_KEY: retracted}
    resolve_callback_delivery_ack(callback, False)
    assert await retracted is False


def _verify_wiring(root: Path) -> None:
    bus = _text(root, "main_logic/agent_event_bus.py")
    api = _text(root, "app/agent_server/api_runtime.py")
    mount = _text(root, "app/agent_server/nekoclaw_mount.py")
    main = _text(root, "app/main_server/character_runtime.py")

    assert "def notify_nekoclaw_delivery_barrier_ack" in bus
    assert "async def publish_nekoclaw_delivery_barrier" in bus
    assert 'action not in {"claim", "commit", "release"}' in bus

    for method in (
        "outbox_claim_delivery",
        "outbox_commit_delivery",
        "outbox_release_delivery",
    ):
        assert method in api
    assert '"nekoclaw_delivery_barrier"' in api
    assert '"nekoclaw_delivery_barrier_ack"' in api

    _ordered(
        mount,
        "await host.ledger.outbox_mark_handoff(item.id, attempt_id)",
        'payload["delivery_id"] = int(item.id)',
        'payload["delivery_attempt_id"] = attempt_id',
        "accepted = await _send_main_event(payload)",
        "return DeliveryHandoff(attempt_id) if accepted else False",
    )
    assert "await host.ledger.outbox_mark_sent" not in mount

    assert "class _NekoClawDeliveryClaim" in main
    assert "DELIVERY_ACK_FUTURE_KEY" in main
    assert "notify_nekoclaw_delivery_barrier_ack" in main
    _ordered(
        main,
        'delivery_claim = await _claim_nekoclaw_delivery(event)',
        "# Resolve target session manager",
        "mgr = _get_session_manager(lanlan)",
    )
    assert 'await _settle_nekoclaw_delivery(delivery_claim, False)' in main
    _ordered(
        main,
        "delivery_ack_future = asyncio.get_running_loop().create_future()",
        "callback[DELIVERY_ACK_FUTURE_KEY] = delivery_ack_future",
        'if delivery_mode != "silent":',
    )
    assert "delivery_effect_seen = True" in main
    assert "_settle_nekoclaw_callback_ack" in main
    assert "_spawn_nekoclaw_delivery_settler" in main
    # Unknown settlement must remain fenced; the adapter must not synthesize a retry.
    assert "No local retry here." in main
    assert "outbox_mark_failed" not in main


async def _verify(root: Path) -> None:
    _verify_wiring(root)
    await _verify_native_ack(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_verify(args.neko_root))
    print("native delivery receipt candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
