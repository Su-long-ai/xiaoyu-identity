# -*- coding: utf-8 -*-
"""Cached/resumable post-seal hybrid-BGE/RRF diagnostic over frozen v3 gap plans.

Generation and retrieval stay gold-free until all 16 retrieval rows are sealed.
Persona embeddings are persisted by exact document fingerprint so interruption
does not waste the expensive local ONNX encoding pass.
"""
from __future__ import annotations

from pathlib import Path
import collections, hashlib, json, os, re, sys, time
import numpy as np

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_GAP_ANALYZER_V2_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
RROOT=ROOT/"external/benchmarks/rhelm"
HY=ROOT/"governance/lead_prechecks"
FREEZE=ROOT/"governance/HYBRID_BGE_RRF_RETRIEVAL_CANDIDATE_FREEZE_V1.json"
CACHE=P/"bge_cache"
ROWS=P/"HYBRID_BGE_RETRIEVAL_ROWS_GOLD_FREE.jsonl"
SEAL=P/"HYBRID_BGE_RETRIEVAL_SEAL.json"
RESULT=P/"POSTSEAL_HYBRID_BGE_RRF_DIAGNOSTIC.json"

sys.path[:0]=[str(HY),str(ROOT),str(A)]
from hybrid_bge_rrf_retriever_candidate import (
    LocalBGE, embed_documents, embed_question, hybrid_rank
)

def load(p): return json.loads(Path(p).read_text("utf-8"))
def jl(p):
    p=Path(p)
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical_sha(obj):
    raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
def append_row(path,row):
    with Path(path).open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
        f.flush()
        os.fsync(f.fileno())
def atomic_json(path,obj):
    path=Path(path); tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8")
    os.replace(tmp,path)

def pool_docs(persona):
    out=[]
    for p in sorted((RROOT/"conversations"/persona).glob("*.json")):
        o=json.loads(p.read_text("utf-8")); date=str(o.get("date") or "")
        for t in o.get("conversation") or []:
            sid=f"{date}:{int(t['turn'])}"
            txt=f"User: {t.get('user','')}\nAssistant: {t.get('assistant','')}"
            out.append({"id":sid,"speaker":"","text":txt})
    by=collections.defaultdict(list)
    for p in sorted((RROOT/"emails"/persona).glob("*.txt")):
        m=re.search(r"(\d{4})_(\d{2})_(\d{2})",p.name)
        if m: by["-".join(m.groups())].append(p)
    for d,ps in sorted(by.items()):
        txt="\n\n".join(f"### {p.name}\n"+p.read_text("utf-8",errors="replace") for p in ps)
        out.append({"id":f"Emails_{d}","speaker":"","text":txt})
    for p in sorted((RROOT/"attachments"/persona).glob("*")):
        if p.is_file():
            out.append({"id":p.name,"speaker":"","text":p.read_text("utf-8",errors="replace")})
    ids=[x["id"] for x in out]
    if len(ids)!=len(set(ids)): raise RuntimeError("duplicate document ids: "+persona)
    return out

def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]+","_",str(s))[:120]

def docs_fingerprint(docs):
    return canonical_sha([{"id":d["id"],"speaker":d.get("speaker",""),"text":d.get("text","")} for d in docs])

def verify_frozen_ranker():
    fr=load(FREEZE)
    candidate=ROOT/fr["bindings"]["candidate_path"]
    if sha(candidate)!=fr["bindings"]["candidate_sha256"]:
        raise RuntimeError("hybrid candidate code drift")
    return {
        "candidate_sha256":fr["bindings"]["candidate_sha256"],
        "semantic_model":fr["algorithm"]["semantic_model"],
        "model_onnx_sha256":fr["model_bindings"]["model_optimized.onnx"]["sha256"],
    }

def cache_paths(persona):
    stem=safe_name(persona)
    return CACHE/(stem+".meta.json"), CACHE/(stem+".embeddings.npy")

def ensure_embeddings(model,persona,docs,model_binding):
    CACHE.mkdir(parents=True,exist_ok=True)
    meta_path,npy_path=cache_paths(persona)
    dsha=docs_fingerprint(docs)
    if meta_path.exists() and npy_path.exists():
        meta=load(meta_path)
        if (meta.get("documents_sha256")==dsha and
            meta.get("candidate_sha256")==model_binding["candidate_sha256"] and
            meta.get("model_onnx_sha256")==model_binding["model_onnx_sha256"] and
            meta.get("document_count")==len(docs)):
            arr=np.load(npy_path,mmap_mode="r")
            if arr.shape==(len(docs),384):
                print("CACHE_HIT",persona,len(docs),flush=True)
                return arr,meta
    t0=time.time()
    print("CACHE_BUILD_BEGIN",persona,len(docs),flush=True)
    arr=embed_documents(model,docs).astype(np.float32,copy=False)
    if arr.shape!=(len(docs),384): raise RuntimeError("embedding shape mismatch")
    tmp=npy_path.with_suffix(".npy.tmp")
    with tmp.open("wb") as f:
        np.save(f,arr,allow_pickle=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp,npy_path)
    meta={
      "schema":"xiaoyu-rhelm-persona-bge-cache-v1",
      "persona":persona,"document_count":len(docs),"documents_sha256":dsha,
      "candidate_sha256":model_binding["candidate_sha256"],
      "semantic_model":model_binding["semantic_model"],
      "model_onnx_sha256":model_binding["model_onnx_sha256"],
      "shape":[len(docs),384],"dtype":"float32",
      "build_seconds":round(time.time()-t0,3),
      "embeddings_sha256":sha(npy_path),
    }
    atomic_json(meta_path,meta)
    print("CACHE_BUILD_DONE",persona,len(docs),meta["build_seconds"],flush=True)
    return np.load(npy_path,mmap_mode="r"),meta

def main():
    model_binding=verify_frozen_ranker()
    gap_seal=load(P/"GAP_PLAN_SEAL.json")
    gap_rows_path=P/"GAP_PLANS.jsonl"
    if gap_seal["plans_sha256"]!=sha(gap_rows_path) or gap_seal.get("gold_loaded") is not False:
        raise RuntimeError("gap plan seal invalid")
    gap_sha=sha(gap_rows_path)
    plans={x["case_id"]:x["plan"] for x in jl(gap_rows_path)}
    ids=load(P0/"CASE_IDS.json")["case_ids"]
    suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
    if not set(ids)<=set(plans): raise RuntimeError("gap plans incomplete")

    # Refuse stale incremental rows from a different generation/ranker contract.
    done={}
    for row in jl(ROWS):
        if row.get("gap_plans_sha256")!=gap_sha:
            raise RuntimeError("stale incremental row gap SHA")
        if row.get("candidate_sha256")!=model_binding["candidate_sha256"]:
            raise RuntimeError("stale incremental row ranker SHA")
        done[row["case_id"]]=row

    # Group by persona so each expensive full-history embedding is built once.
    by_persona=collections.defaultdict(list)
    for cid in ids:
        by_persona[suite[cid]["scope_id"]].append(cid)

    model=LocalBGE()
    cache_meta={}
    for persona,cids in by_persona.items():
        pending=[cid for cid in cids if cid not in done]
        if not pending:
            continue
        docs=pool_docs(persona)
        emb,meta=ensure_embeddings(model,persona,docs,model_binding)
        cache_meta[persona]=meta
        for cid in pending:
            c=suite[cid]
            current=[str(x) for x in c["baseline_source_keys"]]
            selected=set(current); extras=[]; trace=[]
            plan=plans[cid]
            if not plan.get("stop"):
                for qrow in plan.get("search_queries") or []:
                    query=str(qrow["query"])
                    qemb=embed_question(model,query)
                    ranked=hybrid_rank(docs,emb,qemb,query,())
                    hits=[]
                    for sid in ranked:
                        if sid in selected: continue
                        hits.append(sid)
                        if len(hits)>=2: break
                    trace.append({"query":query,
                                  "node_ids":qrow.get("node_ids") or [],
                                  "new_candidates":hits})
                    for sid in hits:
                        if sid in selected: continue
                        selected.add(sid); extras.append(sid)
                        if len(extras)>=3: break
                    if len(extras)>=3: break
            row={
              "schema":"xiaoyu-hybrid-bge-retrieval-row-gold-free-v1",
              "case_id":cid,"persona":persona,
              "source_keys":current+extras,"extra_source_keys":extras,
              "query_trace":trace,"gap_stop":bool(plan.get("stop")),
              "gap_plans_sha256":gap_sha,
              "candidate_sha256":model_binding["candidate_sha256"],
              "documents_sha256":meta["documents_sha256"],
              "semantic_model":model_binding["semantic_model"],
              "gold_loaded":False,
            }
            append_row(ROWS,row); done[cid]=row
            print("HYBRID_ROW",len(done),"/16",cid,"extras",extras,flush=True)

    if set(done)!=set(ids):
        raise RuntimeError("retrieval rows incomplete")

    # Seal gold-free retrieval bytes before opening labels.
    ordered=[done[cid] for cid in ids]
    # Rewrite canonical deterministic row order only after all rows exist.
    canonical=ROWS.with_suffix(".canonical.jsonl")
    with canonical.open("w",encoding="utf-8") as f:
        for row in ordered:
            f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    seal={
      "schema":"xiaoyu-hybrid-bge-retrieval-seal-v1","n":16,
      "rows_path":str(canonical),"rows_sha256":sha(canonical),
      "gap_plans_sha256":gap_sha,"gold_loaded":False,
      "candidate_sha256":model_binding["candidate_sha256"],
      "semantic_model":model_binding["semantic_model"],
      "model_onnx_sha256":model_binding["model_onnx_sha256"],
      "cache_personas":sorted({row["persona"] for row in ordered}),
    }
    atomic_json(SEAL,seal)

    # Only now open exposed diagnostic labels.
    report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
    scored=[]
    for row in ordered:
        cid=row["case_id"]; req=set(report[cid].get("resolved_evidence_ids") or [])
        base=set(suite[cid]["baseline_source_keys"]); cand=set(row["source_keys"])
        scored.append({**row,
          "required":sorted(req),
          "baseline_complete":bool(req) and req<=base,
          "candidate_complete":bool(req) and req<=cand,
          "baseline_hits":len(req&base),"candidate_hits":len(req&cand),
          "required_n":len(req),
          "new_required_sources":sorted(req & set(row["extra_source_keys"]))})
    result={
      "schema":"xiaoyu-v3-gap-hybrid-bge-rrf-exposed16-v2",
      "status":"EXPOSED_DEV_POSTSEAL_RETRIEVAL_DIAGNOSTIC_ONLY",
      "generation_gold_free":True,"ranker_gold_free":True,
      "retrieval_sealed_before_labels":True,
      "retrieval_rows_sha256":seal["rows_sha256"],
      "semantic_model":model_binding["semantic_model"],
      "candidate_sha256":model_binding["candidate_sha256"],
      "n":16,
      "baseline_complete":sum(x["baseline_complete"] for x in scored),
      "candidate_complete":sum(x["candidate_complete"] for x in scored),
      "baseline_hits":sum(x["baseline_hits"] for x in scored),
      "candidate_hits":sum(x["candidate_hits"] for x in scored),
      "required_total":sum(x["required_n"] for x in scored),
      "cases_with_new_required_source":sum(bool(x["new_required_sources"]) for x in scored),
      "rows":scored}
    atomic_json(RESULT,result)
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    main()
