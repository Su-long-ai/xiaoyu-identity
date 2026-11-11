# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "governance"
FAST = G / "fastlane"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
import model_adapter
from research_components.retrieval.api import (
    CONTEXT_CAP,
    authorized_documents,
    component_fingerprint,
    enrich_bridge_hits,
    load_component,
    prepare_component,
    rank_component,
)

DEFAULT_FIXTURE = Path(__file__).with_name("local_dev_v3_240.json")
LEGACY_REGRESSION_FIXTURE = Path(__file__).with_name("local_e2e_cases_v2_120.json")
SYSTEM_PROMPT = """You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. Never use external facts or guesses. If the memories do not support a reliable answer, return exactly {"answer":"I don't know."}. For current/now questions, prefer the latest explicit statement using the timestamps. For multi-hop questions, combine multiple supplied memories when the relation is directly supported. Return exactly one JSON object with one string field named answer and no other text."""

def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())

def stable(obj) -> str:
    return sha_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode())

def normalize(text: str) -> str:
    # Unicode-aware normalization: preserve CJK and other alphanumeric scripts.
    raw=str(text).casefold()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in raw).split())

def answer_correct(answer: str, aliases: list[str]) -> bool:
    a = normalize(answer)
    if any(normalize(x) in ("i don t know","unknown") for x in aliases):
        return ("i don t know" in a) or a == "unknown" or a.startswith("unknown ")
    return any(normalize(x) and normalize(x) in a for x in aliases)

def parse_answer(raw: str) -> str:
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
            return obj["answer"].strip()
    except Exception:
        pass
    return str(raw).strip()

def messages_for(question: str, docs: list[dict]) -> list[dict]:
    parts = []
    for i,d in enumerate(docs,1):
        ts = d.get("timestamp") or "unknown"
        parts.append(f"[{i}] authority={d.get('authority','user_state')} timestamp={ts}\n{d.get('text','')}")
    user = "AUTHORIZED MEMORIES:\n" + "\n\n".join(parts) + "\n\nQUESTION:\n" + str(question)
    return [{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":user}]

def deepseek_config():
    base = model_adapter.PROVIDERS["deepseek"]
    return {
        "provider":"deepseek",
        "url":base["url"],
        "model":"deepseek-flash",
        "key_env":base["key_env"],
        "thinking":"disabled",
        "reasoning_effort":"none",
        "temperature":0,
        "top_p":1,
        "response_format":{"type":"json_object"},
    }

def call_answerer(question: str, docs: list[dict]):
    raw, usage = model_adapter.chat(
        deepseek_config(),
        messages_for(question, docs),
        max_tokens=96,
        timeout=90,
    )
    return parse_answer(raw), usage

def offline_answer(case: dict, docs: list[dict]) -> str:
    required = set(case.get("required_ids") or [])
    got = {str(d.get("source_key") or "") for d in docs}
    if required and required.issubset(got):
        return str(case["expected"][0])
    if not required:
        return "I don't know."
    return "I don't know."

def build_shared_store(fixture: dict):
    home = Path(tempfile.mkdtemp(prefix="xy-fastret-shared-"))
    store = IdentityStore(home)
    try:
        rows = list(fixture.get("distractors") or [])
        for case in fixture.get("cases") or []:
            rows.extend(case.get("memories") or [])
        ids = [str(x["id"]) for x in rows]
        if len(ids) != len(set(ids)):
            raise RuntimeError("fixture source IDs must be globally unique")
        for idx,m in enumerate(rows):
            key = str(m["id"])
            ts = str(m.get("time") or f"2025-{(idx%12)+1:02d}-{(idx%27)+1:02d}T00:00:00Z")
            speaker = str(m.get("speaker") or "User")
            text = str(m["text"])
            event = store.record(
                "conversation.user",
                "user",
                text,
                {"chat_time":ts,"speaker":speaker,"session":"local-e2e-v2","source_key":key},
            )
            store.add_memory(text, category="shared", priority=3, source_event=event)
        bridge = ProductMemoryBridge(home, store)
        bridge.sync()
        return home, store, bridge
    except Exception:
        store.close()
        shutil.rmtree(home, ignore_errors=True)
        raise

def build_isolated_case(case: dict, distractors: list[dict]):
    fixture={"distractors":distractors,"cases":[case]}
    return build_shared_store(fixture)

def evidence_full(case: dict, docs: list[dict]):
    required = set(case.get("required_ids") or [])
    if not required:
        return None
    got = {str(d.get("source_key") or "") for d in docs}
    return required.issubset(got)

def summarize(rows: list[dict], arm: str) -> dict:
    n = len(rows)
    correct = sum(bool(r[arm]["correct"]) for r in rows)
    evidence_rows = [r for r in rows if r[arm]["full_evidence"] is not None]
    full = sum(bool(r[arm]["full_evidence"]) for r in evidence_rows)
    by = {}
    for r in rows:
        f = str(r["family"])
        z = by.setdefault(f, {"n":0,"correct":0,"evidence_n":0,"full_evidence":0})
        z["n"] += 1
        z["correct"] += int(bool(r[arm]["correct"]))
        if r[arm]["full_evidence"] is not None:
            z["evidence_n"] += 1
            z["full_evidence"] += int(bool(r[arm]["full_evidence"]))
    for z in by.values():
        z["accuracy"] = z["correct"]/z["n"] if z["n"] else None
        z["full_evidence_rate"] = z["full_evidence"]/z["evidence_n"] if z["evidence_n"] else None
    return {
        "n":n,
        "correct":correct,
        "accuracy":correct/n if n else None,
        "evidence_n":len(evidence_rows),
        "full_evidence":full,
        "full_evidence_rate":full/len(evidence_rows) if evidence_rows else None,
        "by_family":by,
    }

def load_fastlane_baseline():
    p = FAST/"BASELINE.json"
    if not p.is_file():
        return None, None, {"baseline_id":"current_product"}
    record=json.loads(p.read_text(encoding="utf-8"))
    rel=(record.get("method") or {}).get("component")
    if not rel:
        return None, None, record
    component_path=(ROOT/rel).resolve()
    component,module_path=load_component(str(component_path))
    return component,module_path,record

def install_query_cache(component, cases):
    cid=str(getattr(component,"component_id",""))
    if cid not in {"hybrid_bge_bm25_rrf_v1","multifacet_bge_rrf_v1"} or not hasattr(component,"model"):
        return
    questions=[str(case["question"]) for case in cases]
    texts=list(questions)
    if cid=="multifacet_bge_rrf_v1":
        facet_fn=getattr(component.rank,"__globals__",{}).get("facet_queries")
        if callable(facet_fn):
            texts=[facet for q in questions for facet in facet_fn(q)]
    unique=list(dict.fromkeys(texts))
    emb=component.model.encode(unique,batch_size=64,max_length=128,query=True)
    cache={q:emb[i] for i,q in enumerate(unique)}
    original=component.model.encode
    def cached_encode(values,batch_size=64,max_length=256,query=False):
        vals=[str(x) for x in values]
        if query and vals and all(v in cache for v in vals):
            return np.stack([cache[v] for v in vals],axis=0)
        return original(values,batch_size=batch_size,max_length=max_length,query=query)
    component.model.encode=cached_encode

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--component", required=True, help="builtin alias or candidate .py path")
    ap.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    ap.add_argument("--provider", choices=["none","deepseek"], default="none", help="Local suites are offline-only; deepseek is rejected by policy.")
    ap.add_argument("--promote-local-candidate", action="store_true")
    ap.add_argument("--promote-e0", action="store_true", help="DEPRECATED alias: creates a Local Candidate, never an E0.")
    ap.add_argument("--agent-id", default="fastlane-research")
    ap.add_argument("--run-label", default="")
    ap.add_argument("--no-baseline-cache", action="store_true")
    ap.add_argument("--concurrency", type=int, default=int(os.environ.get("XIAOYU_FASTLANE_LOCAL_CONCURRENCY","8")))
    args = ap.parse_args()
    if args.provider != "none":
        raise SystemExit("LOCAL_PROVIDER_FORBIDDEN: local evaluation suites are offline-only; use DeepSeek only in External100/200.")

    fixture_path=Path(args.fixture).resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if int(fixture.get("context_cap") or 0) != CONTEXT_CAP:
        raise SystemExit("fixture context cap drift")
    fixture_sha=sha_file(fixture_path)
    dev_manifest_path=FAST/"LOCAL_DEV_FIXTURES.json"
    primary_dev_sha=None
    if dev_manifest_path.is_file():
        try:
            primary_dev_sha=str((json.loads(dev_manifest_path.read_text(encoding="utf-8")).get("default_dev") or {}).get("sha256") or "")
        except Exception:
            primary_dev_sha=None
    primary_dev_fixture=bool(primary_dev_sha and fixture_sha==primary_dev_sha)
    cases=list(fixture["cases"])
    component, component_path = load_component(args.component)
    fp = component_fingerprint(component_path, component.component_id)
    baseline_component, baseline_component_path, baseline_record = load_fastlane_baseline()
    baseline_fp = (
        component_fingerprint(baseline_component_path, baseline_component.component_id)
        if baseline_component is not None else
        {"component_id":"current_product_recall","path":None,"sha256":None}
    )
    install_query_cache(component,cases)
    if baseline_component is not None:
        if str(getattr(baseline_component,"component_id",""))==str(getattr(component,"component_id","")) and hasattr(component,"model"):
            baseline_component.model=component.model
        else:
            install_query_cache(baseline_component,cases)

    product_fp = {
        "product_memory_bridge_sha256": sha_file(ROOT/"product_memory_bridge.py"),
        "product_memory_bridge_base_sha256": sha_file(ROOT/"product_memory_bridge_base.py"),
        "identity_core_sha256": sha_file(ROOT/"identity_core.py"),
    }
    baseline_cache_key = stable({
        "fixture":fixture_sha,
        "product":product_fp,
        "prompt":sha_bytes(SYSTEM_PROMPT.encode()),
        "provider":args.provider,
        "baseline_record":sha_file(FAST/"BASELINE.json") if (FAST/"BASELINE.json").is_file() else "current-product",
        "baseline_component":baseline_fp,
    })
    baseline_cache_path = FAST/"cache"/f"local_baseline_{baseline_cache_key[:20]}.json"
    retrieval_cache_path = FAST/"cache"/f"local_baseline_retrieval_{baseline_cache_key[:20]}.json"
    cached = {}
    cached_retrieval = {}
    if retrieval_cache_path.is_file() and not args.no_baseline_cache:
        try:
            robj=json.loads(retrieval_cache_path.read_text(encoding="utf-8"))
            if robj.get("cache_key")==baseline_cache_key:
                cached_retrieval={str(x["case_id"]):list(x["selected_source_keys"]) for x in robj.get("rows",[])}
        except Exception:
            cached_retrieval={}
    if baseline_cache_path.is_file() and not args.no_baseline_cache:
        try:
            obj = json.loads(baseline_cache_path.read_text(encoding="utf-8"))
            if obj.get("cache_key") == baseline_cache_key:
                cached = {str(x["case_id"]):x for x in obj.get("answers",[])}
        except Exception:
            cached = {}

    started=time.perf_counter()
    retrieval_rows=[]
    homes=[]
    if fixture.get("shared_store"):
        home,store,bridge=build_shared_store(fixture)
        homes.append((home,store,bridge))
        docs=authorized_documents(bridge)
        by_source={str(d.get("source_key") or ""):d for d in docs}
        candidate_state=prepare_component(component,docs)
        need_baseline_retrieval=not all(str(case["id"]) in cached_retrieval for case in cases)
        if need_baseline_retrieval and baseline_component is not None:
            same_bge_family={
                str(getattr(component,"component_id","")),
                str(getattr(baseline_component,"component_id","")),
            }.issubset({"hybrid_bge_bm25_rrf_v1","multifacet_bge_rrf_v1"})
            baseline_state=(
                {"documents":[dict(d) for d in docs],"embeddings":candidate_state["embeddings"]}
                if same_bge_family and isinstance(candidate_state,dict) and "embeddings" in candidate_state
                else prepare_component(baseline_component,docs)
            )
        else:
            baseline_state=None
        baseline_retrieval_rows=[]
        for case in cases:
            cid=str(case["id"])
            candidate_docs=rank_component(component,candidate_state,docs,case["question"],CONTEXT_CAP,metadata={})
            if cid in cached_retrieval:
                baseline_docs=[by_source[x] for x in cached_retrieval[cid] if x in by_source]
            elif baseline_component is not None:
                baseline_docs=rank_component(baseline_component,baseline_state,docs,case["question"],CONTEXT_CAP,metadata={})
            else:
                baseline_docs=enrich_bridge_hits(bridge,bridge.recall(case["question"],limit=CONTEXT_CAP))
            baseline_retrieval_rows.append({"case_id":cid,"selected_source_keys":[str(d.get("source_key") or "") for d in baseline_docs]})
            retrieval_rows.append((case,baseline_docs,candidate_docs))
        if need_baseline_retrieval:
            retrieval_cache_path.write_text(json.dumps({
                "schema":"xiaoyu-fast-retrieval-baseline-retrieval-cache-v1",
                "cache_key":baseline_cache_key,
                "baseline_id":baseline_record.get("baseline_id") if isinstance(baseline_record,dict) else "current_product",
                "rows":baseline_retrieval_rows
            },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    else:
        for case in cases:
            home,store,bridge=build_isolated_case(case,fixture.get("distractors") or [])
            homes.append((home,store,bridge))
            docs=authorized_documents(bridge)
            candidate_state=prepare_component(component,docs)
            candidate_docs=rank_component(component,candidate_state,docs,case["question"],CONTEXT_CAP,metadata={})
            if baseline_component is not None:
                bs=prepare_component(baseline_component,docs)
                baseline_docs=rank_component(baseline_component,bs,docs,case["question"],CONTEXT_CAP,metadata={})
            else:
                baseline_docs=enrich_bridge_hits(bridge,bridge.recall(case["question"],limit=CONTEXT_CAP))
            retrieval_rows.append((case,baseline_docs,candidate_docs))

    try:
        for _case,b,c in retrieval_rows:
            if len(b)>CONTEXT_CAP or len(c)>CONTEXT_CAP:
                raise RuntimeError("context cap violation")

        usage={"baseline_calls":0,"candidate_calls":0,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
        baseline_answers={}
        candidate_answers={}
        baseline_cache_rows=[]
        if args.provider=="none":
            for case,bdocs,cdocs in retrieval_rows:
                baseline_answers[case["id"]]=offline_answer(case,bdocs)
                candidate_answers[case["id"]]=offline_answer(case,cdocs)
        else:
            workers=max(1,min(12,int(args.concurrency)))
            missing=[(case,bdocs) for case,bdocs,_ in retrieval_rows if str(case["id"]) not in cached]
            for cid,obj in cached.items():
                baseline_answers[cid]=str(obj["answer"])

            def answer_job(item):
                case,docs=item
                ans,u=call_answerer(case["question"],docs)
                return str(case["id"]),ans,u

            if missing:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    results=list(ex.map(answer_job,missing))
                for cid,ans,u in results:
                    baseline_answers[cid]=ans
                    usage["baseline_calls"]+=1
                    for k in ("prompt_tokens","completion_tokens","total_tokens"):
                        usage[k]+=int(u.get(k) or 0)

            same_component=(
                str(fp.get("component_id"))==str(baseline_fp.get("component_id"))
                and str(fp.get("sha256"))==str(baseline_fp.get("sha256"))
            )
            same_retrieval=same_component and all(
                [str(d.get("source_key") or "") for d in bdocs]
                == [str(d.get("source_key") or "") for d in cdocs]
                for _case,bdocs,cdocs in retrieval_rows
            )
            if same_retrieval:
                candidate_answers=dict(baseline_answers)
            else:
                cand_jobs=[(case,cdocs) for case,_,cdocs in retrieval_rows]
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    results=list(ex.map(answer_job,cand_jobs))
                for cid,ans,u in results:
                    candidate_answers[cid]=ans
                    usage["candidate_calls"]+=1
                    for k in ("prompt_tokens","completion_tokens","total_tokens"):
                        usage[k]+=int(u.get(k) or 0)

        rows=[]
        for case,bdocs,cdocs in retrieval_rows:
            cid=str(case["id"])
            ba=baseline_answers[cid]; ca=candidate_answers[cid]
            baseline_cache_rows.append({"case_id":cid,"answer":ba})
            rows.append({
                "case_id":cid,"family":case["family"],"question":case["question"],"expected":case["expected"],
                "baseline":{"answer":ba,"correct":answer_correct(ba,case["expected"]),
                            "full_evidence":evidence_full(case,bdocs),
                            "selected_source_keys":[d.get("source_key") for d in bdocs],"count":len(bdocs)},
                "candidate":{"answer":ca,"correct":answer_correct(ca,case["expected"]),
                             "full_evidence":evidence_full(case,cdocs),
                             "selected_source_keys":[d.get("source_key") for d in cdocs],"count":len(cdocs)}
            })

        baseline=summarize(rows,"baseline"); candidate=summarize(rows,"candidate")
        delta={"accuracy":candidate["accuracy"]-baseline["accuracy"],
               "full_evidence_rate":candidate["full_evidence_rate"]-baseline["full_evidence_rate"],
               "correct_cases":candidate["correct"]-baseline["correct"]}
        eligible=bool(delta["correct_cases"]>=1 and delta["accuracy"]>0 and delta["full_evidence_rate"]>=0)
        run_id=args.run_label.strip() or time.strftime("%Y%m%d_%H%M%S")+"_"+re.sub(r"[^a-zA-Z0-9_.-]+","_",component.component_id)[:60]
        out={
          "schema":"xiaoyu-fast-retrieval-local-e2e-v3","status":"LOCAL_E2E_COMPLETE","run_id":run_id,
          "agent_id":args.agent_id,"component":fp,"baseline_component":baseline_fp,
          "baseline_id":baseline_record.get("baseline_id") if isinstance(baseline_record,dict) else "current_product",
          "fixture":{"path":str(fixture_path),"sha256":fixture_sha,"cases":len(cases),"shared_store":bool(fixture.get("shared_store"))},
          "product":product_fp,"provider":args.provider,"local_provider_policy":"NONE_ONLY","context_cap":CONTEXT_CAP,
          "baseline":baseline,"candidate":candidate,"delta":delta,
          "dev_advantage_eligible":eligible,
          "local_candidate_eligible":bool(eligible and primary_dev_fixture),
          "local_candidate_fixture_authorized":primary_dev_fixture,
          "e0_eligible":False,
          "e0_generation_stage":"EXTERNAL_DEV_ONLY",
          "usage":usage,
          "elapsed_seconds":time.perf_counter()-started,"rows":rows
        }
        FAST.joinpath("runs").mkdir(parents=True,exist_ok=True)
        out_path=FAST/"runs"/f"{run_id}.json"
        out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        result_sha=sha_file(out_path)

        if args.provider!="none" and (not baseline_cache_path.is_file() or args.no_baseline_cache):
            baseline_cache_path.write_text(json.dumps({
              "schema":"xiaoyu-fast-retrieval-baseline-cache-v2","cache_key":baseline_cache_key,
              "baseline_id":out["baseline_id"],"answers":baseline_cache_rows
            },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

        local_candidate_path=None
        promote_local=bool(args.promote_local_candidate or args.promote_e0)
        if promote_local and out["local_candidate_eligible"]:
            lc_id="LC-FASTRET-"+stable({"component":fp,"result":result_sha,"agent":args.agent_id,"baseline":out["baseline_id"]})[:12]
            lc={
              "schema":"xiaoyu-fast-retrieval-local-candidate-v1",
              "status":"LOCAL_CANDIDATE_READY_FOR_EXTERNAL_DEV",
              "local_candidate_id":lc_id,
              "created_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "agent_id":args.agent_id,
              "component":fp,
              "baseline_component":baseline_fp,
              "baseline_id":out["baseline_id"],
              "fixture":out["fixture"],
              "local_e2e_result":str(out_path.relative_to(ROOT)).as_posix(),
              "local_e2e_result_sha256":result_sha,
              "baseline":baseline,
              "candidate":candidate,
              "delta":delta,
              "claim":"Local-only research candidate. It is NOT E0 and carries no frozen-test or product-promotion authority.",
              "required_external_dev":["rhelm","convomem"],
              "e0_generation_rule":"Only governance/evaluation/external_suite/qualify_e0.py may mint E0 after External Dev qualification.",
              "local_provider_policy":"NONE_ONLY",
              "deprecated_promote_e0_alias_used":bool(args.promote_e0)
            }
            local_dir=FAST/"local_candidates"
            local_dir.mkdir(parents=True,exist_ok=True)
            local_candidate_path=local_dir/f"{lc_id}.json"
            local_candidate_path.write_text(json.dumps(lc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

        print(json.dumps({
          "status":out["status"],"run":str(out_path),"fixture_cases":len(cases),"shared_store":bool(fixture.get("shared_store")),
          "baseline_id":out["baseline_id"],"component":fp,"baseline":baseline,"candidate":candidate,
          "delta":delta,
          "dev_advantage_eligible":eligible,
          "local_candidate_eligible":out["local_candidate_eligible"],
          "local_candidate_fixture_authorized":primary_dev_fixture,
          "local_candidate_path":str(local_candidate_path) if local_candidate_path else None,
          "e0_eligible":False,
          "e0_generation_stage":"EXTERNAL_DEV_ONLY",
          "deprecated_promote_e0_alias_used":bool(args.promote_e0),
          "usage":usage,"elapsed_seconds":out["elapsed_seconds"]
        },ensure_ascii=False,indent=2))
    finally:
        for home,store,bridge in homes:
            try: bridge.close()
            except Exception: pass
            try: store.close()
            except Exception: pass
            shutil.rmtree(home,ignore_errors=True)

if __name__=="__main__":
    main()
