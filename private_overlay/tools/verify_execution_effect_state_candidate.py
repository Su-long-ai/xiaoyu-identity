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
            return DeliveryHandoff("attempt-a")

        sender = OutboxSender(ledger, send)
        assert await sender.flush() == 0
        assert await ledger.outbox_delivery_state(item_id) == "handoff"
        assert await ledger.outbox_pending() == []
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
        path = Path(td) / "effect-ledger.db"
        ledger = Ledger(path)
        item_id = await ledger.outbox_add(None, "task_result", {"summary": "guard"})

        async def invalid_send(_item):
            return DeliveryHandoff("not-recorded")

        sender = OutboxSender(ledger, invalid_send)
        assert await sender.flush() == 0
        assert await ledger.outbox_delivery_state(item_id) == "pending"
        pending = await ledger.outbox_pending()
        assert [item.id for item in pending] == [item_id]
        assert pending[0].attempts == 1
        assert "not persisted before transport" in pending[0].last_error
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
