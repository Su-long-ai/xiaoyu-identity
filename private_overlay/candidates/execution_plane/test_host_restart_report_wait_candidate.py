from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host.ledger import Ledger
from tests.unit.nekoclaw.fakes import ScriptedLLM
from tests.unit.nekoclaw.test_host_task_agents import (
    _events,
    _host,
    _report,
    _waiting_and_closed,
)
from tests.unit.nekoclaw.host_fakes import wait_status


async def _waiting_row(path: Path, *, kind: str) -> tuple[str, int]:
    ledger = Ledger(path)
    commission, created = await ledger.create(
        lanlan_name="Lan",
        title="sort the photos",
        dispatch_text="sort the photos",
        user_text="sort the photos",
        source="dispatch",
    )
    assert created
    await ledger.update(commission.id, route="task_agent")
    assert (await ledger.transition(commission.id, "working", reason="started")).applied
    question = {
        "kind": kind,
        "id": f"{kind}-question-1",
        "question": "Which folder holds the photos?",
        "details": "",
    }
    assert (
        await ledger.transition(
            commission.id,
            "waiting_user",
            reason="waiting for the user",
            pending_question=json.dumps(question),
        )
    ).applied
    outbox_id = await ledger.outbox_add(
        commission.id,
        "question",
        {"task_id": commission.id, "question": question},
    )
    await ledger.close()
    return commission.id, outbox_id


@pytest.mark.asyncio
async def test_reopen_preserves_report_wait_and_its_unsent_native_question(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    commission_id, outbox_id = await _waiting_row(path, kind="report")

    reopened = Ledger(path)
    try:
        kept = await reopened.get(commission_id)
        assert kept is not None
        assert kept.status == "waiting_user"
        assert kept.question() == {
            "kind": "report",
            "id": "report-question-1",
            "question": "Which folder holds the photos?",
            "details": "",
        }
        assert await reopened.outbox_question_state(outbox_id) == "current"
        pending = await reopened.outbox_pending()
        assert [row.id for row in pending] == [outbox_id]
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["permission", "tool"])
async def test_reopen_still_fails_question_types_without_a_native_resume_continuation(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / f"{kind}.db"
    commission_id, outbox_id = await _waiting_row(path, kind=kind)

    reopened = Ledger(path)
    try:
        ended = await reopened.get(commission_id)
        assert ended is not None
        assert ended.status == "failed"
        assert ended.status_reason == "the host process ended before this finished"
        assert await reopened.outbox_question_state(outbox_id) == "gone"
        # A reconcile failure report is optional here because this bare Ledger
        # has no reporter hook. The stale question itself must not survive.
        assert all(row.id != outbox_id for row in await reopened.outbox_pending())
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_new_host_answers_preserved_report_wait_at_the_existing_transcript_tail(
    tmp_path: Path,
) -> None:
    hosts: list[Any] = []
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    first_llm = ScriptedLLM([_report("waiting", "Which folder holds the photos?")])
    old = _host(hosts, old_root, first_llm)
    try:
        commission_id = await asyncio.wait_for(_waiting_and_closed(old, "sort the photos"), 10)
        old_commission = await old.ledger.get(commission_id)
        assert old_commission is not None
        question = old_commission.question()
        assert question is not None and question["kind"] == "report"
        assert not old.task_agents.running

        # Snapshot the durable on-disk state while the original process is
        # notionally lost. The closed runtime no longer owns the transcript.
        new_db = new_root / "nekoclaw" / "ledger.db"
        new_db.parent.mkdir(parents=True, exist_ok=True)

        def backup() -> None:
            # Simulate another host process taking a durable database snapshot.
            # Do not call sqlite backup while holding Ledger.run's own
            # connection/transaction; on Windows that can wait on itself.
            source = sqlite3.connect(old_root / "nekoclaw" / "ledger.db")
            target = sqlite3.connect(new_db)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()

        await asyncio.wait_for(asyncio.to_thread(backup), 10)

        resumed_llm = ScriptedLLM([_report("ready", "sorted D:/Camera")])
        new = _host(hosts, new_root, resumed_llm)

        # Merely opening the new host/ledger must not start a model turn or
        # replay an effect.
        assert not new.task_agents.runtime_started
        preserved = await new.ledger.get(commission_id)
        assert preserved is not None and preserved.status == "waiting_user"
        assert not new.task_agents.runtime_started
        assert resumed_llm.requests == []

        assert await asyncio.wait_for(
            new.answer(
                commission_id,
                "the photos are in D:/Camera",
                question_id=str(question["id"]),
            ),
            10,
        )

        done = await wait_status(new, commission_id, "done", timeout=10)
        assert done.result_summary == "sorted D:/Camera"
        assert done.session_dir == old_commission.session_dir
        assert {"role": "user", "content": "the photos are in D:/Camera"} in resumed_llm.requests[0]
        started = await _events(new, commission_id, "started")
        assert [event.payload["resumed"] for event in started] == [False, True]
    finally:
        for host in reversed(hosts):
            try:
                await host.shutdown()
            except Exception:
                pass
