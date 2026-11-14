# -*- coding: utf-8 -*-
"""Same-full-evidence consumption A/B for answer-contract MVP.

Development diagnostic only:
- baseline = already sealed X327 DeepSeek answer with complete raw evidence;
- planner = Qwen3.8-flash non-thinking over QUESTION ONLY;
- executor = DeepSeek flash non-thinking over same complete raw evidence;
- no retrieval/source expansion/gold in generation;
- invalid contract/execution falls back to the already sealed baseline answer.
"""
from pathlib import Path
import hashlib,json,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P0=A/"results/product_integration/LEAD_HRPA_MANUAL_EVIDENCE_DIAGNOSTIC_20261114"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_MVP_V2_20261114"
B2=A/"results/product_integration/LEAD_B2_DOC_LAZY_REPLAY_20261114/fresh24d"
sys.path[:0]=[str(ROOT),str(A)]

from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat
from governance.evaluation.v11_capability.agents.answer_contract_mvp import (
    planner_messages,validate_contract,executor_messages,validate_execution,
    repair_messages,render_execution,
)
from governance.evaluation.v11_capability.agents.answer_outcome_gate import inspect_answer

def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
    p=Path(p)
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
    with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def decode(s):
    t=str(s).strip();f=chr(96)*3
    if t.startswith(f): t=t.replace(f+"json","").replace(f,"").strip()
    return json.loads(t)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def cfg_qwen():
    c=dict(PROVIDERS["qwen"]);c.update({"provider":"qwen","model":"qwen3.8-flash",
      "temperature":0,"enable_thinking":False,"response_format":{"type":"json_object"},
      "_capture_finish_reason":True});return c
def cfg_deepseek():
    c=dict(PROVIDERS["deepseek"]);c.update({"provider":"deepseek","model":"deepseek-flash",
      "temperature":0,"reasoning_effort":"none","response_format":{"type":"json_object"},
      "_capture_finish_reason":True});return c

def main():
    P.mkdir(parents=True,exist_ok=True)
    cases=load(P0/"CASE_IDS.json")["case_ids"]
    suite={x["case_id"]:x for x in load(B2/"FRESH24D_FROZEN_NO_GOLD.json")["cases"]}
    evidence={x["case_id"]:x for x in jl(P0/"MANUAL_EVIDENCE.jsonl")}
    baseline={x["case_id"]:x for x in jl(P0/"MANUAL_ANSWERS.jsonl")}
    assert len(cases)==len(evidence)==len(baseline)==16

    # Allocate or reuse one bounded paid scope for the whole mechanism.
    scope_path=P/"SCOPE.json"
    if scope_path.exists():
        scope=load(scope_path)
    else:
        with sqlite3.connect(A/"TASKS.sqlite3",timeout=30) as db:
            nums=[int(x[0][4:]) for x in db.execute("select id from tasks where id like 'M2-X%'") if x[0][4:].isdigit()]
            tid=f"M2-X{max(nums)+1:03d}"
            db.execute("""insert into tasks(id,role,track,priority,title,acceptance,inputs,status,owner,artifact,updated_at)
              values(?,?,?,?,?,?,?,?,?,?,?)""",
              (tid,"MAINLINE","M2",1,"Answer-contract MVP v2 same-full-evidence consumption A/B",
               "16 exposed dev cases; question-only contract planner + same-evidence DeepSeek executor; <=2CNY; no fresh credit",
               str(P0/"CASE_IDS.json"),"ACTIVE","xy-single-owner-20261114",str(P/"CANDIDATE_ANSWERS.jsonl"),time.time()))
            db.commit()
        scope={"schema":"xiaoyu-answer-contract-mvp16-scope-v2","task":tid,
               "max_task_cny":2,"fresh_capability_credit":False}
        scope_path.write_text(json.dumps(scope,ensure_ascii=False,indent=2)+"\n","utf-8")
    task=scope["task"]

    out=P/"CANDIDATE_ANSWERS.jsonl";done={x["case_id"]:x for x in jl(out)}
    contracts=P/"CONTRACTS.jsonl";c_done={x["case_id"]:x for x in jl(contracts)}

    for cid in cases:
        if cid in done:continue
        q=suite[cid]["question"];ev=evidence[cid]["evidence_text"];base=baseline[cid]
        fallback=None;contract=None;planner_finish=None;executor_finish=None
        raw_contract=None;raw_execution=None;checked=None;repair_used=False
        try:
            if cid in c_done:
                raw_contract=c_done[cid]["raw_contract"];contract=validate_contract(q,raw_contract)
                planner_finish=c_done[cid].get("finish_reason")
            else:
                wire,usage=cached_chat(cfg_qwen(),planner_messages(q),max_tokens=650,timeout=100,
                  namespace="answer-contract-mvp16-planner-v2",budget_scope=task,cache_only=False)
                planner_finish=usage.get("_finish_reason");raw_contract=decode(wire)
                contract=validate_contract(q,raw_contract)
                crec={"case_id":cid,"raw_contract":raw_contract,"contract":contract,
                      "finish_reason":planner_finish}
                append(contracts,crec);c_done[cid]=crec
        except Exception as exc:
            fallback="contract_invalid:"+type(exc).__name__+":"+str(exc)[:180]

        answer=base["answer"];finish=base.get("finish_reason")
        if fallback is None:
            try:
                wire,usage=cached_chat(cfg_deepseek(),executor_messages(q,ev,contract),max_tokens=1000,timeout=120,
                  namespace="answer-contract-mvp16-executor-v2",budget_scope=task,cache_only=False)
                executor_finish=usage.get("_finish_reason");raw_execution=decode(wire)
                checked=validate_execution(contract,raw_execution)
                if not checked["valid"]:
                    repair_used=True
                    wire2,usage2=cached_chat(cfg_deepseek(),repair_messages(q,ev,contract,raw_execution,checked["errors"]),
                      max_tokens=1000,timeout=120,namespace="answer-contract-mvp16-repair-v2",
                      budget_scope=task,cache_only=False)
                    executor_finish=usage2.get("_finish_reason");raw_execution=decode(wire2)
                    checked=validate_execution(contract,raw_execution)
                if not checked["valid"]:
                    fallback="execution_invalid:"+";".join(checked["errors"])[:300]
                else:
                    answer=render_execution(contract,checked);finish=executor_finish
                    if not answer.strip():fallback="render_empty"
            except Exception as exc:
                fallback="executor_exception:"+type(exc).__name__+":"+str(exc)[:180]

        if fallback:
            answer=base["answer"];finish=base.get("finish_reason")
        item={"case_id":cid,"arm":"answer_contract_mvp",
          "answer":answer,"finish_reason":finish,"integrity":inspect_answer(answer,finish),
          "fallback_to_manual_baseline":bool(fallback),"fallback_reason":fallback,
          "planner_finish_reason":planner_finish,"executor_finish_reason":executor_finish,
          "repair_used":repair_used,"contract":contract,
          "raw_execution":raw_execution,"checked_execution":checked,
          "baseline_manual_answer_sha256":hashlib.sha256(base["answer"].encode("utf-8")).hexdigest(),
          "evidence_sha256":hashlib.sha256(ev.encode("utf-8")).hexdigest()}
        append(out,item);done[cid]=item
        print("CONTRACT",len(done),"/16",cid,"fallback",bool(fallback),"repair",repair_used,flush=True)

    if len(done)!=16:raise RuntimeError("incomplete")
    seal=P/"CANDIDATE_SEAL.json"
    seal.write_text(json.dumps({"schema":"xiaoyu-answer-contract-mvp16-seal-v2","n":16,
      "answers_sha256":sha(out),"contracts_sha256":sha(contracts),
      "source_case_ids_sha256":sha(P0/"CASE_IDS.json"),
      "baseline_manual_answers_sha256":sha(P0/"MANUAL_ANSWERS.jsonl"),
      "manual_evidence_sha256":sha(P0/"MANUAL_EVIDENCE.jsonl"),
      "gold_loaded":False,"question_only_planner":True,"same_full_evidence":True,
      "answer_model":"deepseek-flash non-thinking","planner_model":"qwen3.8-flash non-thinking",
      "fresh_capability_credit":False,
      "fallback_count":sum(bool(x.get("fallback_to_manual_baseline")) for x in done.values()),
      "repair_count":sum(bool(x.get("repair_used")) for x in done.values())},
      ensure_ascii=False,indent=2)+"\n","utf-8")
    with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
        db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
                   (str(seal),time.time(),task));db.commit()
    print("SEALED",task,sha(seal),flush=True)

if __name__=="__main__":main()
