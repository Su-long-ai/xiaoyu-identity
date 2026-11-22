from __future__ import annotations

import argparse
import ast
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


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


class _Logger:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


def _load_receipt_helpers(root: Path):
    """Execute only the thin receipt helpers, not character_runtime's heavy imports."""
    source = _text(root, "app/main_server/character_runtime.py")
    module = ast.parse(source)
    wanted = {
        "_NekoClawDeliveryClaim",
        "_claim_nekoclaw_delivery",
        "_settle_nekoclaw_delivery",
        "_settle_nekoclaw_callback_ack",
    }
    body = []
    for node in module.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            body.append(node)
    found = {node.name for node in body}
    assert found == wanted, f"missing receipt helpers: {sorted(wanted - found)}"

    calls = []

    async def publish(action, delivery_id, attempt_id, claim_id, *, lanlan_name=None, **_kwargs):
        calls.append((action, delivery_id, attempt_id, claim_id, lanlan_name))
        return {
            "claim": "claimed",
            "commit": "committed",
            "release": "released",
        }[action]

    namespace = {
        "asyncio": asyncio,
        "dataclass": dataclass,
        "uuid4": uuid4,
        "logger": _Logger(),
        "publish_nekoclaw_delivery_barrier": publish,
    }
    helper_module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(helper_module)
    exec(compile(helper_module, "<receipt-helpers>", "exec"), namespace)
    return SimpleNamespace(**namespace), calls


def _load_epoch_observer(root: Path):
    source = _text(root, "app/agent_server/api_runtime.py")
    module = ast.parse(source)
    node = next(
        (
            item
            for item in module.body
            if isinstance(item, ast.AsyncFunctionDef)
            and item.name == "_observe_nekoclaw_main_epoch"
        ),
        None,
    )
    assert node is not None, "missing main epoch observer"

    class Ledger:
        def __init__(self):
            self.calls = 0

        async def outbox_mark_main_restart_uncertain(self):
            self.calls += 1
            return 2

    ledger = Ledger()

    async def ready_host():
        return SimpleNamespace(ledger=ledger)

    namespace = {
        "Any": object,
        "logger": _Logger(),
        "ready_host": ready_host,
        "_nekoclaw_main_epoch": None,
        "_nekoclaw_retired_main_epochs": set(),
    }
    helper_module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(helper_module)
    exec(compile(helper_module, "<main-epoch-observer>", "exec"), namespace)
    return SimpleNamespace(**namespace), ledger


async def _verify_main_restart_epoch(root: Path) -> None:
    helpers, ledger = _load_epoch_observer(root)
    observe = helpers._observe_nekoclaw_main_epoch

    assert await observe("") == "missing"
    assert ledger.calls == 0
    assert await observe("main-a") == "initialized"
    assert ledger.calls == 0
    assert await observe("main-a") == "same"
    assert ledger.calls == 0

    assert await observe("main-b") == "reconciled:2"
    assert ledger.calls == 1
    # A delayed barrier/announcement from the retired process must never move
    # authority back to its epoch. Otherwise that old process could claim a
    # row again before crossing a visible effect boundary.
    assert await observe("main-a") == "stale"
    assert ledger.calls == 1
    assert await observe("main-b") == "same"
    assert ledger.calls == 1
    assert await observe("main-c") == "reconciled:2"
    assert ledger.calls == 2
    assert await observe("main-a") == "stale"
    assert await observe("main-b") == "stale"
    assert ledger.calls == 2
    assert await observe("main-c") == "same"


async def _verify_receipt_faults(root: Path) -> None:
    helpers, calls = _load_receipt_helpers(root)

    # Legacy/non-NekoClaw events preserve the native path with no new barrier.
    assert await helpers._claim_nekoclaw_delivery({"event_type": "task_result"}) is None
    assert calls == []

    # A retired main epoch is rejected by the agent-side barrier. The main
    # process must treat any non-"claimed" answer as "do not cross effect".
    claim_globals = helpers._claim_nekoclaw_delivery.__globals__
    native_publish = claim_globals["publish_nekoclaw_delivery_barrier"]
    stale_calls = []

    async def stale_publish(action, delivery_id, attempt_id, claim_id, *, lanlan_name=None, **_kwargs):
        stale_calls.append((action, delivery_id, attempt_id, claim_id, lanlan_name))
        return "stale_epoch"

    claim_globals["publish_nekoclaw_delivery_barrier"] = stale_publish
    try:
        assert (
            await helpers._claim_nekoclaw_delivery(
                {"delivery_id": 6, "delivery_attempt_id": "retired-main"}
            )
            is False
        )
        assert len(stale_calls) == 1 and stale_calls[0][0:3] == (
            "claim",
            6,
            "retired-main",
        )
    finally:
        claim_globals["publish_nekoclaw_delivery_barrier"] = native_publish

    # Malformed partial identity is rejected before any effect and before IPC.
    assert (
        await helpers._claim_nekoclaw_delivery(
            {"delivery_id": 7, "delivery_attempt_id": ""}
        )
        is False
    )
    assert calls == []

    claim = await helpers._claim_nekoclaw_delivery(
        {
            "delivery_id": 7,
            "delivery_attempt_id": "attempt-a",
            "lanlan_name": "Lan",
        }
    )
    assert isinstance(claim, helpers._NekoClawDeliveryClaim)
    assert calls[-1][0:3] == ("claim", 7, "attempt-a")

    # Positive native effect receipt commits the exact claim.
    future = asyncio.get_running_loop().create_future()
    future.set_result(True)
    await helpers._settle_nekoclaw_callback_ack(claim, future)
    assert calls[-1][0] == "commit"
    assert calls[-1][1:4] == (7, "attempt-a", claim.claim_id)

    # Proven native retraction/no-effect releases only the exact claim.
    second = await helpers._claim_nekoclaw_delivery(
        {"delivery_id": 8, "delivery_attempt_id": "attempt-b"}
    )
    future = asyncio.get_running_loop().create_future()
    future.set_result(False)
    await helpers._settle_nekoclaw_callback_ack(second, future)
    assert calls[-1][0] == "release"
    assert calls[-1][1:4] == (8, "attempt-b", second.claim_id)

    # Cancellation is ambiguous. It must not translate into release/FAILED/retry.
    third = await helpers._claim_nekoclaw_delivery(
        {"delivery_id": 9, "delivery_attempt_id": "attempt-c"}
    )
    before = len(calls)
    future = asyncio.get_running_loop().create_future()
    waiter = asyncio.create_task(helpers._settle_nekoclaw_callback_ack(third, future))
    await asyncio.sleep(0)
    waiter.cancel()
    try:
        await waiter
    except asyncio.CancelledError:
        pass
    assert len(calls) == before, "ambiguous cancellation must not emit commit/release"

    # A native receipt future that itself fails is equally ambiguous. Do not
    # turn transport/consumer failure into a proven no-effect release.
    fourth = await helpers._claim_nekoclaw_delivery(
        {"delivery_id": 10, "delivery_attempt_id": "attempt-d"}
    )
    before = len(calls)
    future = asyncio.get_running_loop().create_future()
    future.set_exception(RuntimeError("receipt channel lost"))
    await helpers._settle_nekoclaw_callback_ack(fourth, future)
    assert len(calls) == before, "failed receipt must remain fenced"


def _verify_wiring(root: Path) -> None:
    bus = _text(root, "main_logic/agent_event_bus.py")
    api = _text(root, "app/agent_server/api_runtime.py")
    mount = _text(root, "app/agent_server/nekoclaw_mount.py")
    main = _text(root, "app/main_server/character_runtime.py")

    assert "def notify_nekoclaw_delivery_barrier_ack" in bus
    assert "def notify_nekoclaw_main_epoch_ack" in bus
    assert "async def publish_nekoclaw_delivery_barrier" in bus
    assert 'action not in {"claim", "commit", "release"}' in bus
    assert "self.instance_id = uuid.uuid4().hex" in bus
    assert "self._epoch_announce_task: Optional[asyncio.Task] = None" in bus
    _ordered(
        bus,
        "self._recv_thread.start()",
        "self._epoch_announce_task = asyncio.create_task(",
        "_announce_nekoclaw_main_epoch(self)",
    )
    assert "epoch_task.cancel()" in bus
    assert "await asyncio.gather(epoch_task, return_exceptions=True)" in bus
    assert "bridge_override: Optional[MainServerAgentBridge] = None" in bus
    assert "bridge = bridge_override or _main_bridge_ref" in bus
    assert "await asyncio.sleep(min(0.05 * (attempt + 1), 0.2))" in bus
    assert "async def _announce_nekoclaw_main_epoch" in bus
    assert 'label="nekoclaw_main_epoch"' in bus
    assert "bridge_override=bridge" in bus
    assert '"main_epoch": str(getattr(_main_bridge_ref, "instance_id", "") or "")' in bus

    for method in (
        "outbox_claim_delivery",
        "outbox_commit_delivery",
        "outbox_release_delivery",
    ):
        assert method in api
    assert '"nekoclaw_delivery_barrier"' in api
    assert '"nekoclaw_delivery_barrier_ack"' in api
    assert '"nekoclaw_main_epoch_ack"' in api
    assert "async def _observe_nekoclaw_main_epoch" in api
    assert "_nekoclaw_retired_main_epochs: set[str] = set()" in api
    assert 'if epoch in _nekoclaw_retired_main_epochs:' in api
    assert '_nekoclaw_retired_main_epochs.add(previous)' in api
    assert "async def _handle_nekoclaw_main_epoch" in api
    assert "outbox_mark_main_restart_uncertain" in api
    assert 'if epoch_state == "stale":' in api
    assert 'result = "stale_epoch"' in api
    assert 'if event_type == "nekoclaw_main_epoch":' in api
    assert "_create_tracked_task(_handle_nekoclaw_main_epoch(event))" in api
    restore_start = api.index('if event_type == "agent_intent_restore_signal":')
    restore_end = api.index("return", restore_start)
    assert "_observe_nekoclaw_main_epoch" not in api[restore_start:restore_end]

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
    assert "notify_nekoclaw_main_epoch_ack" in main
    assert 'if event_type == "nekoclaw_main_epoch_ack":' in main
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
    direct_start = main.index('if event.get("direct_reply"):')
    direct_end = main.index("# Build structured callback", direct_start)
    direct_branch = main[direct_start:direct_end]
    _ordered(
        direct_branch,
        "if delivered:",
        "await _settle_nekoclaw_delivery(delivery_claim, True)",
        "return",
    )
    assert "_settle_nekoclaw_callback_ack" in main
    assert "_spawn_nekoclaw_delivery_settler" in main
    # Unknown settlement must remain fenced; the adapter must not synthesize a retry.
    assert "No local retry here." in main
    assert "outbox_mark_failed" not in main


async def _verify(root: Path) -> None:
    _verify_wiring(root)
    await _verify_native_ack(root)
    await _verify_receipt_faults(root)
    await _verify_main_restart_epoch(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_verify(args.neko_root))
    print("native delivery receipt candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
