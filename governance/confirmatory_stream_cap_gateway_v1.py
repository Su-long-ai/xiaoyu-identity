#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audited post-entry cap amendment shim for HaluMem confirmatory recovery.

This module does not replace XiaoYu's frozen research_api.py or base gate.
It wraps only validate_confirmatory_case() inside a dedicated recovery proxy
process after a separately audited/frozen amendment authorizes two numeric caps.

All membership, prompt, response-format, completion-token, duplicate-case,
UNKNOWN and recovery semantics continue to come from the exact frozen base gate.
"""
from __future__ import annotations
import copy, hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
AMEND=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
FREEZE=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE_V1.json"
POLICY=GOV/"policy.json"
BASE_MANIFEST=GOV/"E2_CONFIRMATORY_EXECUTION_MANIFEST_CANDIDATE.json"
BASE_FREEZE=GOV/"E2_CONFIRMATORY_FINAL_FREEZE_RECORD.json"
RECOVERY_MANIFEST=GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json"
RECOVERY_FREEZE=GOV/"E2_CONFIRMATORY_RECOVERY_V2_FINAL_FREEZE_RECORD.json"
SAFE_COUNTS=GOV/"lead_workspaces"/"halumem_stream_shape_20261029"/"HALUMEM_SAFE_STREAM_COUNTS.json"
BASE_RESEARCH_API=GOV/"research_api.py"
BASE_PROXY=GOV/"research_api_proxy.py"
HALU_SCOPE="proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"

import research_api as base_api
from research_api import ResearchBudgetError

class CapAmendmentError(RuntimeError):
    pass

_ORIGINAL_VALIDATE=None
_INSTALLED=False
_AUTHORIZED=None

def sha_file(path:Path)->str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_json(path:Path)->dict:
    x=json.loads(Path(path).read_text("utf-8"))
    if not isinstance(x,dict):raise CapAmendmentError("expected object: "+str(path))
    return x

def _bound(path:Path,expected:str,label:str)->Path:
    path=Path(path)
    if not path.is_file():raise CapAmendmentError(label+" missing")
    got=sha_file(path)
    if not expected or got!=str(expected):raise CapAmendmentError(label+" SHA drift")
    return path

def load_authorized_amendment()->dict:
    policy=load_json(POLICY)
    e2=policy.get("e2_transition") or {}
    rel=str(AMEND.relative_to(ROOT)).replace("\\","/")
    rows=e2.get("execution_amendments") or []
    entry=next((x for x in rows if isinstance(x,dict) and x.get("path")==rel),None)
    if entry is None:raise CapAmendmentError("stream-cap amendment is not policy-registered")
    _bound(AMEND,str(entry.get("sha256") or ""),"stream-cap amendment")

    frel=e2.get("halumem_stream_cap_amendment_freeze")
    fsha=e2.get("halumem_stream_cap_amendment_freeze_sha256")
    if frel!=str(FREEZE.relative_to(ROOT)).replace("\\","/") or not fsha:
        raise CapAmendmentError("stream-cap amendment final freeze is not policy-bound")
    _bound(FREEZE,str(fsha),"stream-cap amendment final freeze")

    a=load_json(AMEND);f=load_json(FREEZE)
    if a.get("schema")!="xiaoyu-e2-execution-amendment-v1" or a.get("status")!="FROZEN_POST_ENTRY_AMENDMENT":
        raise CapAmendmentError("bad stream-cap amendment schema/status")
    if f.get("schema")!="xiaoyu-e2-halumem-stream-cap-amendment-freeze-v1":
        raise CapAmendmentError("bad stream-cap amendment freeze schema")
    if f.get("status")!="STREAM_CAP_AMENDMENT_EXECUTION_AUTHORIZED" or f.get("execution_allowed") is not True:
        raise CapAmendmentError("stream-cap amendment is not execution-authorized")
    if f.get("amendment_sha256")!=sha_file(AMEND):
        raise CapAmendmentError("amendment/freeze binding drift")

    parents=a.get("parents") or {}
    expected_parents={
      "base_execution_manifest":BASE_MANIFEST,
      "base_final_freeze":BASE_FREEZE,
      "recovery_v2_manifest":RECOVERY_MANIFEST,
      "recovery_v2_final_freeze":RECOVERY_FREEZE,
    }
    for k,p in expected_parents.items():
        if parents.get(k,{}).get("sha256")!=sha_file(p):
            raise CapAmendmentError("parent drift: "+k)

    source=a.get("safe_structural_count") or {}
    _bound(SAFE_COUNTS,str(source.get("sha256") or ""),"safe structural count")
    counts=load_json(SAFE_COUNTS)
    cs=counts.get("confirmatory") or {}
    ctl=counts.get("controls") or {}
    if ctl.get("pilot_control_pass") is not True or int(ctl.get("pilot_user_turns_observed") or -1)!=7900:
        raise CapAmendmentError("safe structural scanner pilot control failed")
    delta=a.get("cap_delta") or {}
    if int(cs.get("total_semantic_calls_required") or -1)!=int(delta.get("new_max_case_calls") or -2):
        raise CapAmendmentError("total call cap not derived from safe structural count")
    if int(cs.get("max_semantic_calls_per_stream") or -1)!=int(delta.get("new_max_calls_per_stream") or -2):
        raise CapAmendmentError("stream cap not derived from safe structural count")
    if int(delta.get("old_max_case_calls") or -1)!=10000 or int(delta.get("old_max_calls_per_stream") or -1)!=768:
        raise CapAmendmentError("old cap ancestry drift")

    # Keep exact original gateway bytes as explicit ancestry.
    impl=a.get("base_gateway") or {}
    if impl.get("research_api_sha256")!=sha_file(BASE_RESEARCH_API):
        raise CapAmendmentError("base research_api drift")
    if impl.get("research_api_proxy_sha256")!=sha_file(BASE_PROXY):
        raise CapAmendmentError("base research_api_proxy drift")

    # Final freeze binds the amendment implementation exact bytes.
    for key in ("gateway","proxy"):
        row=(f.get("implementation_bindings") or {}).get(key) or {}
        p=ROOT/str(row.get("path") or "")
        _bound(p,str(row.get("sha256") or ""),"amendment implementation "+key)
    return a

def amended_case_meta(meta:dict,amendment:dict)->dict:
    out=copy.deepcopy(meta)
    if out.get("track_name")!="halumem_semantic_projection":
        return out
    track=out.get("track") or {}
    delta=amendment.get("cap_delta") or {}
    if int(track.get("max_case_calls") or -1)!=int(delta.get("old_max_case_calls") or -2):
        raise CapAmendmentError("live base max_case_calls drift")
    if int(track.get("max_calls_per_stream") or -1)!=int(delta.get("old_max_calls_per_stream") or -2):
        raise CapAmendmentError("live base max_calls_per_stream drift")
    track["max_case_calls"]=int(delta["new_max_case_calls"])
    track["max_calls_per_stream"]=int(delta["new_max_calls_per_stream"])
    out["track"]=track
    return out

def install_authorized_amendment()->dict:
    global _ORIGINAL_VALIDATE,_INSTALLED,_AUTHORIZED
    if _INSTALLED:return _AUTHORIZED
    amendment=load_authorized_amendment()
    original=base_api.confirmatory_gate.validate_confirmatory_case
    _ORIGINAL_VALIDATE=original
    def wrapped(manifest:dict,scope:str,case_id:str)->dict:
        meta=original(manifest,scope,case_id)
        return amended_case_meta(meta,amendment)
    base_api.confirmatory_gate.validate_confirmatory_case=wrapped
    _AUTHORIZED=amendment;_INSTALLED=True
    return amendment

class RecoveryCapBudget(base_api.ResearchApiBudget):
    """Original durable budget with Halu-only execution in amended proxy."""
    def chat(self,messages,**kwargs):
        cfg=self._cfg()
        e2=self.policy.get("e2_transition") or {}
        if cfg.get("active_phase")=="benchmark" and str(e2.get("current_stage") or "")=="E2_CONFIRMATORY":
            scope=str(kwargs.get("budget_scope") or "")
            if scope!=HALU_SCOPE:
                raise ResearchBudgetError("amended recovery proxy authorizes HaluMem confirmatory scope only")
        return super().chat(messages,**kwargs)
