# -*- coding: utf-8 -*-
"""Post-seal rank-position diagnosis for missing required RHELM sources."""
from pathlib import Path
import collections,hashlib,json,re,sys
import numpy as np

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_GAP_ANALYZER_V2_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
RROOT=ROOT/"external/benchmarks/rhelm"
HY=ROOT/"governance/lead_prechecks"
CACHE=P/"bge_cache"

sys.path[:0]=[str(HY),str(ROOT),str(A)]
from hybrid_bge_rrf_retriever_candidate import (
    LocalBGE,embed_question,bm25_rank,semantic_rank,rrf_rank
)

def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):return [json.loads(x) for x in Path(p).read_text("utf-8").splitlines() if x.strip()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def safe_name(s):return re.sub(r"[^A-Za-z0-9_.-]+","_",str(s))[:120]

def pool_docs(persona):
    out=[]
    for p in sorted((RROOT/"conversations"/persona).glob("*.json")):
        o=json.loads(p.read_text("utf-8"));date=str(o.get("date") or "")
        for t in o.get("conversation") or []:
            sid=f"{date}:{int(t['turn'])}"
            out.append({"id":sid,"speaker":"",
              "text":f"User: {t.get('user','')}\nAssistant: {t.get('assistant','')}"})
    by=collections.defaultdict(list)
    for p in sorted((RROOT/"emails"/persona).glob("*.txt")):
        m=re.search(r"(\d{4})_(\d{2})_(\d{2})",p.name)
        if m:by["-".join(m.groups())].append(p)
    for d,ps in sorted(by.items()):
        txt="\n\n".join(f"### {p.name}\n"+p.read_text("utf-8",errors="replace") for p in ps)
        out.append({"id":f"Emails_{d}","speaker":"","text":txt})
    for p in sorted((RROOT/"attachments"/persona).glob("*")):
        if p.is_file():out.append({"id":p.name,"speaker":"","text":p.read_text("utf-8",errors="replace")})
    return out

def rank_of(ids,target):
    try:return ids.index(target)+1
    except ValueError:return None

def best(values):
    vals=[x for x in values if isinstance(x,int)]
    return min(vals) if vals else None

def bucket(r):
    if r is None:return ">100/not-fused"
    for k in (2,3,5,10,20,50,100):
        if r<=k:return f"<={k}"
    return ">100/not-fused"

def main():
    seal=load(P/"HYBRID_BGE_RETRIEVAL_SEAL.json")
    rows_path=Path(seal["rows_path"])
    if seal["rows_sha256"]!=sha(rows_path) or seal.get("gold_loaded") is not False:
        raise RuntimeError("retrieval seal invalid")
    plans={x["case_id"]:x["plan"] for x in jl(P/"GAP_PLANS.jsonl")}
    ids=load(P0/"CASE_IDS.json")["case_ids"]
    suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
    report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
    model=LocalBGE()
    cache={}
    missing_rows=[]
    case_rows=[]
    for cid in ids:
        c=suite[cid];persona=c["scope_id"]
        req=set(report[cid].get("resolved_evidence_ids") or [])
        base=set(c["baseline_source_keys"])
        missing=sorted(req-base)
        if not missing:
            case_rows.append({"case_id":cid,"missing_required":[],"gap_stop":plans[cid].get("stop")})
            continue
        if persona not in cache:
            docs=pool_docs(persona)
            meta=load(CACHE/(safe_name(persona)+".meta.json"))
            emb=np.load(CACHE/(safe_name(persona)+".embeddings.npy"),mmap_mode="r")
            if meta["document_count"]!=len(docs):raise RuntimeError("cache doc count drift")
            cache[persona]=(docs,emb)
        docs,emb=cache[persona]
        qrows=[]
        for qrow in plans[cid].get("search_queries") or []:
            query=str(qrow["query"])
            qemb=embed_question(model,query)
            lex=bm25_rank(docs,query,())
            sem=semantic_rank(docs,emb,qemb)
            fused100=rrf_rank(lex,sem,cap=100)
            qrows.append({"query":query,"lex":lex,"sem":sem,"fused":fused100})
        mdetails=[]
        for target in missing:
            l=best([rank_of(q["lex"],target) for q in qrows])
            s=best([rank_of(q["sem"],target) for q in qrows])
            f=best([rank_of(q["fused"],target) for q in qrows])
            d={"case_id":cid,"target":target,"best_lexical_rank":l,
               "best_semantic_rank":s,"best_rrf_rank":f,
               "rrf_bucket":bucket(f),"query_count":len(qrows)}
            missing_rows.append(d);mdetails.append(d)
        case_rows.append({"case_id":cid,"gap_stop":plans[cid].get("stop"),
                          "missing_required":mdetails})
        print("RANK_DIAG",cid,[(x["target"],x["best_rrf_rank"]) for x in mdetails],flush=True)
    counts=collections.Counter(x["rrf_bucket"] for x in missing_rows)
    result={"schema":"xiaoyu-gap-hybrid-rank-position-diagnostic-v1",
      "status":"EXPOSED_DEV_POSTSEAL_DIAGNOSTIC_ONLY",
      "retrieval_rows_sha256":seal["rows_sha256"],
      "missing_required_source_count":len(missing_rows),
      "rrf_bucket_counts":dict(counts),
      "rrf_within_3":sum((x["best_rrf_rank"] or 999999)<=3 for x in missing_rows),
      "rrf_within_10":sum((x["best_rrf_rank"] or 999999)<=10 for x in missing_rows),
      "rrf_within_20":sum((x["best_rrf_rank"] or 999999)<=20 for x in missing_rows),
      "rrf_within_50":sum((x["best_rrf_rank"] or 999999)<=50 for x in missing_rows),
      "rrf_within_100":sum((x["best_rrf_rank"] or 999999)<=100 for x in missing_rows),
      "semantic_within_20":sum((x["best_semantic_rank"] or 999999)<=20 for x in missing_rows),
      "lexical_within_20":sum((x["best_lexical_rank"] or 999999)<=20 for x in missing_rows),
      "rows":missing_rows,"cases":case_rows}
    out=P/"POSTSEAL_HYBRID_RANK_POSITIONS.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("rows","cases")},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
