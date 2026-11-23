from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host.ledger import Ledger, MessageLimits
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
    root.mkdir(parents=True, exist_ok=True)
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
        updated = await ledger.update(commission.id, route="task_agent")
        assert updated is not None
        commission = updated
        if resume is not None or invalid_resume:
            commission, _session = await ledger.give_session(
                commission.id,
                kind="single",
                name=commission.id,
                duty="durable restart queue",
            )
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
    unsaid = _Unsaid("continue from copied result", "recipient-session")
    unsaid.retried = True
    commission_id = await _prepared_queue(root, resume=_queue_text_payload(unsaid))
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
        assert isinstance(restored, _Unsaid)
        assert str(restored) == "continue from copied result"
        assert restored.recipient == "recipient-session"
        assert restored.retried is True
    finally:
        await host.abort(commission_id, reason="test cleanup")
        await host.shutdown()


@pytest.mark.asyncio
async def test_invalid_retake_provenance_fails_closed_without_replaying(tmp_path: Path) -> None:
    root = tmp_path / "bad-root"
    commission_id = await _prepared_queue(root, invalid_resume=True)
    host = _recovery_host(root)
    try:
        host.start()

        async def failed_closed() -> bool:
            row = await host.ledger.get(commission_id)
            return row is not None and row.status == "failed"

        await wait_until(failed_closed, what="invalid queue provenance to fail closed")
        current = await host.ledger.get(commission_id)
        assert current is not None
        assert current.status == "failed"
        assert "current queue cycle is missing or invalid" in current.status_reason
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


@pytest.mark.asyncio
async def test_pre_candidate_requeue_without_durable_resume_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "legacy-requeue-root"
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.db")
    try:
        commission, created = await ledger.create(
            lanlan_name="Lan",
            title="legacy requeue",
            dispatch_text="legacy work",
            user_text="legacy work",
            source="dispatch",
        )
        assert created
        commission = await ledger.update(commission.id, route="task_agent")
        assert commission is not None
        commission, _session = await ledger.give_session(
            commission.id, kind="single", name=commission.id, duty="legacy requeue"
        )
        assert (await ledger.transition(commission.id, "working", reason="first run")).applied
        assert (
            await ledger.transition(
                commission.id, "queued", reason="taken up again; waiting for a place"
            )
        ).applied
        commission_id = commission.id
    finally:
        await ledger.close()

    host = _recovery_host(root)
    try:
        host.start()

        async def failed_closed() -> bool:
            row = await host.ledger.get(commission_id)
            return row is not None and row.status == "failed"

        await wait_until(failed_closed, what="legacy requeue without continuation to fail closed")
        current = await host.ledger.get(commission_id)
        assert current is not None
        assert "durable continuation for the current queue cycle is missing or invalid" in current.status_reason
        assert commission_id not in host.task_agents.queued
    finally:
        await host.shutdown()


@pytest.mark.asyncio
async def test_orphan_resume_event_does_not_poison_initial_queue(tmp_path: Path) -> None:
    root = tmp_path / "orphan-root"
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.db")
    try:
        commission, created = await ledger.create(
            lanlan_name="Lan",
            title="initial queue with orphan",
            dispatch_text="initial",
            user_text="initial",
            source="dispatch",
        )
        assert created
        commission = await ledger.update(commission.id, route="task_agent")
        assert commission is not None
        await ledger.append_event(
            commission.id,
            "restart_queue_resume",
            {"resume": _queue_text_payload(_Found("must not leak into opening"))},
        )
        commission_id = commission.id
    finally:
        await ledger.close()

    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: commission_id in host.task_agents.queued,
            what="initial queue to be reconstructed",
        )
        current = await host.ledger.get(commission_id)
        assert current is not None and current.status == "queued"
        assert current.session_id == commission_id
        assert commission_id not in host.task_agents._resume
    finally:
        await host.abort(commission_id, reason="test cleanup")
        await host.shutdown()


@pytest.mark.asyncio
async def test_wake_working_persists_resume_before_queued_transition(tmp_path: Path) -> None:
    root = tmp_path / "wake-working-root"
    host = _recovery_host(root)
    try:
        commission, created = await host.ledger.create(
            lanlan_name="Lan",
            title="wake working",
            dispatch_text="initial",
            user_text="initial",
            source="dispatch",
        )
        assert created
        commission = await host.ledger.update(commission.id, route="task_agent")
        assert commission is not None
        commission, _session = await host.ledger.give_session(
            commission.id, kind="single", name=commission.id, duty="wake working"
        )
        assert (await host.ledger.transition(commission.id, "working", reason="first run")).applied

        assert await host.task_agents._wake_working(
            commission.id,
            _Found("child result"),
            reason="child completed while session was closed",
        )

        events = await host.ledger.events(commission.id)
        resume = next(event for event in events if event.type == "restart_queue_resume")
        queued = next(
            event
            for event in events
            if event.type == "status" and event.payload.get("to") == "queued"
        )
        assert resume.seq < queued.seq
        assert resume.payload["resume"]["provenance"] == "found"
        assert resume.payload["resume"]["text"] == "child result"
    finally:
        await host.abort(commission.id, reason="test cleanup")
        await host.shutdown()


@pytest.mark.asyncio
async def test_handed_wake_uses_native_wake_ids_once_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "handed-wake-root"
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.db")
    try:
        commission, created = await ledger.create(
            lanlan_name="Lan",
            title="wake restart",
            dispatch_text="initial",
            user_text="initial",
            source="dispatch",
        )
        assert created
        commission = await ledger.update(commission.id, route="task_agent")
        assert commission is not None
        commission, session = await ledger.give_session(
            commission.id, kind="single", name=commission.id, duty="wake restart"
        )
        assert (await ledger.transition(commission.id, "working", reason="first run")).applied
        wake, refusal = await ledger.wake_add(
            session_id=session.id,
            commission_id=commission.id,
            note="native wake after restart",
            due_at=0.0,
            pending_max=10,
            daily_max=10,
        )
        assert refusal == "" and wake is not None
        fired = await ledger.wakes_fire([wake.id], into=commission.id)
        assert fired == [wake.id]
        await ledger.append_event(
            commission.id,
            "restart_queue_resume",
            {"resume": _queue_text_payload(_Handed("serialized wake must not replay", fired))},
        )
        assert (
            await ledger.transition(
                commission.id,
                "queued",
                reason="woken; waiting for a place",
            )
        ).applied
        commission_id = commission.id
        wake_id = wake.id
    finally:
        await ledger.close()

    # Opening a new host reconciles fired-but-untaken wake ids back to pending.
    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: commission_id in host.task_agents.queued,
            what="wake-backed queue to be reconstructed",
        )
        assert commission_id not in host.task_agents._resume

        pending = await host.ledger.wakes_pending(commission_id=commission_id)
        if pending:
            current = await host.ledger.get(commission_id)
            assert current is not None and current.session_id
            target = await host.ledger.get_session(current.session_id)
            assert target is not None
            await host.task_agents._hand_to(current, target, pending)

        await wait_until(
            lambda: commission_id not in host.task_agents._restart_waiting_wakes,
            what="native wake ids to be handed to recovered queue",
        )
        restored = host.task_agents._resume.get(commission_id)
        assert isinstance(restored, _Handed)
        assert restored.wakes == (wake_id,)
        assert commission_id not in host.task_agents._restart_resume_wakes
        handed_notes = [
            note
            for note in host.task_agents._notes.get(commission_id, [])
            if isinstance(note, _Handed) and wake_id in note.wakes
        ]
        assert handed_notes == []
    finally:
        await host.abort(commission_id, reason="test cleanup")
        await host.shutdown()


@pytest.mark.asyncio
async def test_message_wake_uses_session_authority_once_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "message-wake-root"
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.db")
    try:
        target, created = await ledger.create(
            lanlan_name="Lan",
            title="message target",
            dispatch_text="target",
            user_text="target",
            source="dispatch",
        )
        assert created
        target = await ledger.update(target.id, route="task_agent")
        assert target is not None
        target, target_session = await ledger.give_session(
            target.id, kind="single", name=target.id, duty="message target"
        )
        assert (await ledger.transition(target.id, "working", reason="target run")).applied

        source, created = await ledger.create(
            lanlan_name="Lan",
            title="message source",
            dispatch_text="source",
            user_text="source",
            source="dispatch",
        )
        assert created
        source = await ledger.update(source.id, route="task_agent")
        assert source is not None
        source, source_session = await ledger.give_session(
            source.id, kind="single", name=source.id, duty="message source"
        )
        assert (await ledger.transition(source.id, "working", reason="source run")).applied

        message, refusal, _retry = await ledger.message_add(
            from_session=source_session.id,
            from_commission=source.id,
            to_session=target_session.id,
            body="message wake after restart",
            depth=1,
            notify_when_done=False,
            notice_after=60.0,
            limits=MessageLimits(
                target_interval=0.0,
                per_hour=100,
                queue_max=100,
                dedup_seconds=0.0,
            ),
        )
        assert message is not None
        assert refusal == ""

        pending = await ledger.wakes_pending(session_id=target_session.id)
        message_wakes = [wake for wake in pending if wake.reason == "message" and wake.message_id == message.id]
        assert len(message_wakes) == 1
        wake = message_wakes[0]
        # Message handoff is a session-level authority; unlike timers it does
        # not need to name the commission that happens to own the session.
        assert wake.commission_id is None
        fired = await ledger.wakes_fire([wake.id], into=target.id)
        assert fired == [wake.id]
        await ledger.append_event(
            target.id,
            "restart_queue_resume",
            {"resume": _queue_text_payload(_Handed("serialized message must not replay", fired))},
        )
        assert (
            await ledger.transition(
                target.id,
                "queued",
                reason="message handoff; waiting for a place",
            )
        ).applied
        target_id = target.id
        wake_id = wake.id
    finally:
        await ledger.close()

    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: target_id in host.task_agents.queued,
            what="message-backed queue to be reconstructed",
        )
        current = await host.ledger.get(target_id)
        assert current is not None and current.status == "queued"
        assert current.session_id == target_session.id
        assert target_id not in host.task_agents._resume
        assert host.task_agents._restart_waiting_wakes[target_id] == {wake_id}

        pending = await host.ledger.wakes_pending(session_id=target_session.id)
        matching = [wake for wake in pending if wake.id == wake_id]
        assert len(matching) == 1
        target_row = await host.ledger.get_session(target_session.id)
        assert target_row is not None
        await host.task_agents._hand_to(current, target_row, matching)

        await wait_until(
            lambda: target_id not in host.task_agents._restart_waiting_wakes,
            what="session-level message wake to be handed exactly once",
        )
        restored = host.task_agents._resume.get(target_id)
        assert isinstance(restored, _Handed)
        assert restored.wakes == (wake_id,)
        assert target_id not in host.task_agents._restart_resume_wakes
        handed_notes = [
            note
            for note in host.task_agents._notes.get(target_id, [])
            if isinstance(note, _Handed) and wake_id in note.wakes
        ]
        assert handed_notes == []
    finally:
        await host.abort(target_id)
        await host.shutdown()


@pytest.mark.asyncio
async def test_initial_queue_recovers_acknowledged_native_told_notes(tmp_path: Path) -> None:
    root = tmp_path / "initial-told-root"
    commission_id = await _prepared_queue(root)
    ledger = Ledger(root / "ledger.db")
    try:
        await ledger.append_event(
            commission_id,
            "told",
            {"text": "queued user follow-up", "queued": True},
        )
    finally:
        await ledger.close()

    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: commission_id in host.task_agents.queued,
            what="initial queued commission with native told note",
        )
        assert host.task_agents._notes[commission_id] == ["queued user follow-up"]
        assert commission_id not in host.task_agents._resume
    finally:
        await host.abort(commission_id)
        await host.shutdown()


@pytest.mark.asyncio
async def test_current_requeue_recovers_ordered_secondary_found_note(tmp_path: Path) -> None:
    root = tmp_path / "secondary-found-root"
    primary = _Unsaid("primary copied answer", "recipient-session")
    commission_id = await _prepared_queue(root, resume=_queue_text_payload(primary))
    ledger = Ledger(root / "ledger.db")
    try:
        await ledger.append_event(
            commission_id,
            "restart_queue_note",
            {"note": _queue_text_payload(_Found("secondary child finding"))},
        )
    finally:
        await ledger.close()

    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: commission_id in host.task_agents.queued,
            what="requeued commission with secondary finding",
        )
        restored = host.task_agents._resume.get(commission_id)
        assert isinstance(restored, _Unsaid)
        assert str(restored) == "primary copied answer"
        notes = host.task_agents._notes.get(commission_id, [])
        assert len(notes) == 1
        assert isinstance(notes[0], _Found)
        assert str(notes[0]) == "secondary child finding"
    finally:
        await host.abort(commission_id)
        await host.shutdown()


@pytest.mark.asyncio
async def test_secondary_take_up_input_is_durable_before_memory_acceptance(tmp_path: Path) -> None:
    root = tmp_path / "secondary-takeup-root"
    commission_id = await _prepared_queue(root)
    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: commission_id in host.task_agents.queued,
            what="initial queue to be reconstructed before secondary input",
        )
        accepted = await host.task_agents._take_up_again(
            commission_id,
            _Found("late child result"),
        )
        assert accepted is True
        events = await host.ledger.events(commission_id)
        durable = [
            event
            for event in events
            if event.type == "restart_queue_note"
            and event.payload.get("note", {}).get("text") == "late child result"
        ]
        assert len(durable) == 1
        assert durable[0].payload["note"]["provenance"] == "found"
        notes = host.task_agents._notes.get(commission_id, [])
        assert any(isinstance(note, _Found) and str(note) == "late child result" for note in notes)
    finally:
        await host.abort(commission_id)
        await host.shutdown()


@pytest.mark.asyncio
async def test_secondary_wake_note_keeps_queue_position_and_native_text(tmp_path: Path) -> None:
    root = tmp_path / "secondary-wake-note-root"
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.db")
    try:
        commission, created = await ledger.create(
            lanlan_name="Lan",
            title="secondary wake note",
            dispatch_text="initial",
            user_text="initial",
            source="dispatch",
        )
        assert created
        commission = await ledger.update(commission.id, route="task_agent")
        assert commission is not None
        commission, session = await ledger.give_session(
            commission.id, kind="single", name=commission.id, duty="secondary wake note"
        )
        assert (await ledger.transition(commission.id, "working", reason="first run")).applied

        wake, refusal = await ledger.wake_add(
            session_id=session.id,
            commission_id=commission.id,
            note="secondary native timer",
            due_at=0.0,
            pending_max=10,
            daily_max=10,
        )
        assert refusal == "" and wake is not None
        fired = await ledger.wakes_fire([wake.id], into=commission.id)
        assert fired == [wake.id]

        primary = _Unsaid("primary continuation", "recipient-session")
        await ledger.append_event(
            commission.id,
            "restart_queue_resume",
            {"resume": _queue_text_payload(primary)},
        )
        assert (
            await ledger.transition(
                commission.id,
                "queued",
                reason="primary continuation waiting for a place",
            )
        ).applied
        await ledger.append_event(
            commission.id,
            "restart_queue_note",
            {"note": _queue_text_payload(_Handed("serialized secondary wake", fired))},
        )
        await ledger.append_event(
            commission.id,
            "restart_queue_note",
            {"note": _queue_text_payload(_Found("after wake finding"))},
        )
        commission_id = commission.id
        session_id = session.id
        wake_id = wake.id
    finally:
        await ledger.close()

    host = _recovery_host(root)
    try:
        host.start()
        await wait_until(
            lambda: commission_id in host.task_agents.queued,
            what="requeue with secondary wake note to be reconstructed",
        )
        primary = host.task_agents._resume.get(commission_id)
        assert isinstance(primary, _Unsaid)
        notes = host.task_agents._notes.get(commission_id, [])
        assert len(notes) == 2
        assert isinstance(notes[0], _Handed) and str(notes[0]) == "" and notes[0].wakes == (wake_id,)
        assert isinstance(notes[1], _Found) and str(notes[1]) == "after wake finding"
        assert host.task_agents._restart_waiting_wakes[commission_id] == {wake_id}

        pending = await host.ledger.wakes_pending(session_id=session_id)
        matching = [wake for wake in pending if wake.id == wake_id]
        assert len(matching) == 1
        current = await host.ledger.get(commission_id)
        target = await host.ledger.get_session(session_id)
        assert current is not None and target is not None
        await host.task_agents._hand_to(current, target, matching)

        await wait_until(
            lambda: commission_id not in host.task_agents._restart_waiting_wakes,
            what="secondary native wake note to be handed",
        )
        notes = host.task_agents._notes.get(commission_id, [])
        assert len(notes) == 2
        assert isinstance(notes[0], _Handed)
        assert str(notes[0]) != "serialized secondary wake"
        assert notes[0].wakes == (wake_id,)
        assert isinstance(notes[1], _Found)
        assert str(notes[1]) == "after wake finding"
    finally:
        await host.abort(commission_id)
        await host.shutdown()


@pytest.mark.asyncio
async def test_copy_handback_notes_commit_before_primary_requeue(tmp_path: Path) -> None:
    root = tmp_path / "copy-handback-root"
    host = _recovery_host(root)
    try:
        commission, created = await host.ledger.create(
            lanlan_name="Lan",
            title="copy handback",
            dispatch_text="copy work",
            user_text="copy work",
            source="dispatch",
        )
        assert created
        commission = await host.ledger.update(commission.id, route="task_agent")
        assert commission is not None
        commission, _session = await host.ledger.give_session(
            commission.id, kind="single", name=commission.id, duty="copy handback"
        )
        assert (await host.ledger.transition(commission.id, "working", reason="copy active")).applied

        assert await host.task_agents._wake_working(
            commission.id,
            _Found("copy finding"),
            reason="handed back by a copy of its session",
            before=["user line one in copy", "user line two in copy"],
        )

        events = await host.ledger.events(commission.id)
        relevant = [
            event
            for event in events
            if event.type in {"restart_queue_note", "restart_queue_resume", "status"}
            and (
                event.type != "status"
                or event.payload.get("to") == "queued"
            )
        ]
        assert [event.type for event in relevant[-4:]] == [
            "restart_queue_note",
            "restart_queue_note",
            "restart_queue_resume",
            "status",
        ]
        assert relevant[-4].payload["note"]["text"] == "user line one in copy"
        assert relevant[-3].payload["note"]["text"] == "user line two in copy"
        assert relevant[-2].payload["resume"]["provenance"] == "found"

        current = await host.ledger.get(commission.id)
        assert current is not None and current.status == "queued"
        assert isinstance(host.task_agents._resume.get(commission.id), _Found)
        assert host.task_agents._notes.get(commission.id, []) == []
    finally:
        await host.abort(commission.id)
        await host.shutdown()


@pytest.mark.asyncio
async def test_cancel_wins_while_restart_queue_recovery_is_resolving_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cancel-race-root"
    commission_id = await _prepared_queue(root)
    host = _recovery_host(root)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = host.task_agents._know_session

    async def delayed_know_session(cid: str) -> bool:
        entered.set()
        await release.wait()
        return await original(cid)

    monkeypatch.setattr(host.task_agents, "_know_session", delayed_know_session)
    try:
        host.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        cancelled = await host.ledger.transition(
            commission_id,
            "cancelled",
            reason="explicit user stop won during restart recovery",
        )
        assert cancelled.applied
        release.set()
        await host.task_agents.settle()

        current = await host.ledger.get(commission_id)
        assert current is not None
        assert current.status == "cancelled"
        assert current.status_reason == "explicit user stop won during restart recovery"
        assert commission_id not in host.task_agents.queued
        assert commission_id not in host.task_agents.running
        assert commission_id not in host.task_agents._resume
        assert commission_id not in host.task_agents._restart_waiting_wakes
    finally:
        release.set()
        await host.shutdown()
