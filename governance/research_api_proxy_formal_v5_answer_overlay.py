#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedicated paid proxy for formal HaluMem V5 post-seal answer overlay."""
from __future__ import annotations
import hashlib,json,threading,datetime,zoneinfo
from pathlib import Path
import research_api_proxy as base_proxy
from research_api import ResearchApiBudget,ResearchBudgetError

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
PROTOCOL=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_V1.json"
PROTOCOL_FREEZE=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_FREEZE_V1.json"
EXEC_FREEZE=GOV/"FORMAL_HALUMEM_V5_ANSWER_EXECUTION_FREEZE.json"
FORMAL_RUNTIME=GOV/"halumem_confirmatory_runtime_v2"
INPUT_SEAL=FORMAL_RUNTIME/"V5_ANSWER_OVERLAY_INPUT_SEAL.json"
_THIS=Path(__file__).resolve()
_LOCK=threading.Lock()
_CACHE=None

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))

def frozen():
    global _CACHE
    if _CACHE is not None:return _CACHE
    if not PROTOCOL.is_file() or not EXEC_FREEZE.is_file() or not INPUT_SEAL.is_file():
        raise ResearchBudgetError("formal V5 answer freeze material missing")
    p=load(PROTOCOL);e=load(EXEC_FREEZE);s=load(INPUT_SEAL)
    if p.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-v1" or p.get("status")!="PREFROZEN_FOR_INDEPENDENT_REVIEW":raise ResearchBudgetError("protocol candidate schema/status")
    if not PROTOCOL_FREEZE.is_file():raise ResearchBudgetError("protocol independent freeze missing")
    pf=load(PROTOCOL_FREEZE)
    if pf.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-freeze-v1" or pf.get("status")!="PROTOCOL_EXECUTION_READY" or pf.get("protocol_sha256")!=sha(PROTOCOL):raise ResearchBudgetError("protocol independent freeze drift")
    if e.get("schema")!="xiaoyu-formal-halumem-v5-answer-execution-freeze-v1" or e.get("status")!="ANSWER_EXECUTION_AUTHORIZED":
        raise ResearchBudgetError("answer execution freeze not authorized")
    if e.get("paid_execution_authorized") is not True or e.get("formal_gold_scoring_authorized") is not False:
        raise ResearchBudgetError("answer execution boundary drift")
    if e.get("protocol_sha256")!=sha(PROTOCOL) or e.get("input_seal_sha256")!=sha(INPUT_SEAL):
        raise ResearchBudgetError("answer execution binding drift")
    policy_path=GOV/"policy.json"
    if e.get("policy_sha256")!=sha(policy_path):
        raise ResearchBudgetError("answer execution policy binding drift")
    for name,b in (p.get("bindings") or {}).items():
        fp=ROOT/str(b.get("path") or "")
        if not fp.is_file() or sha(fp)!=b.get("sha256") or fp.stat().st_size!=int(b.get("bytes") or -1):
            raise ResearchBudgetError("protocol bound byte drift: "+str(name))
    if sha(_THIS)!=(p.get("implementation") or {}).get("answer_proxy_sha256"):
        raise ResearchBudgetError("answer proxy byte drift")
    if int(s.get("question_count") or 0)!=6282 or int(s.get("stream_count") or 0)!=36:
        raise ResearchBudgetError("answer input seal cardinality drift")
    m={}
    for spec in s.get("files") or []:
        fp=GOV/spec["path"]
        if not fp.is_file() or sha(fp)!=spec["sha256"]:raise ResearchBudgetError("answer input stream drift")
        obj=load(fp)
        for row in obj.get("rows") or []:
            cid=str(row["case_id"])
            if cid in m:raise ResearchBudgetError("duplicate formal answer case")
            m[cid]=row["request_messages_sha256"]
    if len(m)!=6282:raise ResearchBudgetError("formal answer membership drift")
    _CACHE=(p,e,s,m);return _CACHE

class FormalV5AnswerBudget(ResearchApiBudget):
    def chat(self,messages,*,max_tokens=96,purpose="research",timeout=75,phase=None,
             response_format=None,budget_scope=None,case_id=None,prompt_prefix_sha256=None,_proxy_auth=None):
        with _LOCK:
            p,e,s,members=frozen();track=p["answer_track"];cfg=self._cfg()
            if cfg.get("budget_mode")!="BUDGET100_FORMAL_HALUMEM_V5_ANSWER_OVERLAY":
                raise ResearchBudgetError("formal V5 answer proxy requires exact budget mode")
            scope=str(budget_scope or "")
            if scope!=track["scope"]:raise ResearchBudgetError("formal V5 answer scope mismatch")
            # This scope is conservatively >10 CNY at peak. Enforce off-peak here,
            # independently of mutable generic gateway policy.
            now=datetime.datetime.now(datetime.timezone.utc).astimezone(zoneinfo.ZoneInfo("Asia/Shanghai"))
            minute=now.hour*60+now.minute
            if now.weekday()<5 and ((540<=minute<720) or (840<=minute<1080)):
                raise ResearchBudgetError("formal V5 answer overlay is directly blocked in Beijing weekday peak hours")
            guard=self._guard_cfg()
            effective=((guard.get("scope_overrides") or {}).get(scope) or {})
            expected=track.get("runtime_caps") or {}
            keymap={
              "rolling_raw_token_cap":"rolling_raw_token_cap",
              "rolling_cache_miss_cap":"rolling_cache_miss_cap",
              "rolling_output_token_cap":"rolling_output_token_cap",
              "rolling_call_cap":"rolling_call_cap",
              "epoch_raw_token_cap":"epoch_raw_token_cap",
              "epoch_cache_miss_cap":"epoch_cache_miss_cap",
              "epoch_output_token_cap":"epoch_output_token_cap",
              "epoch_call_cap":"epoch_call_cap",
            }
            for ek,gk in keymap.items():
                if int(effective.get(gk) or -1)!=int(expected.get(ek) or -2):
                    raise ResearchBudgetError("formal V5 runtime cap drift: "+ek)
            cid=str(case_id or "")
            if cid not in members:raise ResearchBudgetError("formal V5 answer case outside frozen membership")
            if stable(messages)!=members[cid]:raise ResearchBudgetError("formal V5 full request messages drift")
            if int(max_tokens)!=int(track["max_completion_tokens"]):raise ResearchBudgetError("formal V5 max_tokens must equal frozen value")
            if response_format!=track["response_format"]:raise ResearchBudgetError("formal V5 response format drift")
            if str(prompt_prefix_sha256 or "")!=str(track["invariant_prefix_sha256"]):
                raise ResearchBudgetError("formal V5 invariant prefix drift")
            prior=self.recover_e2_case(cid)
            if prior is not None:
                raise ResearchBudgetError(f"formal V5 duplicate paid case blocked: {cid} already {prior.get('status')}")
            e2=self.policy.setdefault("e2_transition",{})
            old=e2.get("current_stage");e2["current_stage"]="FORMAL_HALUMEM_V5_ANSWER_OVERLAY"
            try:
                return super().chat(messages,max_tokens=max_tokens,purpose=purpose,timeout=timeout,phase=phase,
                  response_format=response_format,budget_scope=budget_scope,case_id=case_id,
                  prompt_prefix_sha256=prompt_prefix_sha256,_proxy_auth=_proxy_auth)
            finally:e2["current_stage"]=old

def main():
    base_proxy.ResearchApiBudget=FormalV5AnswerBudget
    base_proxy.Handler.server_version="XiaoYuFormalV5AnswerProxy/1.0"
    base_proxy.main()

if __name__=="__main__":main()
