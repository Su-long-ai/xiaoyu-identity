#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedicated loopback proxy for the RMB50 HaluMem dev gate.

This proxy does not authorize formal confirmatory execution. It accepts only the
fixed public pilot membership in BUDGET50_HALUMEM_DEV_GATE_V1.json and delegates
all paid transport/accounting to governance/research_api.py.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import research_api_proxy as base_proxy
from research_api import ResearchApiBudget, ResearchBudgetError

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_GATE_V1.json"
_THIS = Path(__file__).resolve()
_LOCK = threading.Lock()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    if not MANIFEST.is_file():
        raise ResearchBudgetError("budget50 dev manifest missing")
    m = json.loads(MANIFEST.read_text("utf-8"))
    if m.get("schema") != "xiaoyu-budget50-halumem-dev-gate-v1":
        raise ResearchBudgetError("budget50 dev manifest schema mismatch")
    if m.get("status") != "READY_FOR_BOUNDED_DEV_EXECUTION":
        raise ResearchBudgetError("budget50 dev manifest not executable")
    if _sha(_THIS) != (m.get("implementation") or {}).get("proxy_sha256"):
        raise ResearchBudgetError("budget50 dev proxy byte drift")
    return m


class Budget50DevBudget(ResearchApiBudget):
    """Exact-membership, serial, crash-fail-closed wrapper over ResearchApiBudget."""

    def chat(
        self,
        messages,
        *,
        max_tokens=500,
        purpose="research",
        timeout=75,
        phase=None,
        response_format=None,
        budget_scope=None,
        case_id=None,
        prompt_prefix_sha256=None,
        _proxy_auth=None,
    ):
        with _LOCK:
            m = _manifest()
            track = m["paid_track"]
            cfg = self._cfg()
            if cfg.get("budget_mode") != "BUDGET50_DEV_ONLY":
                raise ResearchBudgetError("budget50 dev proxy requires BUDGET50_DEV_ONLY policy mode")
            scope = str(budget_scope or "")
            if scope != track["scope"]:
                raise ResearchBudgetError("budget50 dev scope mismatch")
            cid = str(case_id or "")
            if cid not in set(track["case_ids"]):
                raise ResearchBudgetError("budget50 dev case outside frozen pilot membership")
            if int(max_tokens) > int(track["max_completion_tokens"]):
                raise ResearchBudgetError("budget50 dev max_tokens exceeds cap")
            if response_format != track["response_format"]:
                raise ResearchBudgetError("budget50 dev response_format mismatch")
            if str(prompt_prefix_sha256 or "") != str(track["invariant_prefix_sha256"]):
                raise ResearchBudgetError("budget50 dev invariant prefix mismatch")
            prior = self.recover_e2_case(cid)
            if prior is not None:
                raise ResearchBudgetError(
                    f"budget50 dev duplicate paid case blocked: {cid} already {prior.get('status')}"
                )

            # Bypass only the formal E2 membership switch in this dedicated
            # process. All token, proxy-auth, rolling/epoch, provider and global
            # budget guards in ResearchApiBudget remain active.
            e2 = self.policy.setdefault("e2_transition", {})
            old_stage = e2.get("current_stage")
            e2["current_stage"] = "BUDGET50_DEV"
            try:
                return super().chat(
                    messages,
                    max_tokens=max_tokens,
                    purpose=purpose,
                    timeout=timeout,
                    phase=phase,
                    response_format=response_format,
                    budget_scope=budget_scope,
                    case_id=case_id,
                    prompt_prefix_sha256=prompt_prefix_sha256,
                    _proxy_auth=_proxy_auth,
                )
            finally:
                e2["current_stage"] = old_stage


def main():
    base_proxy.ResearchApiBudget = Budget50DevBudget
    base_proxy.Handler.server_version = "XiaoYuBudget50DevProxy/1.0"
    base_proxy.main()


if __name__ == "__main__":
    main()
