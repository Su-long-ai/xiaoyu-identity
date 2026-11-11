#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,hashlib,importlib.machinery,importlib.util,json,sqlite3,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUNTIME=GOV/"stagea_answerer_v5_full_runtime"
MANIFEST=GOV/"STAGEA_ANSWERER_V5_FULL_JUDGE_V1.json"
WRAPPER=GOV/"stagea_answerer_v5_full_judge_v1.py"
EVAL=GOV/"confirmatory_frozen"/"HALUMEM_OFFICIAL_EVAL_TOOLS.PY"
QA=GOV/"budget50_halumem_dev_runtime_v1"/"QA_INPUTS_POST_SEAL.json"
ANS=RUNTIME/"results.json"
PROG=RUNTIME/"judge_progress.json"
FINAL=RUNTIME/"judge_result.json"
LEDGER=RUNTIME/"judge_ledger_qwen38_flash_v5full.sqlite3"
THIS=Path(__file__).resolve()

class ScoreError(RuntimeError):
    pass

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load(p):
    return json.loads(Path(p).read_text("utf-8"))

def atomic(p,obj):
    p=Path(p)
    q=p.with_suffix(p.suffix+".tmp")
    q.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8")
    q.replace(p)

def load_tools():
    if ".PY" not in importlib.machinery.SOURCE_SUFFIXES:
        importlib.machinery.SOURCE_SUFFIXES.append(".PY")
    ws=importlib.util.spec_from_file_location("llms",WRAPPER)
    w=importlib.util.module_from_spec(ws)
    sys.modules["llms"]=w
    ws.loader.exec_module(w)
    es=importlib.util.spec_from_file_location("_ansv5full_eval",EVAL)
    e=importlib.util.module_from_spec(es)
    es.loader.exec_module(e)
    return w,e

def state():
    m=load(MANIFEST)
    if m.get("schema")!="xiaoyu-stagea-answerer-v5full-judge-v1" or m.get("status")!="EXECUTION_AUTHORIZED":
        raise ScoreError("manifest not authorized")
    if m["implementation"]["scorer_sha256"]!=sha(THIS):
        raise ScoreError("scorer byte drift")
    if m["implementation"]["judge_wrapper_sha256"]!=sha(WRAPPER):
        raise ScoreError("judge wrapper byte drift")
    for key,path in [("answers_sha256",ANS),("qa_inputs_sha256",QA),("official_eval_tools_sha256",EVAL)]:
        if m["bindings"][key]!=sha(path):
            raise ScoreError(key+" drift")
    answers=load(ANS)["rows"]
    qa_rows=load(QA)["rows"]
    qmap={x["qa_case_id"]:x for x in qa_rows}
    if len(answers)!=51 or [x["qa_case_id"] for x in answers]!=m["case_qids"]:
        raise ScoreError("case qids/count drift")
    if set(m["case_qids"])!=set(qmap):
        raise ScoreError("judge membership not exact full QA set")
    return m,answers,qmap

def ledger_state():
    if not LEDGER.exists():
        return {},[],0
    con=sqlite3.connect(LEDGER)
    con.row_factory=sqlite3.Row
    try:
        counts={r["status"]:int(r["n"]) for r in con.execute("SELECT status,count(*) n FROM judge_calls GROUP BY status")}
        bad=[dict(r) for r in con.execute("SELECT prompt_sha256,status,error FROM judge_calls WHERE status!='COMMITTED'")]
        n=int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])
        return counts,bad,n
    finally:
        con.close()

def dry_run():
    m,answers,qmap=state()
    counts,bad,n=ledger_state()
    return {"cases":len(answers),"prior_ledger":counts,"bad":bad,"provider_calls":0,"gate":m["expansion_gate"]}

def execute():
    m,answers,qmap=state()
    wrapper,tools=load_tools()
    if PROG.exists():
        prog=load(PROG)
        if prog.get("schema")!="xiaoyu-stagea-answerer-v5full-judge-progress-v1":
            raise ScoreError("judge progress schema drift")
    else:
        prog={"schema":"xiaoyu-stagea-answerer-v5full-judge-progress-v1","rows":[]}
        atomic(PROG,prog)
    done={x["qa_case_id"] for x in prog["rows"]}
    if len(done)!=len(prog["rows"]):
        raise ScoreError("duplicate qid in progress")
    for ans in answers:
        qid=ans["qa_case_id"]
        if qid in done:
            continue
        counts,bad,n=ledger_state()
        if bad:
            raise ScoreError("noncommitted judge row; retry forbidden")
        if n>=51:
            raise ScoreError("judge cap exhausted")
        q=qmap[qid]
        evidence="\n".join(str(z.get("memory_content") or "") for z in q.get("evidence") or [])
        got=tools.evaluation_for_question(q["question"],q["answer"],evidence,ans["answer"])
        prog["rows"].append({
            "qa_case_id":qid,
            "variant":q["variant"],
            "system_response":ans["answer"],
            "evaluation_result":got.get("evaluation_result"),
            "judge_result":got,
        })
        atomic(PROG,prog)
        done.add(qid)

    counts,bad,n=ledger_state()
    if bad or n!=51 or counts.get("COMMITTED")!=51 or len(prog["rows"])!=51:
        raise ScoreError("final judge ledger not exactly 51 COMMITTED")
    labels={}
    for row in prog["rows"]:
        label=str(row.get("evaluation_result") or "UNKNOWN")
        labels[label]=labels.get(label,0)+1
    def vm(variant=None):
        rr=prog["rows"] if variant is None else [x for x in prog["rows"] if x["variant"]==variant]
        correct=sum(x["evaluation_result"]=="Correct" for x in rr)
        halluc=sum(x["evaluation_result"]=="Hallucination" for x in rr)
        omission=sum(x["evaluation_result"]=="Omission" for x in rr)
        return {
            "n":len(rr),"correct":correct,"omission":omission,"hallucination":halluc,
            "correct_rate":correct/len(rr) if rr else None,
            "hallucination_rate":halluc/len(rr) if rr else None,
        }
    overall=vm()
    medium=vm("m")
    long=vm("l")
    gate=m["expansion_gate"]
    semantic_reject_rate=float(gate["semantic_reject_rate_observed"])
    checks={
        "overall_correct_rate":overall["correct_rate"]>=float(gate["overall_correct_rate_min"]),
        "medium_correct_rate":medium["correct_rate"]>=float(gate["medium_correct_rate_min"]),
        "long_correct_rate":long["correct_rate"]>=float(gate["long_correct_rate_min"]),
        "hallucination_rate":overall["hallucination_rate"]<=float(gate["hallucination_rate_max"]),
        "semantic_reject_rate":semantic_reject_rate<=float(gate["semantic_reject_rate_max"]),
    }
    out={
        "schema":"xiaoyu-stagea-answerer-v5full-judge-result-v1",
        "labels":labels,
        "overall":overall,
        "medium":medium,
        "long":long,
        "semantic_reject_rate_reference":semantic_reject_rate,
        "checks":checks,
        "decision":"V5_FULL_DEV_GATE_PASS" if all(checks.values()) else "STOP_OR_REVISE",
        "rows":prog["rows"],
        "formal_confirmatory_authorized":False,
    }
    atomic(FINAL,out)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["dry_run","execute"])
    args=ap.parse_args()
    try:
        result=dry_run() if args.action=="dry_run" else execute()
        print(json.dumps({"ok":True,"result":result},ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({"ok":False,"error":type(exc).__name__+":"+str(exc)},ensure_ascii=False,indent=2))
        raise SystemExit(2)

if __name__=="__main__":
    main()
