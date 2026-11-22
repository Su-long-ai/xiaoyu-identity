from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nekoclaw.host import call_audit
from tests.unit.nekoclaw.host_fakes import FakeDecisionLLM, make_host, outbox, pick_plugin, wait_status
from tests.unit.nekoclaw.plugin_server_fake import FakePluginServer, entry, finish, plugin


@pytest.fixture
def server(monkeypatch: Any) -> FakePluginServer:
    return FakePluginServer.install(monkeypatch)


async def _effect_then_unknown(
    host: Any,
    effect_seen: asyncio.Event,
) -> None:
    original = host.runner._await_completion

    async def unreadable_after_effect(
        run_id: str,
        *,
        timeout: float | None,
        on_progress: Any,
    ) -> dict[str, Any]:
        del timeout, on_progress
        await asyncio.wait_for(effect_seen.wait(), 2)
        return {
            "status": "unknown",
            "success": False,
            "data": None,
            "error": f"Run {run_id} polling failed (3 consecutive transport errors)",
            "lost": True,
        }

    host.runner._await_completion = unreadable_after_effect
    host.runner._candidate_original_await_completion = original


async def _close(host: Any) -> None:
    await host.shutdown()


@pytest.mark.asyncio
async def test_direct_effect_that_happened_but_became_unreadable_is_blocked(
    server: FakePluginServer, tmp_path: Any
) -> None:
    effect_seen = asyncio.Event()
    effects: list[str] = []

    async def switch(_args: dict[str, Any]) -> dict[str, Any]:
        effects.append("off")
        effect_seen.set()
        return finish({"reply": "lamp is off"})

    server.add_plugin(
        plugin("lamp", "Desk lamp", [entry("switch", "Switch the desk lamp")], keywords=["lamp"]),
        switch=switch,
    )
    host = make_host(
        tmp_path,
        server,
        decision_llm=FakeDecisionLLM(fine=[pick_plugin("lamp", "switch")]),
    )
    await _effect_then_unknown(host, effect_seen)
    try:
        receipt = await host.dispatch("turn the lamp off", lanlan_name="Lan", lang="en")
        blocked = await wait_status(host, receipt.commission_id, "blocked")

        assert effects == ["off"]
        assert blocked.status == "blocked"
        assert "Effect uncertain; do not repeat this action automatically." in blocked.result_summary
        reports = await outbox(host, "task_result")
        assert len(reports) == 1
        assert reports[0].payload["status"] == "blocked"
        assert reports[0].payload["success"] is False

        trace = await host.ledger.run(
            lambda db: call_audit.read_trace(db, blocked.id, now=host.ledger._clock())
        )
        plugin_calls = [item for item in trace if item["kind"] == "plugin"]
        assert len(plugin_calls) == 1
        assert plugin_calls[0]["status"] == "blocked"
    finally:
        await _close(host)


@pytest.mark.asyncio
async def test_gateway_unknown_effect_is_non_error_and_says_not_to_repeat(
    server: FakePluginServer, tmp_path: Any
) -> None:
    effect_seen = asyncio.Event()
    effects: list[str] = []

    async def send(_args: dict[str, Any]) -> dict[str, Any]:
        effects.append("sent")
        effect_seen.set()
        return finish({"reply": "message sent"})

    server.add_plugin(
        plugin("sender", "Sender", [entry("send", "Send a message")]),
        send=send,
    )
    host = make_host(tmp_path, server, decision_llm=FakeDecisionLLM())
    await _effect_then_unknown(host, effect_seen)
    try:
        commission, _created = await host.ledger.create(
            lanlan_name="Lan",
            title="send it",
            dispatch_text="send it",
            user_text="send it",
            source="dispatch",
            route="task_agent",
            conversation_id="conv-unknown-effect",
            lang="en",
        )
        await host.ledger.transition(commission.id, "working")
        token = host.gateway.issue(commission.id, candidate_plugin_ids=("sender",))
        grant = host.gateway._grant(token)
        assert grant is not None

        answer = await host.gateway.handle(
            grant,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "plugin__sender__send", "arguments": {}},
            },
        )
        result = answer["result"]
        text = "\n".join(item["text"] for item in result["content"])

        assert effects == ["sent"]
        assert result["isError"] is False
        assert "Effect uncertain" in text
        assert "Do not repeat the same action automatically" in text

        events = await host.ledger.events(commission.id)
        ended = [event for event in events if event.type == "plugin_run_ended"]
        assert len(ended) == 1
        assert ended[0].payload["status"] == "unknown"
        assert ended[0].payload["result"] == "blocked"

        trace = await host.ledger.run(
            lambda db: call_audit.read_trace(db, commission.id, now=host.ledger._clock())
        )
        plugin_calls = [item for item in trace if item["kind"] == "plugin"]
        assert len(plugin_calls) == 1
        assert plugin_calls[0]["status"] == "blocked"
    finally:
        await _close(host)
