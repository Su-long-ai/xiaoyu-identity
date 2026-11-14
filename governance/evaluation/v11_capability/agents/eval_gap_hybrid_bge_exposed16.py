# -*- coding: utf-8 -*-
"""Post-seal local hybrid-BGE/RRF ranker A/B over frozen v3 gap queries.

Generation side is frozen and gold-free. Required source labels are opened
only after GAP_PLAN_SEAL exists and matches GAP_PLANS bytes.
"""
from pathlib import Path
import collections,hashlib,json,re,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_GAP_ANALYZER_V2_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
RROOT=ROOT/"external/benchmarks/rhelm"
HY=ROOT/"governance/lead_prechecks"
sys.path[:0]=[str(HY),str(ROOT),str(A)]
from hybrid_bge_rrf_retriever_candidate import (
    LocalBGE,embed_documents,embed_question,hybrid_rank
)

def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):return [json.loads(x) for x in Path(p).read_text("utf-8").splitlines() if x.strip()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def pool_docs(persona):
    out=[]
    for p in sorted((RROOT/"conversations"/persona).glob("*.json")):
        o=json.loads(p.read_text("utf-8"));date=str(o.get("date") or "")
        for t in o.get("conversation") or []:
            sid=f"{date}:{int(t['turn'])}"
            txt=f"User: {t.get('user','')}\nAssistant: {t.get('assistant','')}"
            out.append({"id":sid,"speaker":"","text":txt})
    by=collections.defaultdict(list)
    for p in sorted((RROOT/"emails"/persona).glob("*.txt")):
        m=re.search(r"(\d{4})_(\d{2})_(\d{2})",p.name)
        if m:by["-".join(m.groups())].append(p)
    for d,ps in sorted(by.items()):
        txt="\n\n".join(f"### {p.name}\n"+p.read_text("utf-8",errors="replace") for p in ps)
        out.append({"id":f"Emails_{d}","speaker":"","text":txt})
    for p in sorted((RROOT/"attachments"/persona).glob("*")):
        if p.is_file():
            out.append({"id":p.name,"speaker":"","text":p.read_text("utf-8",errors="replace")})
    if len({x["id"] for x in out})!=len(out):raise RuntimeError("duplicate ids "+persona)
    return out

def main():
    seal=load(P/"GAP_PLAN_SEAL.json")
    if seal["plans_sha256"]!=sha(P/"GAP_PLANS.jsonl") or seal["gold_loaded"] is not False:
        raise RuntimeError("gap plan seal invalid")
    plans={x["case_id"]:x["plan"] for x in jl(P/"GAP_PLANS.jsonl")}
    ids=load(P0/"CASE_IDS.json")["case_ids"]
    suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
    assert set(ids)<=set(plans)

    model=LocalBGE()
    cache={}
    rows=[]
    t0=time.time()
    for idx,cid in enumerate(ids,1):
        c=suite[cid];person=c["scope_id"]
        if person not in cache:
            docs=pool_docs(person)
            cache[person]=(docs,embed_documents(model,docs))
        docs,emb=cache[person]
        byid={x["id"]:x for x in docs}
        current=[str(x) for x in c["baseline_source_keys"]]
        selected=set(current);extras=[];trace=[]
        plan=plans[cid]
        if not plan.get("stop"):
            for qrow in plan.get("search_queries") or []:
                query=str(qrow["query"])
                qemb=embed_question(model,query)
                ranked=hybrid_rank(docs,emb,qemb,query,())
                hits=[]
                for sid in ranked:
                    if sid in selected:continue
                    hits.append(sid)
                    if len(hits)>=2:break
                trace.append({"query":query,"node_ids":qrow.get("node_ids") or [],
                              "new_candidates":hits})
                for sid in hits:
                    if sid in selected:continue
                    selected.add(sid);extras.append(sid)
                    if len(extras)>=3:break
                if len(extras)>=3:break
        rows.append({"case_id":cid,"source_keys":current+extras,
                     "extra_source_keys":extras,"query_trace":trace})
        print("HYBRID",idx,"/16",cid,"extras",extras,flush=True)

    # Labels are opened only after all retrieval outputs are fixed in memory.
    report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
    for x in rows:
        cid=x["case_id"];req=set(report[cid].get("resolved_evidence_ids") or [])
        base=set(suite[cid]["baseline_source_keys"]);cand=set(x["source_keys"])
        x.update({"required":sorted(req),"baseline_complete":bool(req) and req<=base,
                  "candidate_complete":bool(req) and req<=cand,
                  "baseline_hits":len(req&base),"candidate_hits":len(req&cand),
                  "required_n":len(req),
                  "new_required_sources":sorted(req & set(x["extra_source_keys"]))})
    result={"schema":"xiaoyu-v3-gap-hybrid-bge-rrf-exposed16-v1",
      "status":"EXPOSED_DEV_POSTSEAL_RETRIEVAL_DIAGNOSTIC_ONLY",
      "generation_gap_plans_sha256":sha(P/"GAP_PLANS.jsonl"),
      "generation_gold_free":True,"ranker_gold_free":True,
      "semantic_model":"qdrant/bge-small-en-v1.5-onnx-q",
      "ranker":"frozen hybrid_bge_rrf_retriever_candidate",
      "n":16,
      "baseline_complete":sum(x["baseline_complete"] for x in rows),
      "candidate_complete":sum(x["candidate_complete"] for x in rows),
      "baseline_hits":sum(x["baseline_hits"] for x in rows),
      "candidate_hits":sum(x["candidate_hits"] for x in rows),
      "required_total":sum(x["required_n"] for x in rows),
      "cases_with_new_required_source":sum(bool(x["new_required_sources"]) for x in rows),
      "runtime_seconds":round(time.time()-t0,3),"rows":rows}
    out=P/"POSTSEAL_HYBRID_BGE_RRF_DIAGNOSTIC.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
