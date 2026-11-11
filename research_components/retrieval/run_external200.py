# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, collections, hashlib, json, os, re, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
G=ROOT/"governance"; FAST=G/"fastlane"
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
import model_adapter
from research_components.retrieval.api import authorized_documents,load_component,prepare_component,rank_component,component_fingerprint

INPUT=G/"locomo_blind_200_input_v2.json"
SOURCE=G/"locomo_blind_source_v2_gold_stripped.json"
STORES=G/"capability_external_200_20261102"/"stores"
OLDW=G/"workspaces"/"fish-2c13552ab6324dbd"/"external200"
GOLD=OLDW/"gold_joined.json"
OLD_ANSWER_REQUESTS=OLDW/"answer_requests.json"
DIAG=G/"workspaces"/"fish-5e91afcff84e4ef6"/"evidence_diagnostic.json"
BASELINE=FAST/"BASELINE.json"
EXPECTED_INPUT_SHA="57cbfc53ce0818933831e6b87b8a2c038922a423e533aae2ab2610525c69398c"

JUDGE_SYSTEM="You are an expert grader that determines if answers to questions match a gold standard answer."
JUDGE_PROMPT="""Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given the following data:
(1) a question (posed by one user to another user),
(2) a 'gold' (ground truth) answer,
(3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic. The generated answer might be much longer, but be generous: as long as it touches on the same topic as the gold answer, count it as CORRECT.
For time questions, accept equivalent references to the same date or time period even if format differs.

Question: {question}
Gold answer: {golden_answer}
Generated answer: {response}

Return exactly one JSON object: {{"label":"CORRECT"}} or {{"label":"WRONG"}}."""

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def deepseek():
    b=model_adapter.PROVIDERS["deepseek"]
    return {"provider":"deepseek","url":b["url"],"model":"deepseek-flash","key_env":b["key_env"],
            "thinking":"disabled","reasoning_effort":"none","temperature":0,"top_p":1,
            "response_format":{"type":"json_object"}}
def parse_json(raw):
    try:
        x=json.loads(raw)
        if isinstance(x,dict): return x
    except Exception: pass
    return {}
def user_home(uid): return STORES/hashlib.sha256(str(uid).encode()).hexdigest()

def raw_maps():
    src=json.loads(SOURCE.read_text(encoding="utf-8"))
    out={}
    for s in src["samples"]:
        sid=str(s["sample_id"]); conv=s["conversation"]; by=collections.defaultdict(collections.deque)
        keys=sorted([k for k,v in conv.items() if k.startswith("session_") and isinstance(v,list)],key=lambda k:int(k.split("_")[1]))
        for sk in keys:
            for t in conv[sk]:
                speaker=str(t.get("speaker") or "")
                text=(speaker+": "+str(t.get("text") or "")).strip()
                by[(sk,speaker,text)].append(str(t["dia_id"]))
        out[sid]=by
    return out

def load_side(sid,side,raw_by):
    uid=f"cap200_{sid}_{side}"; home=user_home(uid)
    st=IdentityStore(home); br=ProductMemoryBridge(home,st)
    try:
        docs=authorized_documents(br)
        result=[]
        for d in docs:
            key=(str(d.get("session") or ""),str(d.get("speaker") or ""),str(d.get("text") or "").strip())
            q=raw_by.get(key)
            if not q: raise RuntimeError(f"raw binding missing {sid}/{side}: {key!r}")
            did=q.popleft()
            x=dict(d); x["id"]=f"{side}:{d['id']}"; x["source_key"]=did; x["speaker_side"]=side
            result.append(x)
        return result
    finally:
        br.close(); st.close()

def prepare_external_state(component,docs,sid):
    """Reuse the already-frozen BGE document cache when the component uses the same embedding model."""
    supported={"hybrid_bge_bm25_rrf_v1","multifacet_bge_rrf_v1"}
    cache=G/"lead_prechecks"/"bge_exposed_v1_cache"/f"{sid}.npz"
    if str(getattr(component,"component_id","")) in supported and cache.is_file():
        z=np.load(cache,allow_pickle=False)
        ids=[str(x) for x in z["ids"].tolist()]
        emb=np.asarray(z["emb"],dtype=np.float32)
        if emb.shape!=(len(ids),384) or len(ids)!=len(set(ids)):
            raise RuntimeError(f"invalid BGE cache {sid}")
        by={did:emb[i] for i,did in enumerate(ids)}
        missing=[str(d.get("source_key") or "") for d in docs if str(d.get("source_key") or "") not in by]
        if missing:
            raise RuntimeError(f"BGE cache missing authorized source IDs for {sid}: {missing[:3]}")
        return {"documents":[dict(d) for d in docs],
                "embeddings":np.stack([by[str(d["source_key"])] for d in docs],axis=0)}
    return prepare_component(component,docs)

def answer_messages(system,question,docs):
    mems=[]
    for i,d in enumerate(docs,1):
        mems.append(f"[{i}] authority=user_source_history timestamp={d.get('timestamp') or 'unknown'}\n{d['text']}")
    user="AUTHORIZED MEMORIES:\n"+"\n\n".join(mems)+"\n\nQUESTION:\n"+question
    return [{"role":"system","content":system},{"role":"user","content":user}]

def summary(rows):
    by={}
    for r in rows:
        c=str(r["category"]); z=by.setdefault(c,{"n":0,"correct":0})
        z["n"]+=1; z["correct"]+=int(r["correct"])
    for z in by.values(): z["accuracy"]=z["correct"]/z["n"]
    correct=sum(r["correct"] for r in rows)
    primary=[r for r in rows if str(r["category"]) in {"1","2","4"}]
    return {"overall":{"n":len(rows),"correct":correct,"accuracy":correct/len(rows)},
            "primary_124":{"n":len(primary),"correct":sum(r["correct"] for r in primary),"accuracy":sum(r["correct"] for r in primary)/len(primary)},
            "by_category":by}

def evidence_summary(selected_by_id):
    diag=json.loads(DIAG.read_text(encoding="utf-8")); agg={"n":0,"full":0,"any":0,"hit":0,"total":0}; by={}
    rows=[]
    for d in diag["rows"]:
        bid=str(d["blind_id"]); ev=[str(x) for x in d.get("evidence_ids") or []]; got=set(selected_by_id[bid])
        hit=sum(x in got for x in ev); full=bool(ev) and hit==len(ev); anyhit=hit>0; c=str(d["category"])
        for z in (agg,by.setdefault(c,{"n":0,"full":0,"any":0,"hit":0,"total":0})):
            z["n"]+=1; z["full"]+=int(full); z["any"]+=int(anyhit); z["hit"]+=hit; z["total"]+=len(ev)
        rows.append({"blind_id":bid,"category":c,"evidence_ids":ev,"selected_ids":selected_by_id[bid],"full":full,"hit":hit,"total":len(ev)})
    def pack(z): return {"n":z["n"],"full_evidence_recall_rate":z["full"]/z["n"],"any_evidence_recall_rate":z["any"]/z["n"],"evidence_item_recall":z["hit"]/z["total"] if z["total"] else None}
    return {"overall":pack(agg),"by_category":{k:pack(v) for k,v in sorted(by.items())},"rows":rows}

def promote_baseline(result_path,result,component_path,component):
    old=json.loads(BASELINE.read_text(encoding="utf-8")); gen=int(old.get("generation") or 0)+1
    dest=FAST/"baselines"/f"g{gen:03d}_{component.component_id}"
    dest.mkdir(parents=True,exist_ok=True)
    shutil.copy2(component_path,dest/"component.py"); shutil.copy2(result_path,dest/"external200_result.json")
    new={"schema":"xiaoyu-fast-retrieval-baseline-v1","generation":gen,
         "baseline_id":f"baseline-g{gen:03d}-{component.component_id}","created_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "source":str(result_path.relative_to(ROOT)).replace("\\","/"),
         "method":{"name":component.component_id,"component":str((dest/"component.py").relative_to(ROOT)).replace("\\","/"),"component_sha256":sha(dest/"component.py")},
         "external200":{"questions":200,"overall_correct":result["score"]["overall"]["correct"],"overall_accuracy":result["score"]["overall"]["accuracy"],
             "multi_hop_accuracy":result["score"]["by_category"]["1"]["accuracy"],"temporal_accuracy":result["score"]["by_category"]["2"]["accuracy"],
             "open_domain_accuracy":result["score"]["by_category"]["3"]["accuracy"],"single_hop_accuracy":result["score"]["by_category"]["4"]["accuracy"],
             "full_evidence_recall_rate":result["evidence"]["overall"]["full_evidence_recall_rate"],
             "multi_hop_full_evidence_recall_rate":result["evidence"]["by_category"]["1"]["full_evidence_recall_rate"],
             "answerer":"deepseek-flash","judge":"deepseek-flash","context_cap":20},
         "breakthrough_rule":old.get("breakthrough_rule",{"min_overall_accuracy_delta":0.02,"min_full_evidence_delta":0.0,"material_authority_regressions_max":0}),
         "previous_baseline":old.get("baseline_id")}
    BASELINE.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return new,dest

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--audit",required=True); args=ap.parse_args()
    audit_path=Path(args.audit).resolve(); audit=json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("verdict")!="PASS" or audit.get("external200_authorized") is not True: raise SystemExit("light audit PASS required")
    comp_path=Path(audit["component"]["path"]).resolve()
    if sha(comp_path)!=audit["component"]["sha256"]: raise SystemExit("component SHA drift after audit")
    if sha(INPUT)!=EXPECTED_INPUT_SHA: raise SystemExit("external200 input drift")
    component,module_path=load_component(str(comp_path)); fp=component_fingerprint(module_path,component.component_id)
    run_id="ext200_"+time.strftime("%Y%m%d_%H%M%S")+"_"+re.sub(r"[^A-Za-z0-9_.-]+","_",component.component_id)
    outdir=FAST/"runs"/run_id; outdir.mkdir(parents=True,exist_ok=False)
    data=json.loads(INPUT.read_text(encoding="utf-8")); maps=raw_maps()
    # Batch original query embeddings once. Components still execute their unchanged
    # rank() code; its model.encode() simply hits this in-process cache for exact questions.
    if str(getattr(component,"component_id","")) in {"hybrid_bge_bm25_rrf_v1","multifacet_bge_rrf_v1"} and hasattr(component,"model"):
        all_questions=[str(q["question"]) for sample in data["samples"] for q in sample["questions"]]
        query_texts=list(all_questions)
        if str(getattr(component,"component_id",""))=="multifacet_bge_rrf_v1":
            mod=sys.modules.get(component.__class__.__module__)
            facet_fn=getattr(mod,"facet_queries",None) if mod is not None else None
            if callable(facet_fn):
                query_texts=[facet for question in all_questions for facet in facet_fn(question)]
        unique_questions=list(dict.fromkeys(query_texts))
        qemb=component.model.encode(unique_questions,batch_size=64,max_length=128,query=True)
        qcache={q:qemb[i] for i,q in enumerate(unique_questions)}
        original_encode=component.model.encode
        def cached_encode(texts,batch_size=64,max_length=256,query=False):
            vals=[str(x) for x in texts]
            if query and all(v in qcache for v in vals):
                return np.stack([qcache[v] for v in vals],axis=0)
            return original_encode(texts,batch_size=batch_size,max_length=max_length,query=query)
        component.model.encode=cached_encode
    docs_by={}; state_by={}
    for sample in data["samples"]:
        sid=str(sample["sample_id"]); rm=maps[sid]
        docs=load_side(sid,"a",rm)+load_side(sid,"b",rm)
        if len({d["source_key"] for d in docs})!=len(docs): raise RuntimeError(f"source binding not unique {sid}")
        docs_by[sid]=docs; state_by[sid]=prepare_external_state(component,docs,sid)
    ret_rows=[]; selected={}
    for sample in data["samples"]:
        sid=str(sample["sample_id"]); speakers=(sample["conversation"]["speaker_a"],sample["conversation"]["speaker_b"])
        for q in sample["questions"]:
            bid=str(q["blind_id"]); question=str(q["question"])
            docs=rank_component(component,state_by[sid],docs_by[sid],question,20,metadata={"speaker_names":speakers})
            ids=[str(d["source_key"]) for d in docs]; selected[bid]=ids
            ret_rows.append({"blind_id":bid,"sample_id":sid,"question":question,"selected_source_ids":ids,
              "authorized_memories":[{"authority":"user_source_history","timestamp":d.get("timestamp"),"text":d["text"],"source_id":d["source_key"]} for d in docs]})
    retrieval={"schema":"xiaoyu-fast-external200-retrieval-v1","input_sha256":sha(INPUT),"component":fp,"context_cap":20,"question_count":len(ret_rows),"rows":ret_rows}
    rp=outdir/"retrieval.json"; rp.write_text(json.dumps(retrieval,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (outdir/"RETRIEVAL_SEAL.json").write_text(json.dumps({"status":"SEALED_BEFORE_GOLD","sha256":sha(rp)},indent=2)+"\n",encoding="utf-8")

    oldreq=json.loads(OLD_ANSWER_REQUESTS.read_text(encoding="utf-8")); system=oldreq["rows"][0]["messages"][0]["content"]
    cfg=deepseek(); pred=[]; usage={"calls":0,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
    workers=max(1,min(8,int(os.environ.get("XIAOYU_FASTLANE_CONCURRENCY","8"))))
    def answer_one(r):
        raw,u=model_adapter.chat(cfg,answer_messages(system,r["question"],r["authorized_memories"]),max_tokens=96,timeout=120)
        return str(parse_json(raw).get("answer") or raw).strip(),u
    with ThreadPoolExecutor(max_workers=workers) as ex:
        answer_results=list(ex.map(answer_one,ret_rows))
    for r,(ans,u) in zip(ret_rows,answer_results):
        pred.append({"blind_id":r["blind_id"],"sample_id":r["sample_id"],"answer":ans})
        usage["calls"]+=1
        for k in ("prompt_tokens","completion_tokens","total_tokens"):usage[k]+=int(u.get(k) or 0)
    pp=outdir/"predictions.json"; pp.write_text(json.dumps({"schema":"xiaoyu-fast-external200-predictions-v1","rows":pred,"usage":usage},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (outdir/"PREDICTION_SEAL.json").write_text(json.dumps({"status":"SEALED_BEFORE_GOLD","sha256":sha(pp),"retrieval_sha256":sha(rp)},indent=2)+"\n",encoding="utf-8")

    # Gold is loaded only after retrieval and predictions are sealed.
    gold=json.loads(GOLD.read_text(encoding="utf-8")); gm={str(r["blind_id"]):r for r in gold["rows"]}
    judged=[]; jusage={"calls":0,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
    def judge_one(predrow):
        g=gm[predrow["blind_id"]]
        prompt=JUDGE_PROMPT.format(question=g["question"],golden_answer=g["gold_answer"],response=predrow["answer"])
        raw,u=model_adapter.chat(cfg,[{"role":"system","content":JUDGE_SYSTEM},{"role":"user","content":prompt}],max_tokens=64,timeout=120)
        label=str(parse_json(raw).get("label") or "").upper()
        if label not in {"CORRECT","WRONG"}: raise RuntimeError("invalid judge label")
        return g,label,u
    with ThreadPoolExecutor(max_workers=workers) as ex:
        judge_results=list(ex.map(judge_one,pred))
    for predrow,(g,label,u) in zip(pred,judge_results):
        judged.append({"blind_id":predrow["blind_id"],"category":str(g["category"]),"answer":predrow["answer"],"gold_answer":g["gold_answer"],"label":label,"correct":label=="CORRECT"})
        jusage["calls"]+=1
        for k in ("prompt_tokens","completion_tokens","total_tokens"):jusage[k]+=int(u.get(k) or 0)
    score=summary(judged); ev=evidence_summary(selected); base=json.loads(BASELINE.read_text(encoding="utf-8"))
    ba=float(base["external200"]["overall_accuracy"]); bf=float(base["external200"]["full_evidence_recall_rate"])
    rule=base.get("breakthrough_rule") or {}; minacc=float(rule.get("min_overall_accuracy_delta",0.02)); minfull=float(rule.get("min_full_evidence_delta",0.0))
    delta={"overall_accuracy":score["overall"]["accuracy"]-ba,"full_evidence_recall_rate":ev["overall"]["full_evidence_recall_rate"]-bf}
    breakthrough=delta["overall_accuracy"]>=minacc and delta["full_evidence_recall_rate"]>=minfull
    result={"schema":"xiaoyu-fast-external200-result-v1","status":"BREAKTHROUGH" if breakthrough else "NO_BREAKTHROUGH",
      "audit":str(audit_path),"component":fp,"context_cap":20,"answer_usage":usage,"judge_usage":jusage,
      "score":score,"evidence":{"overall":ev["overall"],"by_category":ev["by_category"]},"baseline_before":base,"delta":delta,"breakthrough":breakthrough,
      "no_new_questions":True,"prediction_sealed_before_gold":True}
    result_path=outdir/"result.json"; result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    promoted=None
    if breakthrough:
        new,dest=promote_baseline(result_path,result,comp_path,component); promoted={"baseline_id":new["baseline_id"],"path":str(BASELINE),"snapshot":str(dest)}
    print(json.dumps({"status":result["status"],"result":str(result_path),"score":score,"evidence":result["evidence"],"delta":delta,"promoted":promoted},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
