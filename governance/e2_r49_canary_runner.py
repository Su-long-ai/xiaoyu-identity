#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execute the frozen R49 16-case HaluMem semantic-transition canary.

The original E2 execution manifest remains immutable. This runner consumes only
a separately frozen supplemental canary manifest registered in policy.

Crash semantics:
- provider response is durably written before semantic validation/state mutation;
- resume never repeats a paid call when a provider receipt already exists;
- R47 ingest is idempotent for identical source/projection replay;
- each stream must execute in frozen order.
"""
from __future__ import annotations
import argparse,hashlib,json,os,sys,time,urllib.request,urllib.error
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
MANIFEST=GOV/"E2_R49_CANARY_MANIFEST.json"
PAIR=GOV/"E2_HALUMEM_PAIR_SOURCE_CANDIDATE.json"
POLICY=GOV/"policy.json"
RUNTIME_AMENDMENT=GOV/"E2_EXECUTION_AMENDMENT_R49_CANARY_RUNTIME_V2.json"
RUNTIME=GOV/"e2_r49_canary_runtime"
RESP=RUNTIME/"responses"
RESULTS=RUNTIME/"results"
STATES=RUNTIME/"states"

sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(GOV))
import E2_R49_SEMANTIC_CONTRACT_FROZEN as contract
from E2_R47_OPEN_DOMAIN_MEMORY_STORE_FROZEN import OpenDomainMemoryStore
import model_adapter

class CanaryError(RuntimeError): pass

def sha_file(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def stable(x)->str:return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def write_json(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
    os.replace(tmp,path)
def load_json(path:Path):return json.loads(path.read_text(encoding="utf-8"))

def load_manifest():
    if not MANIFEST.is_file():raise CanaryError("canary manifest missing")
    policy=load_json(POLICY)
    rows=(policy.get("e2_transition") or {}).get("supplemental_execution_manifests") or []
    rel="governance/E2_R49_CANARY_MANIFEST.json"
    entry=next((x for x in rows if isinstance(x,dict) and x.get("path")==rel),None)
    if entry is None:raise CanaryError("canary manifest not registered in policy")
    actual=sha_file(MANIFEST)
    if actual!=entry.get("sha256"):raise CanaryError("canary manifest policy hash mismatch")
    m=load_json(MANIFEST)
    amend_rel="governance/E2_EXECUTION_AMENDMENT_R49_CANARY_RUNTIME_V2.json"
    amend_entry=next((x for x in (policy.get("e2_transition") or {}).get("execution_amendments",[])
                      if isinstance(x,dict) and x.get("path")==amend_rel),None)
    if amend_entry is None or not RUNTIME_AMENDMENT.is_file():
        raise CanaryError("R49 runtime-v2 amendment is not registered")
    if sha_file(RUNTIME_AMENDMENT)!=amend_entry.get("sha256"):
        raise CanaryError("R49 runtime-v2 amendment hash mismatch")
    amend=load_json(RUNTIME_AMENDMENT)
    if amend.get("schema")!="xiaoyu-e2-execution-amendment-v1" or amend.get("status")!="FROZEN_POST_ENTRY_AMENDMENT":
        raise CanaryError("bad R49 runtime-v2 amendment")
    if amend.get("supplemental_manifest_sha256")!=actual:
        raise CanaryError("R49 runtime-v2 manifest ancestry mismatch")
    if amend.get("previous_runner_sha256")!=m.get("runner_sha256"):
        raise CanaryError("R49 runtime-v2 prior runner ancestry mismatch")
    current_runner=sha_file(Path(__file__))
    if (amend.get("current_implementation_hashes") or {}).get("r49_canary_runner")!=current_runner:
        raise CanaryError("R49 runtime-v2 current runner hash mismatch")
    if m.get("schema")!="xiaoyu-e2-supplemental-execution-manifest-v1":raise CanaryError("bad canary schema")
    if m.get("status")!="FROZEN_BEFORE_EXECUTION" or m.get("paid_execution_authorized") is not True:
        raise CanaryError("canary is not authorized/frozen")
    if sha_file(GOV/"E2_R49_SEMANTIC_CONTRACT_FROZEN.py")!=m["accepted_contract"]["contract_sha256"]:
        raise CanaryError("frozen R49 contract hash drift")
    if sha_file(GOV/"E2_R47_OPEN_DOMAIN_MEMORY_STORE_FROZEN.py")!=m["accepted_contract"]["r47_store_sha256"]:
        raise CanaryError("frozen R47 store hash drift")
    if sha_file(PAIR)!=m["pair_source_artifact_sha256"]:raise CanaryError("pair artifact hash drift")
    return m

def case_map():
    pair=load_json(PAIR)
    return {x["case_id"]:x for x in pair["cases"]}

def stream_state_path(stream:str)->Path:
    safe=stream.replace(":","_").replace("/","_")
    return STATES/(safe+".sqlite")

def provider_receipt_path(cid:str)->Path:return RESP/(cid+".json")
def result_path(cid:str)->Path:return RESULTS/(cid+".json")

def prior_case_ids(m,stream,cid):
    rows=[x for x in m["case_rows"] if x["stream_key"]==stream]
    ids=[x["case_id"] for x in rows]
    i=ids.index(cid)
    return ids[:i]

def verify_order(m,row):
    for p in prior_case_ids(m,row["stream_key"],row["case_id"]):
        if not result_path(p).is_file():
            raise CanaryError(f"stream order blocked: prior case {p} incomplete")

def source_items(store,row,case):
    msgs=case["source_messages"]
    if len(msgs)!=2 or [x["role"] for x in msgs]!=["user","assistant"]:
        raise CanaryError("source pair must be user then assistant")
    caller=row["caller_binding"]
    if len(caller)!=2:raise CanaryError("caller binding cardinality")
    items=[]
    for pos,(msg,bind) in enumerate(zip(msgs,caller)):
        text=str(msg["text"]);role=str(msg["role"])
        if hashlib.sha256(text.encode()).hexdigest()!=bind["source_text_sha256"]:
            raise CanaryError("source text hash mismatch")
        if role!=bind["source_role"] or int(msg["message_index"])!=int(bind["message_seq"]):
            raise CanaryError("trusted source binding mismatch")
        pri=contract.prior_candidates_from_r47(
            store,text,role,int(bind["effective_at"]),limit=6)
        items.append({"source_text":text,"source_role":role,"prior_candidates":pri})
    return items

def messages_for(built):
    payload=json.dumps(built["model_payload"],ensure_ascii=False,separators=(",",":"))
    return [{"role":"system","content":contract.SYSTEM_PROMPT},{"role":"user","content":payload}]

def call_provider(m,row,messages):
    track=m["tracks"]["halumem_semantic_transition_canary"]
    cid=row["case_id"]
    body={
      "model":model_adapter.load_provider(ROOT)["model"],
      "messages":messages,
      "max_tokens":int(track["max_completion_tokens"]),
      "stream":False,
      "thinking":{"type":"disabled"},
      "reasoning_effort":"none",
      "temperature":0.0,
      "top_p":1.0,
      "response_format":{"type":"json_object"}
    }
    raw=json.dumps(body,ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(
      "http://127.0.0.1:18081/v1/chat/completions",data=raw,method="POST",
      headers={
        "Content-Type":"application/json",
        "Authorization":"Bearer local-budget-proxy:xiaoyu",
        "X-XiaoYu-Research-Run":"e2_halumem_semantic_transition_pilot_v1",
        "X-XiaoYu-Case-ID":cid,
      })
    try:
        with urllib.request.urlopen(req,timeout=120) as r:
            payload=json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg=e.read().decode("utf-8","replace")
        raise CanaryError(f"provider HTTP {e.code}: {msg[:1200]}") from e
    content=payload["choices"][0]["message"]["content"]
    receipt={
      "schema":"xiaoyu-e2-r49-provider-receipt-v1",
      "case_id":cid,"stream_key":row["stream_key"],
      "call_id":payload.get("id"),"model":payload.get("model"),
      "usage":payload.get("usage"),"response_text":content,
      "request_messages_sha256":stable(messages),
      "manifest_sha256":sha_file(MANIFEST),
      "recorded_at_epoch":time.time(),
    }
    write_json(provider_receipt_path(cid),receipt)
    return receipt

def load_or_call(m,row,messages):
    p=provider_receipt_path(row["case_id"])
    if p.is_file():
        rec=load_json(p)
        if rec.get("manifest_sha256")!=sha_file(MANIFEST):
            raise CanaryError("existing provider receipt manifest mismatch")
        if rec.get("request_messages_sha256")!=stable(messages):
            raise CanaryError("existing provider receipt request mismatch")
        return rec,True
    return call_provider(m,row,messages),False

def apply_case(m,row,case,store,receipt,built):
    before=store.current_view()
    try:
        validated=contract.validate_response(
            receipt["response_text"],built["model_payload"],built["caller_binding"])
    except Exception as exc:
        after=store.current_view()
        unchanged=(stable(before)==stable(after))
        if not unchanged:
            raise CanaryError("semantic validation rejection mutated state") from exc
        result={
          "schema":"xiaoyu-e2-r49-canary-result-v1",
          "case_id":row["case_id"],"stream_key":row["stream_key"],
          "call_id":receipt["call_id"],"usage":receipt["usage"],
          "semantic_validation":"REJECTED",
          "validation_error":type(exc).__name__+":"+str(exc),
          "validated_outputs":[],
          "ingest":[],
          "state_unchanged":True,
          "current_view":after,
          "manifest_sha256":sha_file(MANIFEST),
          "provider_receipt_sha256":sha_file(provider_receipt_path(row["case_id"])),
        }
        write_json(result_path(row["case_id"]),result)
        return result
    outputs=validated["outputs"]
    ingest=[]
    for pos,(msg,bind,out) in enumerate(zip(case["source_messages"],row["caller_binding"],outputs)):
        candidates=[{
          "claim_text":p["claim_text"],"evidence_quote":p["evidence_quote"],
          "relation":p["relation"],"targets":p["target_ids"]
        } for p in out["proposals"]]
        rr=store.ingest(
          bind["conversation_id"],bind["message_id"],bind["message_seq"],
          bind["source_role"],msg["text"],bind["effective_at"],candidates)
        ingest.append(rr)
    result={
      "schema":"xiaoyu-e2-r49-canary-result-v1",
      "case_id":row["case_id"],"stream_key":row["stream_key"],
      "call_id":receipt["call_id"],"usage":receipt["usage"],
      "semantic_validation":"ACCEPTED",
      "validation_error":None,
      "semantic_sha256":validated["semantic_sha256"],
      "validated_outputs":outputs,"ingest":ingest,
      "state_unchanged":False,
      "current_view":store.current_view(),
      "manifest_sha256":sha_file(MANIFEST),
      "provider_receipt_sha256":sha_file(provider_receipt_path(row["case_id"])),
    }
    write_json(result_path(row["case_id"]),result)
    return result

def _result_summary(cid,rec,result,reused_provider_receipt=True,result_reused=False):
    return {"case_id":cid,"reused_provider_receipt":reused_provider_receipt,
            "result_reused":result_reused,
            "call_id":rec["call_id"],"usage":rec["usage"],
            "semantic_validation":result.get("semantic_validation","ACCEPTED"),
            "validation_error":result.get("validation_error"),
            "statuses":[x["status"] for x in result.get("validated_outputs",[])],
            "proposal_counts":[len(x["proposals"]) for x in result.get("validated_outputs",[])],
            "state_unchanged":result.get("state_unchanged"),
            "current_count":len((result.get("current_view") or {}).get("current") or []),
            "conflict_count":len((result.get("current_view") or {}).get("conflict") or [])}


def run_case(cid:str):
    m=load_manifest(); cmap=case_map()
    track=m["tracks"]["halumem_semantic_transition_canary"]
    if cid not in track["case_ids"]:raise CanaryError("case outside frozen canary")
    row=next(x for x in m["case_rows"] if x["case_id"]==cid)
    verify_order(m,row)
    rp=result_path(cid); pp=provider_receipt_path(cid)
    if rp.is_file():
        if not pp.is_file():raise CanaryError("existing result missing provider receipt")
        rec=load_json(pp);result=load_json(rp)
        if rec.get("manifest_sha256")!=sha_file(MANIFEST):
            raise CanaryError("existing result provider receipt manifest mismatch")
        if result.get("manifest_sha256")!=sha_file(MANIFEST):
            raise CanaryError("existing result manifest mismatch")
        if result.get("provider_receipt_sha256")!=sha_file(pp):
            raise CanaryError("existing result provider receipt hash mismatch")
        return _result_summary(cid,rec,result,True,True)
    case=cmap[cid]
    if stable([x["text"] for x in case["source_messages"]])!=row["source_texts_sha256"]:
        raise CanaryError("source pair semantic hash mismatch")
    STATES.mkdir(parents=True,exist_ok=True)
    store=OpenDomainMemoryStore(stream_state_path(row["stream_key"]))
    try:
        items=source_items(store,row,case)
        built=contract.build_model_payload(items,limit=6)
        messages=messages_for(built)
        rec,reused=load_or_call(m,row,messages)
        result=apply_case(m,row,case,store,rec,built)
        return _result_summary(cid,rec,result,reused,False)
    finally:store.close()

def preflight():
    m=load_manifest();track=m["tracks"]["halumem_semantic_transition_canary"]
    cmap=case_map()
    for row in m["case_rows"]:
        cid=row["case_id"]
        if cid not in track["case_ids"] or cid not in cmap:raise CanaryError("manifest membership mismatch")
        c=cmap[cid]
        if stable([x["text"] for x in c["source_messages"]])!=row["source_texts_sha256"]:
            raise CanaryError("source hash mismatch")
    done=sum(result_path(x).is_file() for x in track["case_ids"])
    receipts=sum(provider_receipt_path(x).is_file() for x in track["case_ids"])
    return {"healthy":True,"manifest_sha256":sha_file(MANIFEST),
            "case_count":len(track["case_ids"]),"results":done,"provider_receipts":receipts,
            "scope":track["scope"],"max_completion_tokens":track["max_completion_tokens"],
            "provider_calls":0}

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("preflight")
    p=sub.add_parser("run-case");p.add_argument("--case-id",required=True)
    sub.add_parser("run-all")
    args=ap.parse_args()
    if args.cmd=="preflight":
        print(json.dumps(preflight(),ensure_ascii=False,indent=2));return
    if args.cmd=="run-case":
        print(json.dumps(run_case(args.case_id),ensure_ascii=False,indent=2));return
    m=load_manifest();rows=[]
    for cid in m["tracks"]["halumem_semantic_transition_canary"]["case_ids"]:
        rows.append(run_case(cid))
        print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    print(json.dumps({"completed":len(rows),"rows":rows},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
