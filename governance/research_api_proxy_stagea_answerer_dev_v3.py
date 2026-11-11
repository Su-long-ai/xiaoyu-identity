#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedicated bounded proxy for Stage-A grounded QA answerer tuning tranche v3.

PREFROZEN/TUNING ONLY. The manifest must explicitly authorize execution.
Never authorizes formal confirmatory execution.
"""
from __future__ import annotations
import hashlib,json,threading
from pathlib import Path
import research_api_proxy as base_proxy
from research_api import ResearchApiBudget,ResearchBudgetError

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
MANIFEST=GOV/"STAGEA_GROUNDED_ANSWERER_DEV_V3.json"
INPUTS=GOV/"stagea_answerer_dev_v3_inputs.json"
_THIS=Path(__file__).resolve()
_LOCK=threading.Lock()

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def manifest():
    if not MANIFEST.is_file(): raise ResearchBudgetError("answerer dev v3 manifest missing")
    m=json.loads(MANIFEST.read_text("utf-8"))
    if m.get("schema")!="xiaoyu-stagea-grounded-answerer-dev-v3":
        raise ResearchBudgetError("answerer dev v3 manifest schema mismatch")
    if m.get("status")!="TUNING_EXECUTION_AUTHORIZED" or m.get("paid_execution_authorized") is not True:
        raise ResearchBudgetError("answerer dev v3 manifest not executable")
    if m.get("formal_confirmatory_authorized") is not False:
        raise ResearchBudgetError("formal confirmatory boundary drift")
    if sha(INPUTS)!=m.get("inputs_sha256"):
        raise ResearchBudgetError("answerer dev v3 inputs byte drift")
    if sha(_THIS)!=(m.get("implementation") or {}).get("proxy_sha256"):
        raise ResearchBudgetError("answerer dev v3 proxy byte drift")
    return m

class StageAAnswererV3Budget(ResearchApiBudget):
    def chat(self,messages,*,max_tokens=96,purpose="research",timeout=75,phase=None,
             response_format=None,budget_scope=None,case_id=None,prompt_prefix_sha256=None,
             _proxy_auth=None):
        with _LOCK:
            m=manifest(); track=m["paid_track"]; cfg=self._cfg()
            if cfg.get("budget_mode")!="BUDGET100_STAGEA_ANSWERER_DEV_V3":
                raise ResearchBudgetError("answerer dev v3 proxy requires exact budget mode")
            scope=str(budget_scope or "")
            if scope!=track["scope"]: raise ResearchBudgetError("answerer dev v3 scope mismatch")
            cid=str(case_id or "")
            if cid not in set(track["case_ids"]):
                raise ResearchBudgetError("answerer dev v3 case outside frozen membership")
            inputs=json.loads(INPUTS.read_text("utf-8"))
            frozen={x["case_id"]:x for x in inputs.get("rows",[])}
            if set(frozen)!=set(track["case_ids"]) or len(frozen)!=10:
                raise ResearchBudgetError("answerer dev v3 frozen input membership drift")
            expected=frozen[cid].get("request_messages_sha256")
            if stable(messages)!=expected:
                raise ResearchBudgetError("answerer dev v3 full request messages drift")
            if int(max_tokens)>int(track["max_completion_tokens"]):
                raise ResearchBudgetError("answerer dev v3 max_tokens exceeds cap")
            if response_format!=track["response_format"]:
                raise ResearchBudgetError("answerer dev v3 response_format mismatch")
            if str(prompt_prefix_sha256 or "")!=str(track["invariant_prefix_sha256"]):
                raise ResearchBudgetError("answerer dev v3 invariant prefix mismatch")
            prior=self.recover_e2_case(cid)
            if prior is not None:
                raise ResearchBudgetError(
                    f"answerer dev v3 duplicate paid case blocked: {cid} already {prior.get('status')}"
                )
            e2=self.policy.setdefault("e2_transition",{})
            old=e2.get("current_stage"); e2["current_stage"]="STAGEA_ANSWERER_DEV_V3"
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
    base_proxy.ResearchApiBudget=StageAAnswererV3Budget
    base_proxy.Handler.server_version="XiaoYuStageAAnswererProxy/3.0"
    base_proxy.main()

if __name__=="__main__": main()
