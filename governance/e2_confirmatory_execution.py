# -*- coding: utf-8 -*-
"""Fail-closed authorization helpers for XiaoYu E2 HaluMem confirmatory execution.

This module is inert in PREFREEZE. It does not read HaluMem dataset records.
A paid confirmatory semantic call is authorized only after an independently
reviewed final freeze record binds the exact manifest, runner and gateway bytes.
"""
from __future__ import annotations
import hashlib, json, re, sqlite3
from pathlib import Path

class ConfirmatoryGateError(RuntimeError):
    pass

HALU_CASE_RE=re.compile(r"^hm-c-(m|l)-([0-9a-f]{12})-s([0-9]{1,6})-t([0-9]{1,6})$")
LME_CASE_RE=re.compile(r"^lme-c-([0-9]{3})$")

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def load_json(path:Path)->dict:
    obj=json.loads(path.read_text("utf-8"))
    if not isinstance(obj,dict):
        raise ConfirmatoryGateError(f"expected JSON object: {path}")
    return obj

def _bound_file(root:Path,rel:str,expected:str,label:str)->Path:
    p=root/str(rel)
    if not p.is_file():
        raise ConfirmatoryGateError(f"{label} missing")
    got=sha_file(p)
    if not expected or got!=str(expected):
        raise ConfirmatoryGateError(f"{label} SHA mismatch")
    return p

def load_manifest(root:Path, *, require_authorized:bool=False)->tuple[dict,dict]:
    root=Path(root)
    policy=load_json(root/"governance"/"policy.json")
    e2=policy.get("e2_transition") or {}
    rel=e2.get("confirmatory_execution_manifest")
    expected=e2.get("confirmatory_execution_manifest_sha256")
    if not rel or not expected:
        raise ConfirmatoryGateError("confirmatory execution manifest is not policy-bound")
    mp=_bound_file(root,str(rel),str(expected),"confirmatory execution manifest")
    manifest=load_json(mp)
    if manifest.get("schema")!="xiaoyu-e2-confirmatory-execution-manifest-v1":
        raise ConfirmatoryGateError("unsupported confirmatory execution manifest schema")
    if manifest.get("status")!="FROZEN_SPEC_AWAITING_FINAL_FREEZE":
        raise ConfirmatoryGateError("confirmatory execution manifest is not frozen-spec candidate")
    split=root/"governance"/"E2_SPLIT_MANIFEST.json"
    if not split.is_file() or sha_file(split)!=manifest.get("split_manifest_sha256"):
        raise ConfirmatoryGateError("confirmatory split binding drift")
    if manifest.get("confirmatory_execution_allowed") is not False:
        raise ConfirmatoryGateError("prefreeze manifest must not self-authorize execution")

    if not require_authorized:
        return policy,manifest

    if e2.get("current_stage")!="E2_CONFIRMATORY":
        raise ConfirmatoryGateError("current stage is not E2_CONFIRMATORY")
    if e2.get("confirmatory_calls_allowed") is not True:
        raise ConfirmatoryGateError("policy does not allow confirmatory calls")
    frel=e2.get("confirmatory_freeze_record")
    fsha=e2.get("confirmatory_freeze_record_sha256")
    if not frel or not fsha:
        raise ConfirmatoryGateError("final confirmatory freeze record is not policy-bound")
    fp=_bound_file(root,str(frel),str(fsha),"final confirmatory freeze record")
    freeze=load_json(fp)
    if freeze.get("schema")!="xiaoyu-e2-confirmatory-final-freeze-v1":
        raise ConfirmatoryGateError("unsupported final freeze schema")
    if freeze.get("confirmatory_execution_allowed") is not True:
        raise ConfirmatoryGateError("final freeze does not authorize confirmatory execution")
    if freeze.get("reaudit_decision")!="READY_FOR_CONFIRMATORY_FREEZE":
        raise ConfirmatoryGateError("final independent v2 re-audit decision is not ready")
    independent=_validate_independent_reaudit(root,freeze)
    if independent.get("decision")!=freeze.get("reaudit_decision"):
        raise ConfirmatoryGateError("freeze/re-audit decision binding mismatch")
    bindings=freeze.get("bindings") or {}
    if bindings.get("confirmatory_execution_manifest_sha256")!=sha_file(mp):
        raise ConfirmatoryGateError("freeze/manifest binding drift")

    gov=root/"governance"
    required={
      "halumem_runner_sha256": gov/"confirmatory_frozen"/"HALUMEM_CONFIRMATORY_RUNNER.py",
      "lme_runner_sha256": gov/"confirmatory_frozen"/"LME_CONFIRMATORY_RUNNER.py",
      "research_api_sha256": gov/"research_api.py",
      "research_api_proxy_sha256": gov/"research_api_proxy.py",
      "confirmatory_gate_sha256": gov/"e2_confirmatory_execution.py",
      "halumem_judge_binding_sha256": gov/"confirmatory_frozen"/"HALUMEM_JUDGE_BINDING.json",
      "halumem_judge_calibration_sha256": gov/"confirmatory_frozen"/"HALUMEM_JUDGE_CALIBRATION_V1.json",
    }
    for key,path in required.items():
        expected_sha=str(bindings.get(key) or "")
        if not path.is_file() or not expected_sha or sha_file(path)!=expected_sha:
            raise ConfirmatoryGateError(f"final freeze exact-byte binding failed: {key}")
    return policy,manifest

def _validate_independent_reaudit(root:Path, freeze:dict)->dict:
    """Bind final execution authorization to the exact independent final-v2 re-audit.

    This is a procedural provenance check, not an OS/IAM boundary. It prevents a
    bare READY string in a Lead-authored freeze from satisfying the mechanical
    execution gate without the independent auditor artifacts that produced it.
    """
    root=Path(root)
    binding=freeze.get("independent_reaudit")
    if not isinstance(binding,dict):
        raise ConfirmatoryGateError("final freeze missing independent re-audit binding")

    required_text=(
        "submission_id","lease_id","agent_id","family","decision",
        "result_path","result_sha256","receipt_path","receipt_sha256",
        "reaudit_manifest_path","reaudit_manifest_sha256",
    )
    for key in required_text:
        if not str(binding.get(key) or "").strip():
            raise ConfirmatoryGateError(f"independent re-audit binding missing: {key}")
    if binding["decision"]!="READY_FOR_CONFIRMATORY_FREEZE":
        raise ConfirmatoryGateError("independent re-audit binding decision is not ready")
    if binding["family"]!="audit.e2.confirmatory.final_v2_reaudit":
        raise ConfirmatoryGateError("independent re-audit family mismatch")

    result_path=_bound_file(
        root,str(binding["result_path"]),str(binding["result_sha256"]),
        "independent re-audit result")
    receipt_path=_bound_file(
        root,str(binding["receipt_path"]),str(binding["receipt_sha256"]),
        "independent re-audit receipt")
    reaudit_path=_bound_file(
        root,str(binding["reaudit_manifest_path"]),str(binding["reaudit_manifest_sha256"]),
        "final-v2 re-audit manifest")

    result=load_json(result_path)
    receipt=load_json(receipt_path)
    if result.get("decision")!=binding["decision"]:
        raise ConfirmatoryGateError("independent re-audit result decision mismatch")
    if receipt.get("schema")!="fish-evidence-receipt-v1":
        raise ConfirmatoryGateError("independent re-audit receipt schema mismatch")
    if receipt.get("lease_id")!=binding["lease_id"]:
        raise ConfirmatoryGateError("independent re-audit receipt lease mismatch")
    if receipt.get("manifest_relative")!="result.json":
        raise ConfirmatoryGateError("independent re-audit receipt manifest path mismatch")
    if receipt.get("manifest_sha256")!=binding["result_sha256"]:
        raise ConfirmatoryGateError("independent re-audit receipt/result binding mismatch")

    expected_parent=(root/"governance"/"workspaces"/str(binding["lease_id"])).resolve()
    if result_path.resolve()!=expected_parent/"result.json":
        raise ConfirmatoryGateError("independent re-audit result is outside bound auditor workspace")
    if receipt_path.resolve()!=expected_parent/"receipt.json":
        raise ConfirmatoryGateError("independent re-audit receipt is outside bound auditor workspace")
    expected_reaudit=(root/"governance"/"E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.json").resolve()
    if reaudit_path.resolve()!=expected_reaudit:
        raise ConfirmatoryGateError("independent re-audit manifest path mismatch")

    registry=root/"governance"/"registry.sqlite3"
    if not registry.is_file():
        raise ConfirmatoryGateError("governance registry missing for independent re-audit binding")
    db=sqlite3.connect(str(registry))
    db.row_factory=sqlite3.Row
    try:
        row=db.execute(
            """select s.submission_id,s.manifest_sha,s.receipt_sha,s.evidence_label,
                      l.lease_id,l.agent_id,l.role,l.family,l.state
               from submissions s join leases l on l.lease_id=s.lease_id
               where s.submission_id=?""",
            (str(binding["submission_id"]),),
        ).fetchone()
    finally:
        db.close()
    if row is None:
        raise ConfirmatoryGateError("independent re-audit submission absent from registry")
    checks={
        "manifest_sha":binding["result_sha256"],
        "receipt_sha":binding["receipt_sha256"],
        "lease_id":binding["lease_id"],
        "agent_id":binding["agent_id"],
        "role":"auditor",
        "family":binding["family"],
        "state":"SUBMITTED",
    }
    for key,expected in checks.items():
        if str(row[key])!=str(expected):
            raise ConfirmatoryGateError(f"independent re-audit registry mismatch: {key}")
    return binding

def semantic_track(manifest:dict)->dict:
    track=((manifest.get("tracks") or {}).get("halumem_semantic_projection"))
    if not isinstance(track,dict):
        raise ConfirmatoryGateError("semantic projection track missing")
    return track

def validate_confirmatory_case(manifest:dict, scope:str, case_id:str)->dict:
    tracks=manifest.get("tracks") or {}
    matches=[(name,t) for name,t in tracks.items()
             if isinstance(t,dict) and str(t.get("scope") or "")==str(scope)]
    if len(matches)!=1:
        raise ConfirmatoryGateError("confirmatory scope is not uniquely frozen")
    name,track=matches[0]
    cid=str(case_id or "")
    if name=="longmemeval_answer":
        if not LME_CASE_RE.fullmatch(cid):
            raise ConfirmatoryGateError("invalid LongMemEval confirmatory case_id")
        allowed=set(str(x) for x in (track.get("allowed_case_ids") or []))
        if cid not in allowed:
            raise ConfirmatoryGateError("LongMemEval case_id outside frozen confirmatory membership")
        return {"track_name":name,"case_id":cid,"stream_key":"lme","track":track}

    if name!="halumem_semantic_projection":
        raise ConfirmatoryGateError("unsupported confirmatory track")
    m=HALU_CASE_RE.fullmatch(cid)
    if not m:
        raise ConfirmatoryGateError("invalid confirmatory semantic case_id")
    variant,prefix,session_s,turn_s=m.groups()
    hashes=[str(x) for x in (track.get("allowed_uuid_hashes") or [])]
    hm=[h for h in hashes if h.startswith(prefix)]
    if len(hm)!=1:
        raise ConfirmatoryGateError("case_id UUID hash prefix is not uniquely frozen")
    if variant not in set(track.get("variants") or []):
        raise ConfirmatoryGateError("case_id variant is outside frozen track")
    session=int(session_s);turn=int(turn_s)
    max_session=int(track.get("max_session_index") or 0)
    max_turn=int(track.get("max_turn_index") or 0)
    if max_session<=0 or session>max_session or max_turn<=0 or turn>max_turn:
        raise ConfirmatoryGateError("case_id session/turn index exceeds frozen structural cap")
    return {
      "track_name":name,"variant":variant,"uuid_hash":hm[0],"uuid_hash_prefix":prefix,
      "session_index":session,"turn_index":turn,
      "stream_key":f"{variant}:{prefix}","track":track,
    }

def validate_semantic_case(manifest:dict, scope:str, case_id:str)->dict:
    meta=validate_confirmatory_case(manifest,scope,case_id)
    if meta.get("track_name")!="halumem_semantic_projection":
        raise ConfirmatoryGateError("scope is not HaluMem semantic projection")
    return meta

def assert_runner_authorized(root:Path)->dict:
    _policy,manifest=load_manifest(root,require_authorized=True)
    return manifest
