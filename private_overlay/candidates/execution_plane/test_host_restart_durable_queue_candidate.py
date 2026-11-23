from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host.ledger import Ledger
from nekoclaw.host.task_agents import (
    _Found,
    _Handed,
    _Unsaid,
    _queue_text_from_payload,
    _queue_text_payload,
)
from tests.unit.nekoclaw.host_fakes import FakeDecisionLLM, fake_model, make_host, wait_until


def _hard_kill_queue(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    db = tmp_path / "queued-hard-kill.db"
    marker = tmp_path / "queued-hard-kill.json"
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
            "queued",
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
                pytest.fail(f"fault child exited early: {stdout}\n{stderr}")
            if time.monotonic() >= deadline:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
                pytest.fail(f"fault child checkpoint timeout: {stdout}\n{stderr}")
            time.sleep(0.05)
        snapshot = json.loads(marker.read_text(encoding="utf-8"))
        proc.kill()
        proc.wait(timeout=5)
        return db, snapshot
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


async def _prepared_queue(
    root: Path,
    *,
    resume: dict[str, Any] | None = None,
    invalid_resume: bool = False,
    cancel: bool = False,
) -> str:
    ledger = Ledger(root / "ledger.db")
    try:
        commission, created = await ledger.create(
            lanlan_name="Lan",
            title="durable restart queue",
            dispatch_text="initial queued work",
            user_text="initial queued work",
            source="dispatch",
        )
        assert created
        await ledger.update(commission.id, route="task_agent")
        if resume is not None or invalid_resume:
            assert (await ledger.transition(commission.id, "working", reason="first run")).applied
            assert (await ledger.transition(commission.id, "blocked", reason="waiting to resume")).applied
            await ledger.append_event(
                commission.id,
                "restart_queue_resume",
                {"resume": {"text": "bad", "provenance": "not-a-real-kind"} if invalid_resume else resume},
            )
            assert (
                await ledger.transition(
                    commission.id,
                    "queued",
                    reason="taken up again; waiting for a place",
                )
            ).applied
        if cancel:
            assert (
                await ledger.transition(
                    commission.id,
                    "cancelled",
                    reason="user cancelled before restart recovery",
                )
            ).applied
        return commission.id
    finally:
        await ledger.close()


def _recovery_host(root: Path) -> Any:
    return make_host(
        root.parent,
        None,
        root=root,
        task_agent_model=fake_model,
        decision_llm=FakeDecisionLLM(),
        max_task_agents=0,
    )


@pytest.mark.parametrize(
    "value",
    [
        "plain user continuation",
        _Found("model finding"),
        _Handed("wake delivery", [3, 9]),
        _Unsaid("copy answer", "recipient-session"),
    ],
)
def test_queue_resume_round_trip_preserves_native_provenance(value: str) -> None:
    if isinstance(value, _Unsaid):
        value.retried = True
    restored = _queue_text_from_payload(_queue_text_payload(value))
    assert restored is not None
    assert str(restored) == str(value)
    assert type(restored) is type(value)
    if isinstance(value, _Handed):
        assert restored.wakes == value.wakes
    if isinstance(value, _Unsaid):
        assert restored.recipient == value.recipient
        assert restored.retried is True


@pytest.mark.asyncio
async def test_hard_kill_keeps_initial_task_agent_queue_durable(tmp_path: Path) -> None:
    db, snapshot = _hard_kill_queue(tmp_path)
    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.route == "task_agent"
        assert commission.status == "queued"
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_restart_reconstructs_initial_queue_with_same_native_session_identity(tmp_path: Path) -> None:
    root = tmp_path / "initial-root"
    commission_id = await _prepared_queue(root)
    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: host.task_agents.queued == [commission_id],
            what="initial queued commission to be reconstructed",
        )
        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "queued"
        assert current.session_id == commission_id
        assert host.task_agents._session_of[commission_id] == commission_id
        assert commission_id not in host.task_agents._resume
    finally:
        await host.abort(commission_id, reason="test cleanup")
        await host.shutdown()


@pytest.mark.asyncio
async def test_restart_reconstructs_exact_resume_provenance_without_new_identity(tmp_path: Path) -> None:
    root = tmp_path / "resume-root"
    payload = _queue_text_payload(_Handed("continue after wake", [11, 12]))
    commission_id = await _prepared_queue(root, resume=payload)
    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: host.task_agents.queued == [commission_id],
            what="requeued commission to be reconstructed",
        )
        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "queued"
        assert current.session_id == commission_id
        restored = host.task_agents._resume[commission_id]
        assert isinstance(restored, _Handed)
        assert str(restored) == "continue after wake"
        assert restored.wakes == (11, 12)
    finally:
        await host.abort(commission_id, reason="test cleanup")
        await host.shutdown()


@pytest.mark.asyncio
async def test_invalid_or_missing_retake_provenance_blocks_instead_of_replaying(tmp_path: Path) -> None:
    root = tmp_path / "bad-root"
    commission_id = await _prepared_queue(root, invalid_resume=True)
    host = _recovery_host(root)
    try:
        host.start()

        async def blocked() -> bool:
            row = await host.ledger.get(commission_id)
            return row is not None and row.status == "blocked"

        await wait_until(blocked, what="invalid queue provenance to block")
        current = await host.ledger.get(commission_id)
        assert current is not None
        assert current.status == "blocked"
        assert "provenance is not recoverable" in current.status_reason
        assert commission_id not in host.task_agents.queued
        assert commission_id not in host.task_agents.running
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_cancelled_queue_is_never_recovered_or_revived(tmp_path: Path) -> None:
    root = tmp_path / "cancel-root"
    commission_id = await _prepared_queue(root, cancel=True)
    host = _recovery_host(root)
    try:
        host.start()
        await host.task_agents.settle()
        current = await host.ledger.get(commission_id)
        assert current is not None
        assert current.status == "cancelled"
        assert current.status_reason == "user cancelled before restart recovery"
        assert commission_id not in host.task_agents.queued
        assert commission_id not in host.task_agents.running
    finally:
        await host.shutdown()
