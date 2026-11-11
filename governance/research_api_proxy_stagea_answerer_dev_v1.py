#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedicated bounded proxy for Stage-A grounded QA answerer tuning tranche v1.

TUNING ONLY. Never authorizes formal confirmatory execution.
"""
from __future__ import annotations
import hashlib,json,threading
from pathlib import Path
import research_api_proxy as base_proxy
from research_api import ResearchApiBudget,ResearchBudgetError

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
MANIFEST=GOV/"STAGEA_GROUNDED_ANSWERER_DEV_V1.json"
_THIS=Path(__file__).resolve()
_LOCK=threading.Lock()

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def manifest():
    if not MANIFEST.is_file(): raise ResearchBudgetError("answerer dev manifest missing")
    m=json.loads(MANIFEST.read_text("utf-8"))
    if m.get("schema")!="xiaoyu-stagea-grounded-answerer-dev-v1":
        raise ResearchBudgetError("answerer dev manifest schema mismatch")
    if m.get("status")!="TUNING_EXECUTION_AUTHORIZED":
        raise ResearchBudgetError("answerer dev manifest not executable")
    if sha(_THIS)!=(m.get("implementation") or {}).get("proxy_sha256"):
        raise ResearchBudgetError("answerer dev proxy byte drift")
    return m

class StageAAnswererBudget(ResearchApiBudget):
    def chat(self,messages,*,max_tokens=96,purpose="research",timeout=75,phase=None,
             response_format=None,budget_scope=None,case_id=None,prompt_prefix_sha256=None,
             _proxy_auth=None):
        with _LOCK:
            m=manifest(); track=m["paid_track"]; cfg=self._cfg()
            if cfg.get("budget_mode")!="BUDGET100_STAGEA_ANSWERER_DEV_V1":
                raise ResearchBudgetError("answerer dev proxy requires exact budget mode")
            scope=str(budget_scope or "")
            if scope!=track["scope"]: raise ResearchBudgetError("answerer dev scope mismatch")
            cid=str(case_id or "")
            if cid not in set(track["case_ids"]):
                raise ResearchBudgetError("answerer dev case outside frozen membership")
            if int(max_tokens)>int(track["max_completion_tokens"]):
                raise ResearchBudgetError("answerer dev max_tokens exceeds cap")
            if response_format!=track["response_format"]:
                raise ResearchBudgetError("answerer dev response_format mismatch")
            if str(prompt_prefix_sha256 or "")!=str(track["invariant_prefix_sha256"]):
                raise ResearchBudgetError("answerer dev invariant prefix mismatch")
            prior=self.recover_e2_case(cid)
            if prior is not None:
                raise ResearchBudgetError(
                    f"answerer dev duplicate paid case blocked: {cid} already {prior.get('status')}"
                )
            e2=self.policy.setdefault("e2_transition",{})
            old=e2.get("current_stage")
            e2["current_stage"]="STAGEA_ANSWERER_DEV"
            try:
                return super().chat(
                    messages,max_tokens=max_tokens,purpose=purpose,timeout=timeout,
                    phase=phase,response_format=response_format,budget_scope=budget_scope,
                    case_id=case_id,prompt_prefix_sha256=prompt_prefix_sha256,
                    _proxy_auth=_proxy_auth,
                )
            finally:
                e2["current_stage"]=old

def main():
    base_proxy.ResearchApiBudget=StageAAnswererBudget
    base_proxy.Handler.server_version="XiaoYuStageAAnswererProxy/1.0"
    base_proxy.main()

if __name__=="__main__": main()
