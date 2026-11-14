# -*- coding: utf-8 -*-
from pathlib import Path
import hashlib,json,sqlite3,sys,time
import numpy as np
ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_METADATA_RETRIEVER_20261114"
G=A/"results/product_integration/LEAD_ANSWER_CONTRACT_GAP_ANALYZER_V2_20261114"
V3=A/"results/product_integration/LEAD_ANSWER_CONTRACT_V3_PRECONDITION_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
CAND=ROOT/"governance/lead_prechecks/contract_metadata_gap_retriever_candidate.py"
sys.path[:0]=[str(A),str(ROOT/"governance/lead_prechecks"),str(ROOT)]
import eval_gap_hybrid_bge_exposed16_cached as hy
from hybrid_bge_rrf_retriever_candidate import LocalBGE,embed_question,hybrid_rank
import contract_metadata_gap_retriever_candidate as cm
TASK="M2-X337"
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):return [json.loads(x) for x in Path(p).read_text("utf-8").splitlines() if x.strip()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 bind=hy.verify_frozen_ranker()
 ids=load(P0/"CASE_IDS.json")["case_ids"]
 suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
 plans={x["case_id"]:x["plan"] for x in jl(G/"GAP_PLANS.jsonl")}
 contracts={x["case_id"]:x["contract"] for x in jl(V3/"CONTRACTS.jsonl")}
 model=LocalBGE();rows=[]
 # Candidate mechanics run without labels first.
 for cid in ids:
  c=suite[cid];docs=hy.pool_docs(c["scope_id"]);emb,_=hy.ensure_embeddings(model,c["scope_id"],docs,bind)
  enriched=cm.enrich_documents(docs);ix=cm.filtered_indices(enriched,c["question"])
  fd=[enriched[i] for i in ix];fe=np.asarray(emb)[ix]
  current=list(map(str,c["baseline_source_keys"]));selected=set(current);extras=[];anchors=[];trace=[]
  plan=plans[cid];contract=contracts[cid]
  if not plan.get("stop"):
   for qrow in plan.get("search_queries") or []:
    q=str(qrow["query"]);ranked=hybrid_rank(fd,fe,embed_question(model,q),q,())
    hits=[]
    for sid in ranked:
     if sid in selected:continue
     hits.append(sid)
     if len(hits)>=2:break
    trace.append({"query":q,"pool_n":len(fd),"new_candidates":hits})
    for sid in hits:
     if sid in selected:continue
     selected.add(sid);extras.append(sid);anchors.append(sid)
     if len(extras)>=3:break
    if len(extras)>=3:break
  # Adjacency is packaging expansion, not another ranked anchor.
  adjacent=[]
  if cm.needs_adjacency(contract):
   for sid in list(anchors):
    for aid in cm.adjacent_ids(docs,sid,radius=2):
     if aid not in selected:
      selected.add(aid);adjacent.append(aid)
     if len(adjacent)>=6:break
    if len(adjacent)>=6:break
  rows.append({"case_id":cid,"source_keys":current+extras+adjacent,
    "ranked_extra_source_keys":extras,"adjacent_source_keys":adjacent,
    "filtered_pool_n":len(fd),"query_trace":trace,
    "time_constraint":cm.explicit_time_constraint(c["question"]),
    "attachment_intent":cm.attachment_intent(c["question"]),"gold_loaded":False})
 # Seal retrieval outputs before opening exposed labels.
 goldfree=P/"RETRIEVAL_ROWS_GOLD_FREE.jsonl"
 with goldfree.open("w",encoding="utf-8") as f:
  for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
 freeze={"schema":"xiaoyu-contract-metadata-retriever-dev-freeze-v1","candidate_sha256":sha(CAND),
   "retrieval_rows_sha256":sha(goldfree),"gold_loaded":False,
   "base_hybrid_candidate_sha256":bind["candidate_sha256"],"n":16}
 (P/"FREEZE.json").write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n","utf-8")
 # Open exposed labels only now.
 report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
 base_diag=load(G/"POSTSEAL_HYBRID_BGE_RRF_DIAGNOSTIC.json")
 base_by={x["case_id"]:x for x in base_diag["rows"]}
 scored=[]
 for r in rows:
  cid=r["case_id"];req=set(report[cid].get("resolved_evidence_ids") or [])
  base=set(suite[cid]["baseline_source_keys"]);cand=set(r["source_keys"])
  scored.append({**r,"required":sorted(req),
   "baseline_hits":len(req&base),"candidate_hits":len(req&cand),
   "baseline_complete":bool(req) and req<=base,"candidate_complete":bool(req) and req<=cand,
   "new_required_sources":sorted(req&(cand-base))})
 result={"schema":"xiaoyu-contract-metadata-retriever-exposed16-dev-v1",
  "status":"EXPOSED_DEV_LAST_IMPLEMENTATION_FIX_BEFORE_FRESH",
  "candidate_sha256":freeze["candidate_sha256"],"n":16,
  "baseline_complete":sum(x["baseline_complete"] for x in scored),
  "candidate_complete":sum(x["candidate_complete"] for x in scored),
  "baseline_hits":sum(x["baseline_hits"] for x in scored),
  "candidate_hits":sum(x["candidate_hits"] for x in scored),
  "previous_hybrid_complete":base_diag["candidate_complete"],
  "previous_hybrid_hits":base_diag["candidate_hits"],
  "cases_with_new_required_source":sum(bool(x["new_required_sources"]) for x in scored),
  "fresh_capability_credit":False,"rows":scored}
 out=P/"DEV_REACHABILITY.json";out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3") as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",(str(out),time.time(),TASK));db.commit()
 print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))
 for x in scored:
  if x["new_required_sources"]:print(x["case_id"],x["new_required_sources"],"complete",x["candidate_complete"])
if __name__=="__main__":main()
