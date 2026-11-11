# -*- coding: utf-8 -*-
"""Register one prospectively frozen low-cost non-formal paid research scope.

This is a control-plane admission helper. It does not call a provider.
It reuses research_api.py's existing prefrozen-mainline admission path so the
formal E2 gate remains fail-closed for every unregistered scope.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sqlite3, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
POLICY = GOV / "policy.json"
BACKLOG = GOV / "RESEARCH_BACKLOG.json"
REG_DIR = GOV / "auto_paid_scopes"
USAGE_DB = GOV / "research_api_usage.sqlite3"
LEASE_DB = GOV / "registry.sqlite3"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SCOPE_RE = re.compile(r"^proxy:xiaoyu:[a-z0-9][a-z0-9_.:-]{2,100}$")
CASE_RE = re.compile(r"^[A-Za-z0-9_.:-]{3,160}$")

class AdmissionError(RuntimeError):
    pass

def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha_path(p: Path) -> str:
    return sha_bytes(p.read_bytes())

def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body=(json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(body); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def project_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()

def resolve_rel(raw: str) -> Path:
    p=Path(str(raw))
    if p.is_absolute() or ".." in p.parts:
        raise AdmissionError("path must be project-relative")
    q=(ROOT/p).resolve()
    if not q.is_relative_to(ROOT):
        raise AdmissionError("path escapes project root")
    return q

def get_paid_cfg(policy):
    try:
        return policy["budget"]["paid_research"]
    except Exception as exc:
        raise AdmissionError("paid research policy missing") from exc

def get_active_lease(lease_id: str):
    con=sqlite3.connect(LEASE_DB)
    con.row_factory=sqlite3.Row
    try:
        row=con.execute("select * from leases where lease_id=?",(lease_id,)).fetchone()
        if row is None:
            raise AdmissionError("lease not found")
        d=dict(row)
        if d.get("state")!="ACTIVE":
            raise AdmissionError("paid-scope registration requires an ACTIVE lease")
        if d.get("role")!="research_engineer":
            raise AdmissionError("only research_engineer leases may auto-register paid research")
        return d
    finally:
        con.close()

def require_bound_backlog_active(lease: dict):
    backlog_id=str(lease.get("backlog_id") or "").strip()
    if not backlog_id:
        return
    backlog=load_json(BACKLOG)
    row=next(
        (x for x in (backlog.get("candidates") or [])
         if isinstance(x,dict) and str(x.get("id") or "")==backlog_id),
        None,
    )
    if row is None:
        raise AdmissionError("paid-scope registration bound backlog is missing")
    if str(row.get("status") or "")!="active":
        raise AdmissionError(
            "paid-scope registration requires bound backlog to remain active"
        )

def no_prior_paid_attempt(scope: str):
    if not USAGE_DB.exists():
        return
    con=sqlite3.connect(USAGE_DB)
    con.row_factory=sqlite3.Row
    try:
        row=con.execute(
            "select count(*) as n from calls where budget_scope=? and status in ('RESERVED','COMMITTED','UNKNOWN')",
            (scope,)
        ).fetchone()
        if int(row["n"] or 0):
            raise AdmissionError("scope already has reserved/committed/unknown paid calls; late registration forbidden")
    finally:
        con.close()

def revalidate_source_binding(manifest: dict) -> dict:
    """Re-read mutable source authority immediately before publication.

    Registration is not the execution authority: research_api.py rechecks the
    same source lease/backlog again at every reservation. This function prevents
    publishing an already-stale manifest and, critically, never rewrites the
    source RESEARCH_BACKLOG snapshot.
    """
    auto=manifest.get("auto_registration") or {}
    lease_id=str(auto.get("lease_id") or "")
    lease=get_active_lease(lease_id)
    if str(auto.get("agent_id") or "")!=str(lease.get("agent_id") or ""):
        raise AdmissionError("auto registration source agent drift")
    expected_worker=str(auto.get("worker_instance_id") or "")
    current_worker=str(lease.get("worker_instance_id") or "")
    if expected_worker and current_worker!=expected_worker:
        raise AdmissionError("auto registration source worker_instance drift")
    expected_backlog=str(auto.get("bound_backlog_id") or "")
    current_backlog=str(lease.get("backlog_id") or "")
    if current_backlog!=expected_backlog:
        raise AdmissionError("auto registration source backlog binding drift")
    require_bound_backlog_active(lease)

    req_rel=str(auto.get("source_request") or "")
    req_sha=str(auto.get("source_request_sha256") or "")
    req_path=resolve_rel(req_rel)
    if not req_rel or not req_sha or not req_path.is_file() or sha_path(req_path)!=req_sha:
        raise AdmissionError("auto registration source request drift")
    workspace=Path(lease["workspace"]).resolve()
    if not req_path.resolve().is_relative_to(workspace):
        raise AdmissionError("auto registration source request left active workspace")

    freeze=manifest.get("freeze") or {}
    fp=resolve_rel(str(freeze.get("path") or ""))
    if not fp.is_file() or sha_path(fp)!=str(freeze.get("sha256") or ""):
        raise AdmissionError("auto registration freeze drift")
    no_prior_paid_attempt(str(manifest.get("scope") or ""))
    return lease

def validate_request(req_path: Path):
    policy=load_json(POLICY)
    paid=get_paid_cfg(policy)
    req=load_json(req_path)
    if req.get("schema")!="xiaoyu-auto-paid-scope-request-v1":
        raise AdmissionError("unsupported request schema")
    if req.get("status")!="FROZEN_REQUEST":
        raise AdmissionError("request status must be FROZEN_REQUEST")
    lease_id=str(req.get("lease_id") or "")
    lease=get_active_lease(lease_id)
    require_bound_backlog_active(lease)
    workspace=Path(lease["workspace"]).resolve()
    if not req_path.resolve().is_relative_to(workspace):
        raise AdmissionError("request must live inside the active lease workspace")
    if str(req.get("agent_id") or "")!=str(lease["agent_id"]):
        raise AdmissionError("request agent_id does not own active lease")

    scope=str(req.get("scope") or "")
    if not SCOPE_RE.fullmatch(scope):
        raise AdmissionError("scope must be a bounded proxy:xiaoyu:* identifier")
    if scope.startswith("proxy:xiaoyu:e2_") or ":formal" in scope or ":blind" in scope:
        raise AdmissionError("formal/blind/E2 scopes may not use low-cost auto registration")
    if str(req.get("phase") or "")!="benchmark":
        raise AdmissionError("auto registration is benchmark phase only")

    boundaries=req.get("boundaries") or {}
    if boundaries.get("private_identity_data") is not False:
        raise AdmissionError("private identity data is forbidden for auto registration")
    if boundaries.get("blind_or_formal_data") is not False:
        raise AdmissionError("blind/formal data is forbidden for auto registration")
    if boundaries.get("product_mutation") is not False:
        raise AdmissionError("product mutation is forbidden for auto registration")

    freeze=req.get("freeze") or {}
    freeze_path=resolve_rel(str(freeze.get("path") or ""))
    if not freeze_path.is_file() or not freeze_path.resolve().is_relative_to(workspace):
        raise AdmissionError("freeze must be an existing file inside active lease workspace")
    expected_freeze=str(freeze.get("sha256") or "")
    if not HEX64.fullmatch(expected_freeze) or sha_path(freeze_path)!=expected_freeze:
        raise AdmissionError("freeze hash mismatch")
    freeze_obj=load_json(freeze_path)
    frozen=(freeze_obj.get("frozen_before_provider_execution") is True or
            str(freeze_obj.get("status") or "").startswith("FROZEN"))
    if not frozen:
        raise AdmissionError("freeze does not assert pre-provider freezing")

    auth_cfg=paid.get("auto_scope_authorization") or {}
    if auth_cfg.get("enabled") is not True or auth_cfg.get("strict_less_than") is not True:
        raise AdmissionError("owner low-cost auto authorization is not active")
    threshold=float(auth_cfg.get("threshold_cny") or 0)
    auth_path=resolve_rel(str(auth_cfg.get("record") or ""))
    if not auth_path.is_file():
        raise AdmissionError("owner authorization record missing")
    auth=load_json(auth_path)
    if auth.get("status")!="ACTIVE":
        raise AdmissionError("owner authorization record is not ACTIVE")

    provider=str(req.get("provider") or "")
    model=str(req.get("model") or "")
    thinking=str(req.get("thinking") or "")
    if provider!=str(paid.get("provider") or ""):
        raise AdmissionError("provider differs from active paid policy")
    if thinking!=str(paid.get("thinking") or ""):
        raise AdmissionError("thinking mode differs from active paid policy")
    provider_cfg=load_json(ROOT/"provider.json")
    if model!=str(provider_cfg.get("model") or ""):
        raise AdmissionError("model differs from active provider config")

    max_raw=int(req.get("max_raw_tokens") or 0)
    max_calls=int(req.get("max_case_calls") or 0)
    max_completion=int(req.get("max_completion_tokens") or 0)
    if not (0 < max_raw <= int(paid.get("max_total_tokens") or 0)):
        raise AdmissionError("invalid max_raw_tokens")
    if not (0 < max_calls <= 5000):
        raise AdmissionError("invalid max_case_calls")
    if not (0 < max_completion <= 8192):
        raise AdmissionError("invalid max_completion_tokens")

    case_ids=[str(x) for x in (req.get("case_ids") or [])]
    if not case_ids or len(case_ids)!=len(set(case_ids)) or len(case_ids)>max_calls:
        raise AdmissionError("case_ids must be unique, nonempty and <= max_case_calls")
    if any(not CASE_RE.fullmatch(x) for x in case_ids):
        raise AdmissionError("invalid case_id")
    prefixes=req.get("case_prefix_sha256") or {}
    if not isinstance(prefixes,dict) or not prefixes:
        raise AdmissionError("case_prefix_sha256 is required")
    clean_prefixes={}
    for k,v in prefixes.items():
        k=str(k);v=str(v)
        if not k or not HEX64.fullmatch(v):
            raise AdmissionError("invalid case prefix hash binding")
        clean_prefixes[k]=v
    for cid in case_ids:
        matches=[p for p in clean_prefixes if cid.startswith(p)]
        if len(matches)!=1:
            raise AdmissionError("every case_id must match exactly one invariant prompt prefix")

    response_format=req.get("response_format")
    if response_format!={"type":"json_object"}:
        raise AdmissionError("only json_object response format is auto-registerable")

    pricing=paid.get("pricing_cny_per_million") or {}
    try:
        peak_in=float(pricing["cache_miss"]["peak"])
        peak_out=float(pricing["output"]["peak"])
    except Exception as exc:
        raise AdmissionError("peak pricing missing") from exc
    max_output=max_calls*max_completion
    computed=(max_raw*peak_in + max_output*peak_out)/1_000_000.0
    claimed=float(req.get("conservative_peak_hard_bound_cny") or 0)
    if claimed and computed > claimed + 1e-9:
        raise AdmissionError("claimed peak hard bound understates policy-computed bound")
    if threshold<=0 or not computed < threshold:
        raise AdmissionError(f"computed peak hard bound {computed:.6f} CNY is not strictly below {threshold:.6f}")
    remaining=float(paid.get("estimated_remaining_project_budget_cny") or 0)
    if remaining < computed:
        raise AdmissionError("remaining project budget does not cover scope hard bound")

    existing=paid.get("prefrozen_mainline_execution_manifests") or []
    if any(str(x.get("scope") or "")==scope for x in existing if isinstance(x,dict)):
        raise AdmissionError("scope is already registered")
    no_prior_paid_attempt(scope)

    backlog=load_json(BACKLOG)
    auto_id="AUTO_PAID_"+re.sub(r"[^A-Za-z0-9]","",lease_id)[-16:].upper()
    if any(isinstance(x,dict) and x.get("id")==auto_id for x in (backlog.get("candidates") or [])):
        raise AdmissionError("auto registration backlog id already exists")

    manifest={
      "schema":"xiaoyu-prefrozen-mainline-paid-execution-manifest-v1",
      "created_at":req.get("created_at"),
      "status":"FROZEN_BEFORE_EXECUTION",
      "paid_execution_authorized":True,
      "formal":False,
      "backlog_id":auto_id,
      "scope":scope,
      "phase":"benchmark",
      "provider":provider,
      "model":model,
      "thinking":thinking,
      "reasoning_effort":str(req.get("reasoning_effort") or paid.get("reasoning_effort") or "none"),
      "temperature":float(req.get("temperature",paid.get("temperature",0))),
      "top_p":float(req.get("top_p",paid.get("top_p",1))),
      "max_raw_tokens":max_raw,
      "max_case_calls":max_calls,
      "max_completion_tokens":max_completion,
      "response_format":response_format,
      "case_ids":case_ids,
      "case_prefix_sha256":clean_prefixes,
      "authorization":{"path":project_rel(auth_path),"sha256":sha_path(auth_path)},
      "freeze":{"path":project_rel(freeze_path),"sha256":expected_freeze},
      "auto_registration":{
        "schema":"xiaoyu-auto-paid-scope-registration-v2",
        "source_request":project_rel(req_path),
        "source_request_sha256":sha_path(req_path),
        "lease_id":lease_id,
        "agent_id":lease["agent_id"],
        "worker_instance_id":str(lease.get("worker_instance_id") or ""),
        "bound_backlog_id":str(lease.get("backlog_id") or ""),
        "computed_peak_hard_bound_cny":computed,
        "owner_threshold_cny":threshold,
        "execution_authority":"live source lease/backlog is revalidated by research_api at reservation time"
      },
      "boundaries":boundaries
    }
    slug=re.sub(r"[^a-zA-Z0-9_.-]+","_",scope.replace("proxy:xiaoyu:",""))
    manifest_path=REG_DIR/(slug+"_"+lease_id+".json")
    entry={"scope":scope,"path":project_rel(manifest_path),"sha256":None}
    backlog_row={
      "id":auto_id,
      "plan":"AUTO_PAID_SCOPE_REGISTRATION",
      "task_pool":"administrative",
      "priority":999,
      "status":"administrative_registered",
      "single_pass":True,
      "family":str(lease["family"]),
      "capability":str(lease["capability"]),
      "lineage":str(lease["lineage"] or lease["family"]),
      "lane":str(lease["lane"]),
      "hypothesis":"Administrative paid-scope registration only; scientific hypothesis remains owned by lease "+lease_id,
      "paid_execution_authorized":True,
      "paid_authorization_record":project_rel(auth_path),
      "paid_evidence_requirement":{
        "budget_scope":scope,"phase":"benchmark",
        "max_raw_tokens":max_raw,"max_calls":max_calls
      },
      "auto_registration_lease_id":lease_id
    }
    return policy,backlog,manifest,manifest_path,entry,backlog_row,computed

def apply(req_path: Path, do_apply: bool):
    policy,backlog,manifest,manifest_path,entry,row,cost=validate_request(req_path)
    preview={
      "scope":manifest["scope"],"lease_id":manifest["auto_registration"]["lease_id"],
      "source_backlog_id":manifest["auto_registration"].get("bound_backlog_id") or "",
      "computed_peak_hard_bound_cny":cost,"manifest_path":project_rel(manifest_path),
      "registration_id":manifest["backlog_id"],"apply":do_apply
    }
    if not do_apply:
        return preview

    # Re-read mutable authority after validation. Do not write RESEARCH_BACKLOG:
    # stale validation snapshots must never be able to undo a Lead hold.
    revalidate_source_binding(manifest)
    REG_DIR.mkdir(exist_ok=True)
    body=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    if manifest_path.exists():
        raise AdmissionError("target manifest already exists")
    with manifest_path.open("xb") as f:
        f.write(body); f.flush(); os.fsync(f.fileno())
    entry["sha256"]=sha_bytes(body)

    try:
        # Revalidate again immediately before publishing the scope, then mutate
        # only policy-owned registration state. The runtime performs the final
        # live check at each reservation, which is the revocation linearization
        # point for future calls.
        revalidate_source_binding(manifest)
        policy=load_json(POLICY)
        paid=get_paid_cfg(policy)
        auth_cfg=paid.get("auto_scope_authorization") or {}
        if auth_cfg.get("enabled") is not True:
            raise AdmissionError("owner low-cost auto authorization is not active")
        existing=paid.get("prefrozen_mainline_execution_manifests") or []
        if any(str(x.get("scope") or "")==manifest["scope"] for x in existing if isinstance(x,dict)):
            raise AdmissionError("scope is already registered")
        paid.setdefault("prefrozen_mainline_execution_manifests",[]).append(entry)
        guard=paid.setdefault("runtime_guard",{})
        overrides=guard.setdefault("scope_overrides",{})
        if manifest["scope"] in overrides:
            raise AdmissionError("scope override already exists")
        max_output=manifest["max_case_calls"]*manifest["max_completion_tokens"]
        overrides[manifest["scope"]]={
          "rolling_raw_token_cap":manifest["max_raw_tokens"],
          "rolling_cache_miss_cap":manifest["max_raw_tokens"],
          "rolling_output_token_cap":max_output,
          "rolling_call_cap":manifest["max_case_calls"],
          "epoch_raw_token_cap":manifest["max_raw_tokens"],
          "epoch_cache_miss_cap":manifest["max_raw_tokens"],
          "epoch_output_token_cap":max_output,
          "epoch_call_cap":manifest["max_case_calls"]
        }
        atomic_json(POLICY,policy)
    except Exception:
        # Unpublished or failed publication leaves no durable authorization.
        try: manifest_path.unlink()
        except FileNotFoundError: pass
        raise

    receipt=manifest_path.with_suffix(".registration.json")
    atomic_json(receipt,{
      "schema":"xiaoyu-auto-paid-scope-registration-receipt-v2",
      "status":"REGISTERED",
      "scope":manifest["scope"],
      "manifest_path":project_rel(manifest_path),
      "manifest_sha256":entry["sha256"],
      "registration_id":manifest["backlog_id"],
      "source_lease_id":manifest["auto_registration"]["lease_id"],
      "source_backlog_id":manifest["auto_registration"].get("bound_backlog_id") or "",
      "computed_peak_hard_bound_cny":cost,
      "research_backlog_modified":False,
      "research_api_modified":False,
      "provider_calls":0
    })
    preview.update({"registered":True,"manifest_sha256":entry["sha256"],"receipt":project_rel(receipt)})
    return preview

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--request",required=True)
    ap.add_argument("--apply",action="store_true")
    a=ap.parse_args()
    try:
        q=resolve_rel(a.request)
        result=apply(q,a.apply)
        print(json.dumps({"ok":True,"result":result},ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False,indent=2))
        raise SystemExit(2)

if __name__=="__main__":
    main()
