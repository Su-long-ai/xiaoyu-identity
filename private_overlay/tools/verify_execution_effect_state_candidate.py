from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path


def _load(neko_root: Path):
    root = str(neko_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    from nekoclaw.host.ledger import Ledger
    from nekoclaw.host.outbox import OutboxSender
    return Ledger, OutboxSender


async def _verify(neko_root: Path) -> None:
    Ledger, OutboxSender = _load(neko_root)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effect-ledger.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(None, "task_result", {"summary": "done"})

        send_calls: list[int] = []
        attempt_ids: list[str] = []

        async def send(item):
            send_calls.append(item.id)
            assert item.payload["__nekoclaw_delivery_id"] == item.id
            attempt_ids.append(item.payload["__nekoclaw_delivery_attempt_id"])
            inside = await ledger.outbox_delivery_state(item.id)
            assert inside == "handoff", ("inside-send", inside)
            return True

        send._nekoclaw_effect_receipt_required = lambda _item: True
        sender = OutboxSender(ledger, send)
        assert await sender.flush() == 0
        assert send_calls == [item_id], send_calls
        assert len(attempt_ids) == 1 and attempt_ids[0]
        state = await ledger.outbox_delivery_state(item_id)
        debug_rows = await ledger.outbox_pending(due_by=2**62)
        debug = [(row.id, row.attempts, row.last_error, row.next_attempt_at) for row in debug_rows]
        assert state == "handoff", (state, debug)
        assert await ledger.outbox_pending() == []
        await ledger.close()

    with tempfile.TemporaryDirectory() as td:
        now = [100.0]
        path = Path(td) / "handoff-lease.db"
        leased = Ledger(path, clock=lambda: now[0])
        item_id = await leased.outbox_add(None, "task_result", {"summary": "lease"})
        assert await leased.outbox_mark_handoff(item_id, "attempt-old")
        assert await leased.outbox_pending(due_by=129.9) == []
        assert await leased.outbox_next_due() == 130.0
        now[0] = 130.0
        due = await leased.outbox_pending(due_by=now[0])
        assert [item.id for item in due] == [item_id]
        assert (
            await leased.outbox_claim_delivery(
                item_id, "attempt-old", "late-main-claim"
            )
            == "expired"
        )
        assert await leased.outbox_mark_handoff(item_id, "attempt-new")
        assert (
            await leased.outbox_claim_delivery(
                item_id, "attempt-old", "late-main-claim"
            )
            == "not_ready"
        )
        assert (
            await leased.outbox_claim_delivery(
                item_id, "attempt-new", "fresh-main-claim"
            )
            == "claimed"
        )
        assert (
            await leased.outbox_release_delivery(
                item_id, "attempt-new", "wrong-main-claim"
            )
            == "not_ready"
        )
        assert await leased.outbox_delivery_state(item_id) == "claimed"
        assert (
            await leased.outbox_release_delivery(
                item_id, "attempt-new", "fresh-main-claim"
            )
            == "released"
        )
        assert await leased.outbox_delivery_state(item_id) == "pending"
        assert [row.id for row in await leased.outbox_pending(due_by=now[0])] == [item_id]
        await leased.close()

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "main-restart-ledger.db"
        ledger = Ledger(path)
        safe = await ledger.outbox_add(None, "task_result", {"summary": "handoff"})
        first_claim = await ledger.outbox_add(None, "task_result", {"summary": "claim-a"})
        second_claim = await ledger.outbox_add(None, "task_result", {"summary": "claim-b"})
        assert await ledger.outbox_mark_handoff(safe, "handoff-only")
        assert await ledger.outbox_mark_handoff(first_claim, "attempt-a")
        assert await ledger.outbox_mark_handoff(second_claim, "attempt-b")
        assert await ledger.outbox_claim_delivery(first_claim, "attempt-a", "claim-a") == "claimed"
        assert await ledger.outbox_claim_delivery(second_claim, "attempt-b", "claim-b") == "claimed"

        # A new main-process epoch freezes only claims that could already have
        # crossed the visible-effect boundary. Pre-claim handoff stays leased
        # and retryable after its existing lease expires.
        assert await ledger.outbox_mark_main_restart_uncertain() == 2
        assert await ledger.outbox_delivery_state(safe) == "handoff"
        assert await ledger.outbox_delivery_state(first_claim) == "uncertain"
        assert await ledger.outbox_delivery_state(second_claim) == "uncertain"
        assert await ledger.outbox_mark_main_restart_uncertain() == 0
        assert all(
            item.id not in {first_claim, second_claim}
            for item in await ledger.outbox_pending(due_by=2**62)
        )

        # A late positive native receipt can still settle the exact uncertain
        # claim; absence of a receipt never makes it retryable.
        assert (
            await ledger.outbox_commit_delivery(
                first_claim, "attempt-a", "claim-a"
            )
            == "committed"
        )
        assert await ledger.outbox_delivery_state(first_claim) == "sent"
        assert await ledger.outbox_delivery_state(second_claim) == "uncertain"
        # A stale/no-effect receipt after restart must never reopen an
        # uncertain claim for automatic retry. Only an exact positive receipt
        # may reconcile it.
        assert (
            await ledger.outbox_release_delivery(
                second_claim, "attempt-b", "claim-b"
            )
            == "uncertain"
        )
        assert await ledger.outbox_delivery_state(second_claim) == "uncertain"
        assert all(
            item.id != second_claim
            for item in await ledger.outbox_pending(due_by=2**62)
        )
        await ledger.close()

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effect-ledger.db"
        first = Ledger(path)
        safe = await first.outbox_add(None, "task_result", {"summary": "safe"})
        risky = await first.outbox_add(None, "task_result", {"summary": "risky"})
        assert await first.outbox_mark_handoff(safe, "safe-attempt")
        assert await first.outbox_mark_handoff(risky, "risky-attempt")
        assert await first.outbox_claim_delivery(risky, "risky-attempt", "main-claim-a") == "claimed"
        assert await first.outbox_claim_delivery(risky, "risky-attempt", "main-claim-a") == "claimed"
        assert await first.outbox_claim_delivery(risky, "risky-attempt", "main-claim-b") == "already_claimed"
        await first.close()

        second = Ledger(path)
        await second.open()
        try:
            assert await second.outbox_delivery_state(safe) == "pending"
            assert await second.outbox_delivery_state(risky) == "uncertain"
            assert [item.id for item in await second.outbox_pending()] == [safe]
            assert (
                await second.outbox_commit_delivery(
                    risky, "risky-attempt", "wrong-main-claim"
                )
                == "not_ready"
            )
            assert await second.outbox_delivery_state(risky) == "uncertain"
            assert (
                await second.outbox_commit_delivery(
                    risky, "risky-attempt", "main-claim-a"
                )
                == "committed"
            )
            assert await second.outbox_delivery_state(risky) == "sent"
            assert (
                await second.outbox_commit_delivery(
                    risky, "risky-attempt", "main-claim-a"
                )
                == "sent"
            )
        finally:
            await second.close()

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "confirmed-replay.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(
            None, "task_result", {"summary": "confirmed-once"}
        )
        assert await ledger.outbox_mark_handoff(item_id, "attempt-confirmed")
        assert (
            await ledger.outbox_claim_delivery(
                item_id, "attempt-confirmed", "claim-confirmed"
            )
            == "claimed"
        )
        assert (
            await ledger.outbox_commit_delivery(
                item_id, "attempt-confirmed", "claim-confirmed"
            )
            == "committed"
        )
        assert await ledger.outbox_delivery_state(item_id) == "sent"
        assert (
            await ledger.outbox_claim_delivery(
                item_id, "attempt-confirmed", "claim-confirmed"
            )
            == "sent"
        )
        assert (
            await ledger.outbox_claim_delivery(
                item_id, "attempt-replay", "claim-replay"
            )
            == "sent"
        )
        assert (
            await ledger.outbox_release_delivery(
                item_id, "attempt-confirmed", "claim-confirmed"
            )
            == "sent"
        )
        await ledger.outbox_mark_failed(item_id, "late transport failure", 0.0)
        assert await ledger.outbox_delivery_state(item_id) == "sent"
        assert all(
            item.id != item_id
            for item in await ledger.outbox_pending(due_by=2**62)
        )
        await ledger.close()

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ambiguous-transport.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(None, "task_result", {"summary": "ambiguous"})

        async def ambiguous_send(item):
            assert item.payload["__nekoclaw_delivery_id"] == item.id
            assert item.payload["__nekoclaw_delivery_attempt_id"]
            raise RuntimeError("transport ambiguous after durable handoff")

        ambiguous_send._nekoclaw_effect_receipt_required = lambda _item: True
        sender = OutboxSender(ledger, ambiguous_send)
        assert await sender.flush() == 0
        assert await ledger.outbox_delivery_state(item_id) == "handoff"
        await ledger.outbox_mark_failed(item_id, "must-not-overwrite", 0.0)
        assert await ledger.outbox_delivery_state(item_id) == "handoff"
        rows = await ledger.outbox_pending(due_by=2**62)
        assert [row.id for row in rows] == [item_id]
        assert rows[0].attempts == 0
        assert rows[0].last_error.startswith("delivery_handoff:")
        await ledger.close()

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "transport-reject.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(None, "task_result", {"summary": "retry"})

        async def rejected_send(item):
            assert item.payload["__nekoclaw_delivery_id"] == item.id
            assert item.payload["__nekoclaw_delivery_attempt_id"]
            return False

        rejected_send._nekoclaw_effect_receipt_required = lambda _item: True
        sender = OutboxSender(ledger, rejected_send)
        assert await sender.flush() == 0
        assert await ledger.outbox_delivery_state(item_id) == "pending"
        pending = await ledger.outbox_pending(due_by=2**62)
        assert [item.id for item in pending] == [item_id]
        assert pending[0].attempts == 1
        assert pending[0].last_error == "not accepted"
        await ledger.close()

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "legacy-bool.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(None, "task_result", {"summary": "legacy"})

        async def legacy_send(item):
            assert "__nekoclaw_delivery_id" not in item.payload
            assert "__nekoclaw_delivery_attempt_id" not in item.payload
            return True

        sender = OutboxSender(ledger, legacy_send)
        assert await sender.flush() == 1
        assert await ledger.outbox_delivery_state(item_id) == "sent"
        await ledger.close()



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_verify(args.neko_root))
    print("execution effect-state candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
