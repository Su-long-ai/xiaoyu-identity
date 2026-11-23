from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from nekoclaw.host import call_audit
from nekoclaw.host.ledger import HOST_ENDED_REASON, Ledger


def _kill_after_committed_checkpoint(tmp_path: Path, state: str) -> tuple[Path, dict[str, Any]]:
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
        # Hard kill: no Ledger.close(), no host shutdown hooks, no cooperative
        # cancellation. The next Ledger instance is a genuinely new process epoch.
        proc.kill()
        proc.wait(timeout=5)
        return db, snapshot
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("queued", "failed"),
        ("working", "failed"),
        ("blocked", "blocked"),
        ("done", "done"),
        ("waiting-report", "waiting_user"),
        ("waiting-permission", "waiting_user"),
        ("waiting-permission-plugin", "failed"),
        ("waiting-tool", "failed"),
        ("waiting-malformed", "failed"),
        ("cancelled-from-wait", "cancelled"),
    ],
)
async def test_hard_kill_restart_state_matrix(
    tmp_path: Path,
    state: str,
    expected: str,
) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, state)

    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.id == snapshot["commission_id"]
        assert commission.route == snapshot["route"]
        assert commission.status == expected

        if expected == "failed":
            assert commission.status_reason == HOST_ENDED_REASON

        question_id = snapshot.get("question_id")
        if expected == "waiting_user":
            assert commission.question() is not None
            assert commission.question().get("id") == question_id

        outbox_id = snapshot.get("outbox_id")
        if outbox_id is not None:
            if expected == "waiting_user":
                assert await reopened.outbox_question_state(int(outbox_id)) == "current"
            else:
                assert await reopened.outbox_question_state(int(outbox_id)) == "gone"
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_hard_kill_after_cancel_commit_cannot_revive_old_permission_wait(tmp_path: Path) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, "cancelled-from-wait")

    first_restart = Ledger(db)
    try:
        cancelled = await first_restart.get(str(snapshot["commission_id"]))
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.status_reason == "user cancelled before host death"

        # A late result/recovery transition is rejected by the native terminal
        # state machine. Recovery may inspect this row, but cannot resurrect it.
        late = await first_restart.transition(
            cancelled.id,
            "working",
            reason="late recovery attempted to resume",
        )
        assert late.applied is False
        still = await first_restart.get(cancelled.id)
        assert still is not None and still.status == "cancelled"
    finally:
        await first_restart.close()

    # Prove terminality is durable for another process epoch too.
    second_restart = Ledger(db)
    try:
        still = await second_restart.get(str(snapshot["commission_id"]))
        assert still is not None and still.status == "cancelled"
    finally:
        await second_restart.close()


@pytest.mark.asyncio
async def test_hard_kill_unknown_work_never_becomes_retryable_work(tmp_path: Path) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, "working")

    reopened = Ledger(db)
    try:
        failed = await reopened.get(str(snapshot["commission_id"]))
        assert failed is not None
        assert failed.status == "failed"
        assert failed.status_reason == HOST_ENDED_REASON

        # Reconciliation itself must not silently put unknown old work back in
        # queued/working. A deliberate later user action can use N.E.K.O's normal
        # failed -> working seam, but restart never does it on its own.
        after = await reopened.get(failed.id)
        assert after is not None and after.status == "failed"
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_delivery_state", "retryable"),
    [
        ("outbox-pending", "pending", True),
        ("outbox-handoff", "pending", True),
        ("outbox-claimed", "uncertain", False),
        ("outbox-sent", "sent", False),
    ],
)
async def test_hard_kill_outbox_effect_state_matrix(
    tmp_path: Path,
    state: str,
    expected_delivery_state: str,
    retryable: bool,
) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, state)
    item_id = int(snapshot["outbox_id"])

    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None and commission.status == "done"
        assert await reopened.outbox_delivery_state(item_id) == expected_delivery_state

        pending_ids = {item.id for item in await reopened.outbox_pending()}
        assert (item_id in pending_ids) is retryable
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_hard_kill_claimed_result_accepts_only_exact_late_positive_receipt(
    tmp_path: Path,
) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, "outbox-claimed")
    item_id = int(snapshot["outbox_id"])
    attempt_id = str(snapshot["attempt_id"])
    claim_id = str(snapshot["claim_id"])

    reopened = Ledger(db)
    try:
        assert await reopened.outbox_delivery_state(item_id) == "uncertain"

        assert (
            await reopened.outbox_commit_delivery(
                item_id,
                attempt_id,
                "different-claim-from-new-main",
            )
            == "not_ready"
        )
        assert await reopened.outbox_delivery_state(item_id) == "uncertain"

        # A negative/stale settlement cannot make an uncertain visible effect
        # retryable. Only the exact positive receipt can reconcile it.
        assert await reopened.outbox_release_delivery(item_id, attempt_id, claim_id) == "uncertain"
        assert await reopened.outbox_delivery_state(item_id) == "uncertain"

        assert await reopened.outbox_commit_delivery(item_id, attempt_id, claim_id) == "committed"
        assert await reopened.outbox_delivery_state(item_id) == "sent"
        assert item_id not in {item.id for item in await reopened.outbox_pending()}
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_main_epoch_change_freezes_claim_without_host_restart(tmp_path: Path) -> None:
    path = tmp_path / "main-epoch.db"
    ledger = Ledger(path)
    try:
        commission, created = await ledger.create(
            lanlan_name="Lan",
            title="main epoch",
            dispatch_text="main epoch",
            user_text="main epoch",
            source="dispatch",
        )
        assert created
        await ledger.update(commission.id, route="task_agent")
        assert (await ledger.transition(commission.id, "working", reason="ready")).applied
        assert (await ledger.transition(commission.id, "done", reason="result committed")).applied

        item_id = await ledger.outbox_add(
            commission.id,
            "task_result",
            {"task_id": commission.id, "text": "visible result"},
        )
        attempt_id = "attempt-old-main"
        claim_id = "claim-old-main"
        assert await ledger.outbox_mark_handoff(item_id, attempt_id)
        assert await ledger.outbox_claim_delivery(item_id, attempt_id, claim_id) == "claimed"

        assert await ledger.outbox_mark_main_restart_uncertain() == 1
        assert await ledger.outbox_delivery_state(item_id) == "uncertain"
        assert await ledger.outbox_claim_delivery(item_id, attempt_id, "new-main-claim") == "uncertain"
        assert item_id not in {item.id for item in await ledger.outbox_pending()}

        # Retired-main exact positive receipt remains useful reconciliation
        # evidence; it commits the already-observed effect rather than replaying.
        assert await ledger.outbox_commit_delivery(item_id, attempt_id, claim_id) == "committed"
        assert await ledger.outbox_delivery_state(item_id) == "sent"
    finally:
        await ledger.close()


@pytest.mark.asyncio
async def test_unclaimed_handoff_after_hard_kill_is_safe_to_retry_with_new_identity(
    tmp_path: Path,
) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, "outbox-handoff")
    item_id = int(snapshot["outbox_id"])

    reopened = Ledger(db)
    try:
        assert await reopened.outbox_delivery_state(item_id) == "pending"
        assert item_id in {item.id for item in await reopened.outbox_pending()}

        new_attempt = "attempt-after-restart"
        new_claim = "claim-after-restart"
        assert await reopened.outbox_mark_handoff(item_id, new_attempt)
        assert await reopened.outbox_claim_delivery(item_id, new_attempt, new_claim) == "claimed"
        assert await reopened.outbox_commit_delivery(item_id, new_attempt, new_claim) == "committed"
        assert await reopened.outbox_delivery_state(item_id) == "sent"
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_call_status"),
    [
        ("call-running-device", "interrupted"),
        ("call-running-plugin", "interrupted"),
        ("call-completed-device", "completed"),
        ("call-completed-plugin", "completed"),
    ],
)
async def test_hard_kill_host_call_audit_preserves_effect_boundary(
    tmp_path: Path,
    state: str,
    expected_call_status: str,
) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, state)
    call_id = str(snapshot["call_id"])

    reopened = Ledger(db)
    try:
        commission = await reopened.get(str(snapshot["commission_id"]))
        assert commission is not None
        assert commission.status == "failed"
        assert commission.status_reason == HOST_ENDED_REASON

        trace = await reopened.run(
            lambda conn: call_audit.read_trace(
                conn,
                commission.id,
                now=reopened._clock(),
            )
        )
        exact = [row for row in trace if row["call_id"] == call_id]
        assert len(exact) == 1
        assert exact[0]["kind"] == snapshot["call_kind"]
        assert exact[0]["status"] == expected_call_status
        assert all(row["status"] != "running" for row in trace)
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_completed_effect_call_identity_survives_multiple_restart_epochs(
    tmp_path: Path,
) -> None:
    db, snapshot = _kill_after_committed_checkpoint(tmp_path, "call-completed-plugin")
    commission_id = str(snapshot["commission_id"])
    call_id = str(snapshot["call_id"])

    for _epoch in range(2):
        reopened = Ledger(db)
        try:
            commission = await reopened.get(commission_id)
            assert commission is not None and commission.status == "failed"
            trace = await reopened.run(
                lambda conn: call_audit.read_trace(
                    conn,
                    commission_id,
                    now=reopened._clock(),
                )
            )
            exact = [row for row in trace if row["call_id"] == call_id]
            assert len(exact) == 1
            assert exact[0]["status"] == "completed"
        finally:
            await reopened.close()
