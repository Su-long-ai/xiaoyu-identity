from __future__ import annotations

from typing import Any

import httpx
import pytest

from nekoclaw.host.plugin_runs import PluginCatalog, PluginRunner
from tests.unit.nekoclaw.plugin_server_fake import (
    PLUGIN_SERVER_URL,
    FakePluginServer,
    entry,
    finish,
    plugin,
)


class _Audit:
    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.bound: list[tuple[str, str]] = []

    async def bind_run(self, run_id: str, target: str) -> None:
        self.bound.append((run_id, target))


def _runner_with_lost_first_create(server: FakePluginServer) -> PluginRunner:
    class Client:
        lost = 1

        def __init__(self, **kwargs: Any) -> None:
            self._client = server.client(**kwargs)

        async def __aenter__(self) -> Any:
            await self._client.__aenter__()
            return self

        async def __aexit__(self, *exc: Any) -> Any:
            return await self._client.__aexit__(*exc)

        async def post(self, url: str, **kwargs: Any) -> Any:
            response = await self._client.post(url, **kwargs)
            if url.endswith("/runs") and type(self).lost:
                type(self).lost -= 1
                # The production plugin server has already created/started the
                # run. Only its HTTP response is lost.
                raise httpx.ReadError("accepted response lost")
            return response

        async def get(self, url: str, **kwargs: Any) -> Any:
            return await self._client.get(url, **kwargs)

    catalog = PluginCatalog(base_url=PLUGIN_SERVER_URL, client_factory=server.client)
    return PluginRunner(
        catalog,
        base_url=PLUGIN_SERVER_URL,
        client_factory=Client,
        default_entry_timeout=lambda: None,
        poll_interval=0.01,
    )


@pytest.mark.asyncio
async def test_lost_create_response_reuses_one_native_run(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakePluginServer.install(monkeypatch)
    effects: list[str] = []

    async def send(_args: dict[str, Any]) -> dict[str, Any]:
        effects.append("sent")
        return finish({"reply": "done"})

    server.add_plugin(
        plugin("sender", "Side-effect sender", [entry("send", "Send once")]),
        send=send,
    )
    runner = _runner_with_lost_first_create(server)
    audit = _Audit("host-call-stable-1")

    outcome = await runner.run_entry(
        commission_id="commission-1",
        plugin_id="sender",
        entry_id="send",
        args={"value": 1},
        audit_call=audit,
    )
    await server.settle()

    assert outcome.success is True
    assert len(server.run_requests) == 2
    assert [request.get("idempotency_key") for request in server.run_requests] == [
        "host-call-stable-1",
        "host-call-stable-1",
    ]
    assert effects == ["sent"]
    assert len(server.calls) == 1
    runs = server.runs()
    assert len(runs) == 1
    assert outcome.run_id == runs[0].run_id
    assert audit.bound == [(runs[0].run_id, "plugin:sender:send")]
    await runner.aclose()


@pytest.mark.asyncio
async def test_unkeyed_internal_call_does_not_blindly_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakePluginServer.install(monkeypatch)
    effects: list[str] = []

    async def send(_args: dict[str, Any]) -> dict[str, Any]:
        effects.append("sent")
        return finish({"reply": "done"})

    server.add_plugin(
        plugin("sender", "Side-effect sender", [entry("send", "Send once")]),
        send=send,
    )
    runner = _runner_with_lost_first_create(server)

    outcome = await runner.run_entry(
        commission_id="commission-1",
        plugin_id="sender",
        entry_id="send",
        args={"value": 1},
    )
    await server.settle()

    assert outcome.accepted is False
    assert outcome.reason == "run_failed"
    assert len(server.run_requests) == 1
    assert "idempotency_key" not in server.run_requests[0]
    assert effects == ["sent"]
    assert len(server.calls) == 1
    assert len(server.runs()) == 1
    await runner.aclose()
