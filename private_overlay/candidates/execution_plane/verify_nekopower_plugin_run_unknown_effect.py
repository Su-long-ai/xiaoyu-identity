#!/usr/bin/env python3
"""Verify the NekoPower unknown-plugin-effect migration candidate."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _source(root: Path, relative: str) -> str:
    path = root / relative
    assert path.is_file(), f"missing candidate file: {relative}"
    return path.read_text(encoding="utf-8")


async def _verify_polling() -> None:
    from nekopower.host.plugin_runs import PluginRunner, plugin_terminal_status

    assert plugin_terminal_status(False, None, run_status="unknown") == "blocked"
    assert plugin_terminal_status(False, None, run_status="failed") == "failed"

    class Response:
        status_code = 503

        def json(self):
            return {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url):
            return Response()

    def client_factory(**_kwargs):
        return Client()

    runner = PluginRunner(
        None,
        base_url="http://candidate.invalid",
        client_factory=client_factory,
        poll_interval=0,
    )
    result = await runner._await_completion(
        "run-ambiguous",
        timeout=2,
        on_progress=None,
    )
    assert result["status"] == "unknown", result
    assert result["success"] is False, result
    assert result["lost"] is True, result


def _verify_sources(root: Path) -> None:
    plugin_runs = _source(root, "nekopower/host/plugin_runs.py")
    task_brain = _source(root, "nekopower/host/task_brain.py")
    gateway = _source(root, "nekopower/host/gateway.py")

    assert plugin_runs.count('"status": "unknown"') >= 3
    assert 'else "effect_uncertain"' in plugin_runs
    assert 'run_status == "unknown"' in plugin_runs

    assert "Effect uncertain; do not repeat this action automatically." in task_brain
    assert 'status="blocked"' in task_brain
    assert 'run_status=getattr(outcome, "status", None)' in task_brain

    assert "Do not repeat the same action automatically" in gateway
    assert 'run_status == "unknown"' in gateway
    assert 'plugin_run_ended' in gateway


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", type=Path, required=True)
    args = parser.parse_args()

    root = args.neko_root.resolve()
    sys.path.insert(0, str(root))
    _verify_sources(root)
    asyncio.run(_verify_polling())
    print("NekoPower plugin unknown-effect candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
