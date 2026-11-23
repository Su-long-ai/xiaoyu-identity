from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from nekoclaw.host import call_audit
from nekoclaw.host.ledger import Ledger


def _question(kind: str, question_id: str) -> dict[str, Any]:
    if kind == "permission":
        return {
            "kind": "permission",
            "id": question_id,
            "category": "outside_read",
            "key": None,
            "detail": {"path": "D:/restart-fixture.txt"},
            "options": ["always", "session", "once", "deny"],
        }
    if kind == "report":
        return {"kind": "report", "id": question_id, "question": "continue?"}
    if kind == "tool":
        return {"kind": "tool", "id": question_id, "question": "tool question"}
    raise ValueError(kind)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument(
        "--state",
        choices=(
            "queued",
            "working",
            "blocked",
            "done",
            "waiting-report",
            "waiting-permission",
            "waiting-permission-plugin",
            "waiting-tool",
            "waiting-malformed",
            "cancelled-from-wait",
            "outbox-pending",
            "outbox-handoff",
            "outbox-claimed",
            "outbox-sent",
            "call-running-device",
            "call-running-plugin",
            "call-completed-device",
            "call-completed-plugin",
            "working-resting",
            "working-plugin-route",
        ),
        required=True,
    )
    args = parser.parse_args()

    ledger = Ledger(args.db)
    commission, created = await ledger.create(
        lanlan_name="Lan",
        title=f"restart fault {args.state}",
        dispatch_text=f"restart fault {args.state}",
        user_text=f"restart fault {args.state}",
        source="dispatch",
    )
    assert created

    route = "plugin" if args.state in {"waiting-permission-plugin", "working-plugin-route"} else "task_agent"
    await ledger.update(commission.id, route=route)

    question: dict[str, Any] | None = None
    outbox_id: int | None = None
    attempt_id: str | None = None
    claim_id: str | None = None
    outbox_state = args.state.startswith("outbox-")
    call_state = args.state.startswith("call-")
    call_id: str | None = None
    call_kind: str | None = None

    if args.state != "queued":
        assert (await ledger.transition(commission.id, "working", reason="fault injector started")).applied

    if args.state == "working-resting":
        wake, refusal = await ledger.wake_add(
            session_id=f"{commission.id}-session",
            commission_id=commission.id,
            note="resume after restart",
            due_at=ledger._clock() + 3600.0,
            pending_max=10,
            daily_max=10,
        )
        assert wake is not None and refusal == ""
        assert await ledger.rest(commission.id) is not None
    elif call_state:
        call_kind = "plugin" if args.state.endswith("-plugin") else "device"
        record = await call_audit.start_call(
            ledger,
            commission.id,
            call_kind,
            "plugin:fixture:write" if call_kind == "plugin" else "builtin:fixture:write",
        )
        call_id = record.call_id
        if args.state.startswith("call-completed-"):
            await call_audit.finish_call(record, "completed")
            assert record.closed
    elif outbox_state:
        assert (await ledger.transition(commission.id, "done", reason="result committed before delivery")).applied
        outbox_id = await ledger.outbox_add(
            commission.id,
            "task_result",
            {"task_id": commission.id, "text": f"durable result for {args.state}"},
        )
        attempt_id = "attempt-before-hard-kill"
        claim_id = "claim-before-hard-kill"
        if args.state in {"outbox-handoff", "outbox-claimed", "outbox-sent"}:
            assert await ledger.outbox_mark_handoff(outbox_id, attempt_id)
        if args.state in {"outbox-claimed", "outbox-sent"}:
            assert await ledger.outbox_claim_delivery(outbox_id, attempt_id, claim_id) == "claimed"
        if args.state == "outbox-sent":
            assert await ledger.outbox_commit_delivery(outbox_id, attempt_id, claim_id) == "committed"
    elif args.state == "blocked":
        assert (await ledger.transition(commission.id, "blocked", reason="fault injector blocked")).applied
    elif args.state == "done":
        assert (await ledger.transition(commission.id, "done", reason="fault injector done")).applied
    elif args.state.startswith("waiting-") or args.state == "cancelled-from-wait":
        if args.state == "waiting-malformed":
            pending = "{"
            question_id = "malformed-question"
        else:
            kind = {
                "waiting-report": "report",
                "waiting-permission": "permission",
                "waiting-permission-plugin": "permission",
                "waiting-tool": "tool",
                "cancelled-from-wait": "permission",
            }[args.state]
            question_id = f"{args.state}-question"
            question = _question(kind, question_id)
            pending = json.dumps(question)
        assert (
            await ledger.transition(
                commission.id,
                "waiting_user",
                reason="fault injector waiting",
                pending_question=pending,
            )
        ).applied
        outbox_id = await ledger.outbox_add(
            commission.id,
            "question",
            {
                "task_id": commission.id,
                "question": question if question is not None else {"raw": pending},
            },
        )
        if args.state == "cancelled-from-wait":
            assert (
                await ledger.transition(
                    commission.id,
                    "cancelled",
                    reason="user cancelled before host death",
                )
            ).applied

    marker = {
        "commission_id": commission.id,
        "state": args.state,
        "route": route,
        "question_id": None if question is None else question.get("id"),
        "outbox_id": outbox_id,
        "attempt_id": attempt_id,
        "claim_id": claim_id,
        "call_id": call_id,
        "call_kind": call_kind,
    }
    args.marker.parent.mkdir(parents=True, exist_ok=True)
    args.marker.write_text(json.dumps(marker), encoding="utf-8")

    # Deliberately do not close the ledger. The parent SIGKILLs this process
    # after the marker proves every awaited SQLite write above committed.
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
