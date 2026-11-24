from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host import call_audit
from nekoclaw.host.ledger import HOST_RESTART_UNCERTAIN_REASON, Ledger


def _hard_kill(tmp_path: Path, state: str) -> tuple[Path, dict[str, Any]]:
    db = tmp_path / f"{state}.db"
    marker = tmp_path / f"{state}.json"
    child = Path(__file__).with_name("host_restart_fault_child.py")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(child),
            "--db",
            str(db),
            "--marker",
            str(marker),
            "--state",
            state,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15.0
        while not marker.exists():
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=2)
                pytest.fail(
                    f"fault child exited before checkpoint: state={state} "
                    f"code={proc.returncode}\nstdout={stdout}\nstderr={stderr}"
                )
            if time.monotonic() >= deadline:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
                pytest.fail(
                    f"fault child did not commit checkpoint: state={state}\n"
                    f"stdout={stdout}\nstderr={stderr}"
                )
            time.sleep(0.05)
        snapshot = json.loads(marker.read_text(encoding="utf-8"))
        proc.kill()
        proc.wait(timeout=5)
        return db, snapshot
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_hard_kill_active_task_agent_becomes_blocked_uncertain(tmp_path: Path) -> None:
    db, snapshot = _hard_kill(tmp_path, "working")
    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.status == "blocked"
        assert commission.status_reason == HOST_RESTART_UNCERTAIN_REASON
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "call_status"),
    [
        ("call-running-device", "interrupted"),
        ("call-running-plugin", "interrupted"),
        ("call-completed-device", "completed"),
        ("call-completed-plugin", "completed"),
    ],
)
async def test_hard_kill_effect_boundary_blocks_without_losing_call_identity(
    tmp_path: Path,
    state: str,
    call_status: str,
) -> None:
    db, snapshot = _hard_kill(tmp_path, state)
    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.status == "blocked"
        assert commission.status_reason == HOST_RESTART_UNCERTAIN_REASON

        trace = await reopened.run(
            lambda conn: call_audit.read_trace(
                conn,
                commission.id,
                now=reopened._clock(),
            )
        )
        exact = [row for row in trace if row["call_id"] == snapshot["call_id"]]
        assert len(exact) == 1
        assert exact[0]["kind"] == snapshot["call_kind"]
        assert exact[0]["status"] == call_status
        assert all(row["status"] != "running" for row in trace)
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_resting_task_agent_keeps_native_durable_wake_semantics(tmp_path: Path) -> None:
    db, snapshot = _hard_kill(tmp_path, "working-resting")
    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.status == "working"
        assert commission.resting_since is not None
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_plugin_route_working_keeps_existing_restart_policy(tmp_path: Path) -> None:
    db, snapshot = _hard_kill(tmp_path, "working-plugin-route")
    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.route == "plugin"
        assert commission.status == "failed"
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_existing_blocked_and_cancelled_states_are_not_rewritten(tmp_path: Path) -> None:
    blocked_db, blocked_snapshot = _hard_kill(tmp_path, "blocked")
    blocked_ledger = Ledger(blocked_db)
    try:
        blocked = await blocked_ledger.get(str(blocked_snapshot["commission_id"]))
        assert blocked is not None
        assert blocked.status == "blocked"
        assert blocked.status_reason == "fault injector blocked"
    finally:
        await blocked_ledger.close()

    cancelled_db, cancelled_snapshot = _hard_kill(tmp_path, "cancelled-from-wait")
    cancelled_ledger = Ledger(cancelled_db)
    try:
        cancelled = await cancelled_ledger.get(str(cancelled_snapshot["commission_id"]))
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.status_reason == "user cancelled before host death"
    finally:
        await cancelled_ledger.close()
