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
    from nekoclaw.host.outbox import DeliveryHandoff, OutboxSender
    return Ledger, DeliveryHandoff, OutboxSender


async def _verify(neko_root: Path) -> None:
    Ledger, DeliveryHandoff, OutboxSender = _load(neko_root)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effect-ledger.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(None, "task_result", {"summary": "done"})

        async def send(item):
            assert await ledger.outbox_mark_handoff(item.id, "attempt-a")
            inside = await ledger.outbox_delivery_state(item.id)
            assert inside == "handoff", ("inside-send", inside)
            return DeliveryHandoff("attempt-a")

        sender = OutboxSender(ledger, send)
        assert await sender.flush() == 0
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



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_verify(args.neko_root))
    print("execution effect-state candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
