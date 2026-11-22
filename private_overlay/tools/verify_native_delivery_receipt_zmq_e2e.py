from __future__ import annotations

import argparse
import ast
import asyncio
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict


class _Logger:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


def _free_port() -> int:
    # Test-only allocator; runtime transport remains N.E.K.O's native ZMQ bus.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _wait_until(predicate, *, timeout: float = 3.0, interval: float = 0.02):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("timed out waiting for native ZMQ receipt state")


def _load_agent_handlers(root: Path, ledger, bridge_holder: dict[str, Any]):
    """Load the exact candidate handler functions without importing the full API server."""
    source_path = root / "app/agent_server/api_runtime.py"
    source = source_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    wanted = {
        "_observe_nekoclaw_main_epoch",
        "_handle_nekoclaw_delivery_barrier",
    }
    body = [
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted
    ]
    found = {node.name for node in body}
    assert found == wanted, f"missing candidate handlers: {sorted(wanted - found)}"

    async def ready_host():
        return SimpleNamespace(ledger=ledger)

    async def emit_main_event(event_type: str, lanlan_name=None, **payload):
        bridge = bridge_holder.get("agent")
        assert bridge is not None and bridge.ready
        event = {"event_type": event_type, **payload}
        if lanlan_name is not None:
            event["lanlan_name"] = lanlan_name
        return await bridge.emit_to_main(event)

    namespace = {
        "Any": Any,
        "Dict": Dict,
        "logger": _Logger(),
        "ready_host": ready_host,
        "_emit_main_event": emit_main_event,
        "_nekoclaw_main_epoch": None,
        "_nekoclaw_retired_main_epochs": set(),
    }
    helper_module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(helper_module)
    exec(compile(helper_module, str(source_path), "exec"), namespace)
    return namespace


async def _run(root: Path) -> None:
    sys.path.insert(0, str(root.resolve()))

    # These are the exact native seams found in upstream's existing
    # tests/test_agent_rewrite_regression.py real-ZMQ integration harness.
    from main_logic import agent_event_bus as bus
    from nekoclaw.host.ledger import Ledger

    ports = []
    while len(ports) < 3:
        port = _free_port()
        if port not in ports:
            ports.append(port)
    bus.SESSION_PUB_ADDR = f"tcp://127.0.0.1:{ports[0]}"
    bus.AGENT_PUSH_ADDR = f"tcp://127.0.0.1:{ports[1]}"
    bus.ANALYZE_PUSH_ADDR = f"tcp://127.0.0.1:{ports[2]}"

    bridge_holder: dict[str, Any] = {}
    main_events: list[dict[str, Any]] = []
    observed_epochs: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        ledger = Ledger(Path(td) / "receipt-zmq-e2e.db")
        handlers = _load_agent_handlers(root, ledger, bridge_holder)
        observe_epoch = handlers["_observe_nekoclaw_main_epoch"]
        handle_barrier = handlers["_handle_nekoclaw_delivery_barrier"]

        async def on_session_event(event: dict[str, Any]):
            kind = str(event.get("event_type") or "")
            if kind == "nekoclaw_main_epoch":
                observed_epochs.append(str(event.get("main_epoch") or ""))
                await observe_epoch(event.get("main_epoch"))
                return
            if kind == "nekoclaw_delivery_barrier":
                await handle_barrier(event)

        async def on_agent_event(event: dict[str, Any]):
            main_events.append(dict(event))
            if event.get("event_type") == "nekoclaw_delivery_barrier_ack":
                bus.notify_nekoclaw_delivery_barrier_ack(
                    str(event.get("event_id") or ""),
                    str(event.get("result") or ""),
                )

        agent = bus.AgentServerEventBridge(on_session_event=on_session_event)
        bridge_holder["agent"] = agent
        main = None
        restarted_main = None

        try:
            # Reuse native connect-before-bind behavior so the startup epoch uses
            # the real ANALYZE_PUSH_ADDR socket rather than a direct callback.
            await agent.start()
            await asyncio.sleep(0.05)

            main = bus.MainServerAgentBridge(on_agent_event=on_agent_event)
            await main.start()
            bus.set_main_bridge(main)

            await _wait_until(
                lambda: asyncio.sleep(
                    0, result=(handlers["_nekoclaw_main_epoch"] == main.instance_id)
                )
            )
            assert observed_epochs[-1] == main.instance_id

            first = await ledger.outbox_add(
                None, "task_result", {"summary": "native-zmq-confirmed"}
            )
            assert await ledger.outbox_mark_handoff(first, "attempt-confirmed")
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "claim",
                    first,
                    "attempt-confirmed",
                    "claim-confirmed",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "claimed"
            )
            assert await ledger.outbox_delivery_state(first) == "claimed"
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "commit",
                    first,
                    "attempt-confirmed",
                    "claim-confirmed",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "committed"
            )
            assert await ledger.outbox_delivery_state(first) == "sent"

            # Leave an exact visible-effect claim in flight, then restart only
            # MainServerAgentBridge while the native agent bridge and ledger live on.
            second = await ledger.outbox_add(
                None, "task_result", {"summary": "native-zmq-restart"}
            )
            assert await ledger.outbox_mark_handoff(second, "attempt-restart")
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "claim",
                    second,
                    "attempt-restart",
                    "claim-restart",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "claimed"
            )
            assert await ledger.outbox_delivery_state(second) == "claimed"
            old_epoch = main.instance_id

            bus.set_main_bridge(None)
            await main.stop()
            main = None

            restarted_main = bus.MainServerAgentBridge(on_agent_event=on_agent_event)
            await restarted_main.start()
            bus.set_main_bridge(restarted_main)
            assert restarted_main.instance_id != old_epoch

            await _wait_until(
                lambda: _state_is(ledger, second, "uncertain")
            )
            assert handlers["_nekoclaw_main_epoch"] == restarted_main.instance_id
            assert restarted_main.instance_id in observed_epochs

            # UNKNOWN stays fenced, but a late exact positive receipt is allowed
            # to reconcile it to sent over the same native roundtrip.
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "commit",
                    second,
                    "attempt-restart",
                    "claim-restart",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "committed"
            )
            assert await ledger.outbox_delivery_state(second) == "sent"

            # Same-epoch replay is idempotent and cannot freeze a new valid claim.
            third = await ledger.outbox_add(
                None, "task_result", {"summary": "same-epoch-idempotent"}
            )
            assert await ledger.outbox_mark_handoff(third, "attempt-same")
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "claim",
                    third,
                    "attempt-same",
                    "claim-same",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "claimed"
            )
            assert await restarted_main.publish_analyze_request(
                {
                    "event_type": "nekoclaw_main_epoch",
                    "main_epoch": restarted_main.instance_id,
                }
            )
            await asyncio.sleep(0.15)
            assert await ledger.outbox_delivery_state(third) == "claimed"
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "release",
                    third,
                    "attempt-same",
                    "claim-same",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "released"
            )
            assert await ledger.outbox_delivery_state(third) == "pending"

            # A delayed barrier from the retired main process must be rejected
            # over the real native ZMQ path before it can claim effect rights.
            fourth = await ledger.outbox_add(
                None, "task_result", {"summary": "retired-epoch-must-not-effect"}
            )
            assert await ledger.outbox_mark_handoff(fourth, "attempt-fresh")
            stale_event_id = "stale-main-claim"
            assert await restarted_main.publish_analyze_request(
                {
                    "event_type": "nekoclaw_delivery_barrier",
                    "event_id": stale_event_id,
                    "main_epoch": old_epoch,
                    "action": "claim",
                    "delivery_id": fourth,
                    "delivery_attempt_id": "attempt-old-main",
                    "delivery_claim_id": "claim-old-main",
                }
            )

            async def stale_ack():
                return next(
                    (
                        e
                        for e in reversed(main_events)
                        if e.get("event_type") == "nekoclaw_delivery_barrier_ack"
                        and e.get("event_id") == stale_event_id
                    ),
                    None,
                )

            stale = await _wait_until(stale_ack)
            assert stale.get("result") == "stale_epoch"
            assert await ledger.outbox_delivery_state(fourth) == "pending"
            assert handlers["_nekoclaw_main_epoch"] == restarted_main.instance_id
            assert old_epoch in handlers["_nekoclaw_retired_main_epochs"]

            # The live epoch can still claim the same pending row, proving that
            # rejecting the retired process does not wedge valid delivery.
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "claim",
                    fourth,
                    "attempt-fresh",
                    "claim-fresh",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "claimed"
            )
            assert await ledger.outbox_delivery_state(fourth) == "claimed"
            assert (
                await bus.publish_nekoclaw_delivery_barrier(
                    "release",
                    fourth,
                    "attempt-fresh",
                    "claim-fresh",
                    ack_timeout_s=2.0,
                    retries=0,
                )
                == "released"
            )
            assert await ledger.outbox_delivery_state(fourth) == "pending"

            ack_events = [
                e
                for e in main_events
                if e.get("event_type") == "nekoclaw_delivery_barrier_ack"
            ]
            assert len(ack_events) >= 8
            assert {str(e.get("result") or "") for e in ack_events} >= {
                "claimed",
                "committed",
                "released",
                "stale_epoch",
            }
        finally:
            bus.set_main_bridge(None)
            if restarted_main is not None:
                await restarted_main.stop()
            if main is not None:
                await main.stop()
            await agent.stop()
            await ledger.close()


async def _state_is(ledger, item_id: int, expected: str) -> bool:
    return await ledger.outbox_delivery_state(item_id) == expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_run(args.neko_root))
    print("native delivery receipt real-ZMQ E2E: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
