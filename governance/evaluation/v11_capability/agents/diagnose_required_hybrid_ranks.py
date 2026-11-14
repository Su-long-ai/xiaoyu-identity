# -*- coding: utf-8 -*-
from pathlib import Path
from collections import Counter
import json,sqlite3,sys,time
import numpy as np
ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_GAP_ANALYZER_V2_20261114"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
EXT=ROOT/"governance/evaluation/external_suite"
sys.path[:0]=[str(A),str(ROOT)]
import eval_gap_hybrid_bge_exposed16_cached as hy
from governance.lead_prechecks.hybrid_bge_rrf_retriever_candidate import LocalBGE,embed_question,hybrid_rank
TASK="M2-X336"
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):return [json.loads(x) for x in Path(p).read_text("utf-8").splitlines() if x.strip()]
def bucket(rank):
 if rank is None:return "not_retrieved_by_any_query"
 if rank<=2:return "top2"
 if rank<=5:return "top3_5"
 if rank<=10:return "top6_10"
 if rank<=20:return "top11_20"
 if rank<=50:return "top21_50"
 return "gt50"
def main():
 bind=hy.verify_frozen_ranker()
 plans={x["case_id"]:x["plan"] for x in jl(P/"GAP_PLANS.jsonl")}
 ids=load(P0/"CASE_IDS.json")["case_ids"]
 suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
 report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
 model=LocalBGE(); rows=[];dist=Counter()
 hyp={k:{"hits":0,"complete":0} for k in (2,3,5,8)}
 for cid in ids:
  c=suite[cid];person=c["scope_id"];docs=hy.pool_docs(person)
  emb,meta=hy.ensure_embeddings(model,person,docs,bind)
  req=set(report[cid].get("resolved_evidence_ids") or [])
  base=set(c["baseline_source_keys"]); missing=sorted(req-base)
  plan=plans[cid]; query_ranks=[]; best={x:None for x in missing}; ranked_cache=[]
  for qrow in plan.get("search_queries") or []:
   q=str(qrow["query"]);ranking=hybrid_rank(docs,emb,embed_question(model,q),q,())
   pos={sid:i+1 for i,sid in enumerate(ranking)}
   ranked_cache.append((q,ranking))
   qr={sid:pos.get(sid) for sid in missing}
   query_ranks.append({"query":q,"required_ranks":qr})
   for sid,r in qr.items():
    if r is not None and (best[sid] is None or r<best[sid]):best[sid]=r
  for r in best.values():dist[bucket(r)]+=1
  for k in hyp:
   selected=set(base);extras=[]
   if not plan.get("stop"):
    for q,ranking in ranked_cache:
     hits=[]
     for sid in ranking:
      if sid in selected:continue
      hits.append(sid)
      if len(hits)>=k:break
     for sid in hits:
      if sid in selected:continue
      selected.add(sid);extras.append(sid)
      if len(extras)>=3:break
     if len(extras)>=3:break
   hyp[k]["hits"]+=len(req&selected)
   hyp[k]["complete"]+=int(bool(req) and req<=selected)
  rows.append({"case_id":cid,"gap_stop":bool(plan.get("stop")),"required":sorted(req),
               "baseline_missing_required":missing,"best_required_rank":best,
               "query_ranks":query_ranks,
               "failure_mode":("planner_stopped_with_missing_required" if missing and plan.get("stop")
                 else "ranker_or_query_miss" if any(v is None or v>10 for v in best.values())
                 else "width_or_global_extra_cap" if missing else "baseline_complete")})
 result={"schema":"xiaoyu-postseal-required-hybrid-rank-diagnostic-v1",
   "status":"EXPOSED_DEV_POSTSEAL_DIAGNOSTIC_ONLY","n":16,
   "required_rank_distribution":dict(dist),"hypothetical_same_plan_global_max_extra3":hyp,
   "rows":rows}
 out=P/"POSTSEAL_REQUIRED_RANK_DIAGNOSTIC.json"
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3") as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",(str(out),time.time(),TASK));db.commit()
 print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))
 for r in rows:
  if r["baseline_missing_required"]:
   print(r["case_id"],r["failure_mode"],r["best_required_rank"])
if __name__=="__main__":main()
