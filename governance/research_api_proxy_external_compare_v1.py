#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded loopback proxy for unified external-memory comparator runs.

Only the already allowlisted comparator tags are accepted. Formal E2 membership
routing is bypassed only inside this dedicated process because third-party
memory libraries cannot emit XiaoYu case headers. All provider transport,
durable accounting, token reservation, and global research budget logic remain
in ResearchApiBudget.

This process adds a stricter experiment-level cost fence: before every call,
the conservative upper-bound cost of comparator calls created since process
start must be < 9.0 CNY. The existing max-single-reservation guard leaves
additional headroom below the user's <10 CNY authorization.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import research_api_proxy as base_proxy
from research_api import ResearchApiBudget, ResearchBudgetError

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "governance" / "research_api_usage.sqlite3"
ALLOWED = {"proxy:hindsight", "proxy:mem0oss", "proxy:cognee"}
COST_STOP_BEFORE_CALL_CNY = 9.0

with sqlite3.connect(DB) as _c:
    START_ROWID = int(_c.execute("select coalesce(max(rowid),0) from calls").fetchone()[0])


class ExternalComparatorBudget(ResearchApiBudget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Handler inspects self.policy before calling chat(), so mark this
        # dedicated process as comparator-bounded at construction time.
        self.policy.setdefault("e2_transition", {})["current_stage"] = "EXTERNAL_COMPARATOR_BOUNDED"
        self.policy.setdefault("budget", {})["max_parallel_experiments"] = 4

    def _guard_cfg(self):
        g = dict(super()._guard_cfg())
        # Large enough for a full 200-question comparator, while this dedicated
        # proxy's experiment-level CNY fence is the controlling cap.
        g.update({
            "scope_raw_token_cap": 5_000_000,
            "scope_cache_miss_cap": 3_000_000,
            "scope_output_token_cap": 1_000_000,
            "scope_call_cap": 5_000,
            "scope_epoch_raw_token_cap": 5_000_000,
            "scope_epoch_cache_miss_cap": 3_000_000,
            "scope_epoch_output_token_cap": 1_000_000,
            "scope_epoch_call_cap": 5_000,
            "block_benchmark_weekday_peak": False,
        })
        return g

    def _comparator_cost_upper(self) -> float:
        marks = ",".join("?" for _ in ALLOWED)
        row = self.conn.execute(
            f"""select
                  coalesce(sum(prompt_tokens),0) prompt,
                  coalesce(sum(completion_tokens),0) completion,
                  coalesce(sum(cache_hit_tokens),0) hit,
                  coalesce(sum(cache_miss_tokens),0) miss
                from calls
               where rowid>? and status='COMMITTED'
                 and budget_scope in ({marks})""",
            (START_ROWID, *sorted(ALLOWED)),
        ).fetchone()
        cost = self._cost_range_from_counts(
            int(row["prompt"] or 0), int(row["completion"] or 0),
            int(row["hit"] or 0), int(row["miss"] or 0), self._pricing()
        )
        if not cost.get("available"):
            raise ResearchBudgetError("Comparator pricing unavailable; fail closed")
        return float(cost["conservative_cost_range_cny"][1])

    def chat(self, messages, *, budget_scope=None, **kwargs):
        scope = str(budget_scope or "")
        if scope not in ALLOWED:
            raise ResearchBudgetError(f"External comparator proxy refuses scope: {scope}")
        upper = self._comparator_cost_upper()
        if upper >= COST_STOP_BEFORE_CALL_CNY:
            raise ResearchBudgetError(
                f"External comparator experiment cost fence reached: upper_cny={upper:.6f}"
            )
        # Third-party libraries cannot attach XiaoYu E2 case/prefix headers.
        # This dedicated proxy changes only that routing dimension.
        e2 = self.policy.setdefault("e2_transition", {})
        old_stage = e2.get("current_stage")
        e2["current_stage"] = "EXTERNAL_COMPARATOR_BOUNDED"
        try:
            return super().chat(messages, budget_scope=budget_scope, **kwargs)
        finally:
            e2["current_stage"] = old_stage


def main():
    base_proxy.ResearchApiBudget = ExternalComparatorBudget
    base_proxy.Handler.server_version = "XiaoYuExternalComparatorProxy/1.0"
    base_proxy.main()


if __name__ == "__main__":
    main()
