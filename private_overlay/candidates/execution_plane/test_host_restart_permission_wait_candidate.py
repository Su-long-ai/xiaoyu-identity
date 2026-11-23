from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host.ledger import Ledger
from tests.unit.nekoclaw.host_fakes import make_host


def _permission_question(question_id: str = "permission-question-1") -> dict[str, Any]:
    return {
        "kind": "permission",
        "id": question_id,
        "category": "outside_read",
        "key": None,
        "detail": {"path": "D:/fixture.txt"},
        "options": ["always", "session", "once", "deny"],
    }


async def _waiting_permission_row(path: Path, *, route: str) -> tuple[str, int]:
    ledger = Ledger(path)
    commission, created = await ledger.create(
        lanlan_name="Lan",
        title="read the fixture",
        dispatch_text="read the fixture",
        user_text="read the fixture",
        source="dispatch",
    )
    assert created
    await ledger.update(commission.id, route=route)
    assert (await ledger.transition(commission.id, "working", reason="started")).applied
    question = _permission_question()
    assert (
        await ledger.transition(
            commission.id,
            "waiting_user",
            reason="waiting for permission",
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
async def test_restart_preserves_only_task_agent_permission_wait(tmp_path: Path) -> None:
    task_db = tmp_path / "task-agent.db"
    plugin_db = tmp_path / "direct-plugin.db"
    task_id, task_question = await _waiting_permission_row(task_db, route="task_agent")
    plugin_id, plugin_question = await _waiting_permission_row(plugin_db, route="plugin")

    task_reopened = Ledger(task_db)
    plugin_reopened = Ledger(plugin_db)
    try:
        kept = await task_reopened.get(task_id)
        assert kept is not None and kept.status == "waiting_user"
        assert kept.question()["kind"] == "permission"
        assert await task_reopened.outbox_question_state(task_question) == "current"

        failed = await plugin_reopened.get(plugin_id)
        assert failed is not None and failed.status == "failed"
        assert failed.status_reason == "the host process ended before this finished"
        assert await plugin_reopened.outbox_question_state(plugin_question) == "gone"
    finally:
        await task_reopened.close()
        await plugin_reopened.close()


async def _host_waiting_permission(host: Any) -> tuple[str, dict[str, Any]]:
    commission, created = await host.ledger.create(
        lanlan_name="Lan",
        title="read the fixture",
        dispatch_text="read the fixture",
        user_text="read the fixture",
        source="dispatch",
    )
    assert created
    await host.ledger.update(commission.id, route="task_agent")
    assert (await host.ledger.transition(commission.id, "working", reason="started")).applied
    question = _permission_question()
    assert (
        await host.ledger.transition(
            commission.id,
            "waiting_user",
            reason="waiting for permission",
            pending_question=json.dumps(question),
        )
    ).applied
    return commission.id, question


@pytest.mark.asyncio
async def test_recovered_permission_answer_restores_no_grant_or_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)
    captured: list[tuple[str, str, bool]] = []

    async def take_up_again(
        commission_id: str,
        text: str,
        *,
        same_round: bool = False,
        **_kwargs: Any,
    ) -> bool:
        captured.append((commission_id, text, same_round))
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id, question = await _host_waiting_permission(host)
        await host.permission_store.set_mode("outside_read", "first_ask")
        before = await host.permission_store.mode("outside_read")

        accepted = await host.answer(
            commission_id,
            "yes, continue",
            choice="always",
            question_id=str(question["id"]),
        )

        assert accepted is True
        assert before == await host.permission_store.mode("outside_read") == "first_ask"
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
        assert len(captured) == 1 and captured[0][0] == commission_id and captured[0][2] is True
        continuation = captured[0][1]
        assert "protected tool did not run" in continuation
        assert "old permission answer was not restored as a grant" in continuation
        assert "current host must check permission again" in continuation

        answered = [
            event for event in await host.ledger.events(commission_id)
            if event.type == "answered"
        ]
        assert answered and answered[-1].payload["resumed"] is True
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_recovered_deny_restores_no_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)
    continuations: list[str] = []

    async def take_up_again(_commission_id: str, text: str, **_kwargs: Any) -> bool:
        continuations.append(text)
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id, question = await _host_waiting_permission(host)
        await host.permission_store.set_mode("outside_read", "first_ask")

        assert await host.answer(
            commission_id,
            "no",
            choice="deny",
            question_id=str(question["id"]),
        )
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
        assert await host.permission_store.mode("outside_read") == "first_ask"
        assert len(continuations) == 1
        assert "user declined that permission" in continuations[0]
        assert "no permission grant survived the restart" in continuations[0]
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_next_protected_action_must_ask_current_permission_gate_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)

    async def take_up_again(_commission_id: str, _text: str, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id, question = await _host_waiting_permission(host)
        await host.permission_store.set_mode("outside_read", "first_ask")
        assert await host.answer(
            commission_id,
            "yes",
            choice="session",
            question_id=str(question["id"]),
        )

        # Recovery itself minted no authorization.
        assert host.permissions.session_grants(commission_id) == frozenset()
        asks: list[tuple[str, str]] = []

        async def current_asker(cid: str, ask: Any) -> str:
            asks.append((cid, ask.category))
            return "session"

        host.permissions.set_asker(current_asker)
        decision = await host.permissions.check(
            commission_id,
            "outside_read",
            detail={"path": "D:/fixture.txt"},
        )

        assert decision.allow is True and decision.asked is True
        assert asks == [(commission_id, "outside_read")]
        assert host.permissions.session_grants(commission_id) == frozenset(
            {("outside_read", None)}
        )
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_stale_recovered_permission_question_id_is_rejected_without_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)
    resumed: list[str] = []

    async def take_up_again(_commission_id: str, text: str, **_kwargs: Any) -> bool:
        resumed.append(text)
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id, question = await _host_waiting_permission(host)
        await host.permission_store.set_mode("outside_read", "first_ask")

        assert await host.answer(
            commission_id,
            "yes",
            choice="session",
            question_id="permission-question-from-an-older-epoch",
        ) is False

        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "waiting_user"
        assert current.question() == question
        assert resumed == []
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
        assert await host.permission_store.mode("outside_read") == "first_ask"
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_cancelled_permission_wait_rejects_late_recovery_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)
    resumed: list[str] = []

    async def take_up_again(_commission_id: str, text: str, **_kwargs: Any) -> bool:
        resumed.append(text)
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id, question = await _host_waiting_permission(host)
        assert (
            await host.ledger.transition(
                commission_id,
                "cancelled",
                reason="explicit user stop won the restart race",
            )
        ).applied

        assert await host.answer(
            commission_id,
            "yes",
            choice="always",
            question_id=str(question["id"]),
        ) is False

        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "cancelled"
        assert current.status_reason == "explicit user stop won the restart race"
        assert resumed == []
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_recovered_permission_without_a_valid_choice_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host(tmp_path, None)
    continuations: list[str] = []

    async def take_up_again(_commission_id: str, text: str, **_kwargs: Any) -> bool:
        continuations.append(text)
        return True

    monkeypatch.setattr(host.task_agents, "_take_up_again", take_up_again)
    try:
        commission_id, question = await _host_waiting_permission(host)
        await host.permission_store.set_mode("outside_read", "first_ask")

        assert await host.answer(
            commission_id,
            "continue",
            choice=None,
            question_id=str(question["id"]),
        )
        assert len(continuations) == 1
        assert "user declined that permission" in continuations[0]
        assert host.permissions.run_grants(commission_id) == frozenset()
        assert host.permissions.session_grants(commission_id) == frozenset()
        assert await host.permission_store.mode("outside_read") == "first_ask"
    finally:
        await host.shutdown()
