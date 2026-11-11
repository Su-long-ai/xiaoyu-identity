#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,hashlib,importlib.machinery,importlib.util,json,sqlite3,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
RUNTIME=GOV/"stagea_answerer_dev_v5_runtime"
MANIFEST=GOV/"STAGEA_ANSWERER_V5_JUDGE_V1.json"
WRAPPER=GOV/"stagea_answerer_v5_judge_v1.py"
EVAL=GOV/"confirmatory_frozen"/"HALUMEM_OFFICIAL_EVAL_TOOLS.PY"
QA=GOV/"budget50_halumem_dev_runtime_v1"/"QA_INPUTS_POST_SEAL.json"
ANS=RUNTIME/"results.json"
PROG=RUNTIME/"judge_progress.json"
FINAL=RUNTIME/"judge_result.json"
LEDGER=RUNTIME/"judge_ledger_qwen38_flash_v5.sqlite3"
THIS=Path(__file__).resolve()

class ScoreError(RuntimeError):
    pass

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load(p):
    return json.loads(Path(p).read_text("utf-8"))

def atomic(p,obj):
    # Windows-compatible recovery: judge SQLite ledger is the durable authority.
    Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8")

def load_tools():
    if ".PY" not in importlib.machinery.SOURCE_SUFFIXES:
        importlib.machinery.SOURCE_SUFFIXES.append(".PY")
    ws=importlib.util.spec_from_file_location("llms",WRAPPER)
    w=importlib.util.module_from_spec(ws)
    sys.modules["llms"]=w
    ws.loader.exec_module(w)
    es=importlib.util.spec_from_file_location("_ansv5_eval",EVAL)
    e=importlib.util.module_from_spec(es)
    es.loader.exec_module(e)
    return w,e

def state():
    m=load(MANIFEST)
    if m.get("schema")!="xiaoyu-stagea-answerer-v5-judge-v1" or m.get("status")!="EXECUTION_AUTHORIZED":
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
    if [x["qa_case_id"] for x in answers]!=m["case_qids"]:
        raise ScoreError("case qids drift")
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
    else:
        prog={"schema":"xiaoyu-stagea-answerer-v5-judge-progress-v1","rows":[]}
        atomic(PROG,prog)
    done={x["qa_case_id"] for x in prog["rows"]}
    for ans in answers:
        qid=ans["qa_case_id"]
        if qid in done:
            continue
        counts,bad,n=ledger_state()
        if bad:
            raise ScoreError("noncommitted judge row; retry forbidden")
        if n>=10:
            raise ScoreError("judge cap exhausted")
        q=qmap[qid]
        evidence="\n".join(str(z.get("memory_content") or "") for z in q.get("evidence") or [])
        got=tools.evaluation_for_question(q["question"],q["answer"],evidence,ans["answer"])
        prog["rows"].append({
            "qa_case_id":qid,
            "variant":q["variant"],
            "selection_gold_unknown":ans["selection_gold_unknown"],
            "system_response":ans["answer"],
            "evaluation_result":got.get("evaluation_result"),
            "judge_result":got,
        })
        atomic(PROG,prog)
        done.add(qid)
    counts,bad,n=ledger_state()
    if bad or n!=10 or counts.get("COMMITTED")!=10 or len(prog["rows"])!=10:
        raise ScoreError("final judge ledger not exactly 10 COMMITTED")
    labels={}
    for row in prog["rows"]:
        label=str(row.get("evaluation_result") or "UNKNOWN")
        labels[label]=labels.get(label,0)+1
    known=[x for x in prog["rows"] if not x["selection_gold_unknown"]]
    unknown=[x for x in prog["rows"] if x["selection_gold_unknown"]]
    known_correct=sum(x["evaluation_result"]=="Correct" for x in known)
    unknown_correct=sum(x["evaluation_result"]=="Correct" for x in unknown)
    hallucination=sum(x["evaluation_result"]=="Hallucination" for x in prog["rows"])
    gate=m["expansion_gate"]
    checks={
        "known_correct_at_least":known_correct>=int(gate["known_correct_min"]),
        "unknown_controls_all_correct":unknown_correct==len(unknown)==int(gate["unknown_control_n"]),
        "hallucination_zero":hallucination==0,
    }
    out={
        "schema":"xiaoyu-stagea-answerer-v5-judge-result-v1",
        "labels":labels,
        "known_n":len(known),
        "known_correct":known_correct,
        "unknown_n":len(unknown),
        "unknown_correct":unknown_correct,
        "hallucination":hallucination,
        "checks":checks,
        "decision":"V5_GATE_PASS" if all(checks.values()) else "STOP_OR_REVISE",
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
