from __future__ import annotations

import argparse
import re
from pathlib import Path


def _read(root: Path, relpath: str) -> str:
    path = root / relpath
    if not path.is_file():
        raise SystemExit(f"BLOCK_HOST_RESTART_CONTINUITY_PROBE: missing {relpath}")
    return path.read_text(encoding="utf-8")


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"BLOCK_HOST_RESTART_CONTINUITY_PROBE: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce the current N.E.K.O host-restart continuity gap without "
            "adding a private recovery authority. Any native continuation seam "
            "forces reuse re-evaluation."
        )
    )
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.neko_root.resolve()

    ledger = _read(root, "nekoclaw/host/ledger.py")
    agents = _read(root, "nekoclaw/host/task_agents.py")
    ledger_tests = _read(root, "tests/unit/nekoclaw/test_host_ledger.py")
    agent_tests = _read(root, "tests/unit/nekoclaw/test_host_task_agents.py")

    reconcile_start = ledger.find("    def _reconcile(")
    _require(reconcile_start >= 0, "Ledger._reconcile moved or disappeared; re-audit recovery ownership")
    reconcile_end = ledger.find("\n    # -- a stop of everything", reconcile_start)
    _require(reconcile_end > reconcile_start, "cannot isolate Ledger._reconcile; re-audit")
    reconcile = ledger[reconcile_start:reconcile_end]

    _require(
        "Fail what a previous host process left unfinished" in reconcile,
        "host-restart policy changed from explicit fail-on-open; re-audit before keeping this gap",
    )
    _require(
        "UPDATE host_calls SET status='interrupted'" in reconcile,
        "running host-call reconciliation changed; re-audit effect safety",
    )
    _require(
        re.search(
            r"status IN \('queued','working','waiting_user'\)",
            reconcile,
        ) is not None,
        "the prior-host active-status selection changed; re-audit continuation",
    )
    _require(
        'self._transition(conn, row["id"], "failed", HOST_ENDED_REASON' in reconcile,
        "prior-host active commissions are no longer unconditionally failed here; re-audit native continuation",
    )
    _require(
        "deferred_until IS NULL" in reconcile
        and "resting_since IS NOT NULL" in reconcile,
        "native preserved-state exceptions changed; re-audit restart semantics",
    )

    expected_ledger_test = (
        "async def test_unfinished_commissions_of_an_earlier_process_fail_on_open"
    )
    _require(expected_ledger_test in ledger_tests, "native ledger restart regression moved or disappeared")
    for expected in (
        '"queued": "failed"',
        '"working": "failed"',
        '"waiting": "failed"',
        '"blocked": "blocked"',
        '"deferred": "working"',
        '"expired": "working"',
    ):
        _require(expected in ledger_tests, f"native restart expectation changed: {expected}")

    _require(
        "async def test_what_an_earlier_process_left_unfinished_is_reported_with_its_failure"
        in ledger_tests,
        "native passive restart-failure delivery regression moved or disappeared",
    )
    _require(
        '"status": "failed", "delivery_mode": "passive"' in ledger_tests,
        "restart failure reporting semantics changed; re-audit native continuation",
    )

    # The resume substrate must remain native. If these disappear, a thin
    # continuation candidate must not pretend the existing session/runtime
    # machinery can still carry the work.
    for marker in (
        "async def test_an_answer_held_by_a_closing_session_survives_its_runtime_going_away",
        "async def test_a_blocked_commission_is_taken_up_again_where_it_stopped",
        "async def test_a_result_takes_up_again_a_parent_whose_idle_session_was_closed",
        'event.payload["resumed"]',
    ):
        _require(marker in agent_tests, f"native task-agent resume substrate changed: {marker}")

    _require(
        'if commission.status in ("blocked", "failed"):' in agents,
        "native transcript-tail take-up path changed; re-audit recovery reuse",
    )
    _require(
        "return await self.tell(commission_id, text" in agents,
        "native take-up/requeue path changed; re-audit recovery reuse",
    )

    # No private implementation is admitted by this probe. If upstream starts
    # retaining/requeueing old-host active work, the fail-on-open checks above
    # trip and force a new reuse decision instead of silently layering ours.
    print(
        "PASS: reproduced host-restart continuity gap "
        "(runtime/session resume substrate exists, but prior-host queued/working/"
        "waiting_user commissions are still failed and running calls marked interrupted)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
