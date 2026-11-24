#!/usr/bin/env python3
"""Verify the NekoPower plugin-run idempotency migration candidate."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


class _Response:
    def __init__(self, status: int, payload=None, broken: bool = False):
        self.status_code = status
        self.payload = payload
        self.broken = broken

    def json(self):
        if self.broken:
            raise ValueError("lost response body")
        return self.payload


class _State:
    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies: list[dict] = []


class _Client:
    def __init__(self, state: _State):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, _url, json):
        self.state.bodies.append(dict(json))
        reply = self.state.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


async def _run_case(PluginRunner, body: dict, replies):
    state = _State(replies)
    runner = PluginRunner(
        None,
        base_url="http://candidate.invalid",
        client_factory=lambda **_kwargs: _Client(state),
        poll_interval=0,
    )
    answer, problem = await runner._create_run(dict(body))
    return state, answer, problem


async def _verify() -> None:
    from nekopower.host.plugin_runs import PluginRunner

    success = {"run_id": "r1", "run_token": "t1", "expires_at": 1}
    keyed = {"plugin_id": "p", "entry_id": "e", "args": {}, "idempotency_key": "call-1"}

    state, answer, problem = await _run_case(
        PluginRunner, keyed, [_Response(503), _Response(200, success)]
    )
    assert problem is None and answer["run_id"] == "r1"
    assert len(state.bodies) == 2
    assert {body["idempotency_key"] for body in state.bodies} == {"call-1"}

    state, answer, problem = await _run_case(
        PluginRunner, keyed, [_Response(200, broken=True), _Response(200, success)]
    )
    assert problem is None and len(state.bodies) == 2

    state, answer, problem = await _run_case(
        PluginRunner, keyed, [OSError("lost"), _Response(200, success)]
    )
    assert problem is None and len(state.bodies) == 2

    plain = {"plugin_id": "p", "entry_id": "e", "args": {}}
    state, answer, problem = await _run_case(
        PluginRunner, plain, [_Response(503), _Response(200, success)]
    )
    assert answer is None and problem[1] == "run_failed"
    assert len(state.bodies) == 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.neko_root.resolve()
    sys.path.insert(0, str(root))

    source = (root / "nekopower/host/plugin_runs.py").read_text(encoding="utf-8")
    assert 'body["idempotency_key"] = call_id' in source
    assert "attempts = 2 if idempotent else 1" in source
    asyncio.run(_verify())
    print("NekoPower plugin-run idempotency candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
