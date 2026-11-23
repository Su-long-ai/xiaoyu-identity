from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host.ledger import Ledger
from tests.unit.nekoclaw.host_fakes import make_host


async def _waiting(
    ledger: Ledger,
    *,
    kind: str,
    question_id: str,
) -> str:
    commission, created = await ledger.create(
        lanlan_name="Lan",
        title=f"restart {kind}",
        dispatch_text=f"restart {kind}",
        user_text=f"restart {kind}",
        source="dispatch",
    )
    assert created
    await ledger.update(commission.id, route="task_agent")
    assert (await ledger.transition(commission.id, "working", reason="started")).applied
    question: dict[str, Any]
    if kind == "permission":
        question = {
            "kind": "permission",
            "id": question_id,
            "category": "outside_read",
            "key": None,
            "detail": {"path": "D:/restart-answer.txt"},
            "options": ["session", "once", "deny"],
        }
    else:
        question = {
            "kind": "report",
            "id": question_id,
            "question": "where should I continue?",
            "details": "",
        }
    assert (
        await ledger.transition(
            commission.id,
            "waiting_user",
            reason="waiting for user",
            pending_question=__import__("json").dumps(question),
        )
    ).applied
    return commission.id


@pytest.mark.asyncio
async def test_answer_is_durable_before_restart_resume_begins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)

    async def interrupted_before_resume(_commission_id: str, _text: str, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(host.task_agents, "_take_up_again", interrupted_before_resume)
    try:
        commission_id = await _waiting(
            host.ledger,
            kind="permission",
            question_id="permission-answer-commit",
        )
        await host.permission_store.set_mode("outside_read", "first_ask")

        # This models the crash boundary immediately after the durable write:
        # the native resume seam is unavailable, but the accepted answer must
        # already be on disk and must not mint old-host permission authority.
        assert await host.answer(
            commission_id,
            "yes, continue",
            choice="session",
            question_id="permission-answer-commit",
        ) is False

        events = await host.ledger.events(commission_id)
        kinds = [event.type for event in events]
        answered = [event for event in events if event.type == "answered"]
        envelopes = [event for event in events if event.type == "restart_answer_received"]
        assert len(answered) == 1
        assert len(envelopes) == 1
        assert kinds.index("answered") + 1 == kinds.index("restart_answer_received")
        assert answered[0].payload["question_id"] == "permission-answer-commit"
        assert envelopes[0].payload["question_id"] == "permission-answer-commit"
        assert "old permission answer was not restored as a grant" in envelopes[0].payload["continuation"]

        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "waiting_user"
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
        assert await host.permission_store.mode("outside_read") == "first_ask"
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_first_use_consumes_committed_report_answer_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "nekoclaw" / "ledger.db"
    first = Ledger(db)
    commission_id = await _waiting(
        first,
        kind="report",
        question_id="report-answer-commit",
    )
    await first.append_events(
        commission_id,
        [
            (
                "answered",
                {
                    "text": "continue from D:/Camera",
                    "resumed": True,
                    "question_id": "report-answer-commit",
                },
            ),
            (
                "restart_answer_received",
                {
                    "question_id": "report-answer-commit",
                    "kind": "report",
                    "continuation": "continue from D:/Camera",
                },
            ),
        ],
    )
    await first.close()

    host = make_host(tmp_path, None)
    resumed: list[tuple[str, str]] = []

    async def take_up_again(cid: str, text: str, **_kwargs: Any) -> bool:
        resumed.append((cid, text))
        moved = await host.ledger.transition(
            cid,
            "queued",
            reason="accepted answer recovered after restart",
            only_from=("waiting_user",),
        )
        return moved.applied

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        # NekoClawHost.start() is the read-only caller's first-use path. The
        # recovery consumer is started there just like outbox/wake delivery.
        host.start()
        await host.task_agents.settle()

        assert resumed == [(commission_id, "continue from D:/Camera")]
        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "queued"
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_duplicate_answer_after_restart_uses_first_durable_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)
    resumed: list[str] = []

    async def take_up_again(cid: str, text: str, **_kwargs: Any) -> bool:
        resumed.append(text)
        moved = await host.ledger.transition(
            cid,
            "queued",
            reason="resume durable accepted answer",
            only_from=("waiting_user",),
        )
        return moved.applied

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id = await _waiting(
            host.ledger,
            kind="report",
            question_id="same-question",
        )
        await host.ledger.append_event(
            commission_id,
            "restart_answer_received",
            {
                "question_id": "same-question",
                "kind": "report",
                "continuation": "the answer accepted before the crash",
            },
        )

        assert await host.answer(
            commission_id,
            "a later duplicate must not replace it",
            question_id="same-question",
        )
        assert resumed == ["the answer accepted before the crash"]

        envelopes = [
            event
            for event in await host.ledger.events(commission_id)
            if event.type == "restart_answer_received"
        ]
        assert len(envelopes) == 1
    finally:
        await host.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["cancelled", "failed", "done"])
async def test_restart_answer_recovery_never_revives_terminal_commission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    db = tmp_path / "nekoclaw" / "ledger.db"
    first = Ledger(db)
    commission_id = await _waiting(
        first,
        kind="report",
        question_id="terminal-question",
    )
    await first.append_event(
        commission_id,
        "restart_answer_received",
        {
            "question_id": "terminal-question",
            "kind": "report",
            "continuation": "must never run",
        },
    )
    if terminal == "done":
        assert (await first.transition(commission_id, "working", reason="answer consumed")).applied
        assert (await first.transition(commission_id, "done", reason="finished")).applied
    else:
        assert (await first.transition(commission_id, terminal, reason="terminal won")).applied
    await first.close()

    host = make_host(tmp_path, None)
    resumed: list[str] = []

    async def take_up_again(_cid: str, text: str, **_kwargs: Any) -> bool:
        resumed.append(text)
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        host.start()
        await host.task_agents.settle()
        assert resumed == []
        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == terminal
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_restart_answer_recovery_ignores_stale_question_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "nekoclaw" / "ledger.db"
    first = Ledger(db)
    commission_id = await _waiting(
        first,
        kind="report",
        question_id="current-question",
    )
    await first.append_event(
        commission_id,
        "restart_answer_received",
        {
            "question_id": "older-question",
            "kind": "report",
            "continuation": "stale answer",
        },
    )
    await first.close()

    host = make_host(tmp_path, None)
    resumed: list[str] = []

    async def take_up_again(_cid: str, text: str, **_kwargs: Any) -> bool:
        resumed.append(text)
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        host.start()
        await host.task_agents.settle()
        assert resumed == []
        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "waiting_user"
        assert current.question() is not None
        assert current.question()["id"] == "current-question"
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_permission_answer_auto_recovery_restores_no_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "nekoclaw" / "ledger.db"
    first = Ledger(db)
    commission_id = await _waiting(
        first,
        kind="permission",
        question_id="permission-recovery",
    )
    await first.append_event(
        commission_id,
        "restart_answer_received",
        {
            "question_id": "permission-recovery",
            "kind": "permission",
            "continuation": (
                "The host restarted while permission was pending. The protected tool did not run. "
                "The old permission answer was not restored as a grant. If the action is still needed, "
                "call the tool again; the current host must check permission again."
            ),
        },
    )
    await first.close()

    host = make_host(tmp_path, None)
    await host.permission_store.set_mode("outside_read", "first_ask")
    resumed: list[str] = []

    async def take_up_again(cid: str, text: str, **_kwargs: Any) -> bool:
        resumed.append(text)
        moved = await host.ledger.transition(
            cid,
            "queued",
            reason="permission answer recovered",
            only_from=("waiting_user",),
        )
        return moved.applied

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        host.start()
        await host.task_agents.settle()
        assert len(resumed) == 1
        assert "current host must check permission again" in resumed[0]
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
        assert await host.permission_store.mode("outside_read") == "first_ask"
    finally:
        await host.shutdown()
