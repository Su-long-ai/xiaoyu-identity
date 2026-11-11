#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exact official HaluMem scorer for a sealed formal V5 answer overlay."""
from __future__ import annotations
import argparse,copy,hashlib,importlib.util,json,os,shutil,sqlite3,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance";FROZEN=GOV/"confirmatory_frozen";CAND=GOV/"confirmatory_recovery_candidate"
RUNTIME=GOV/"halumem_confirmatory_runtime_v2"
PROTOCOL=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_V1.json"
PROTOCOL_FREEZE=GOV/"FORMAL_HALUMEM_V5_OVERLAY_PROTOCOL_FREEZE_V1.json"
INPUT_SEAL=RUNTIME/"V5_ANSWER_OVERLAY_INPUT_SEAL.json"
ANSWER_SEAL=RUNTIME/"V5_ANSWER_OVERLAY_RESULT_SEAL.json"
CAL_RESULT=RUNTIME/"V5_JUDGE_CALIBRATION_RESULT.json"
GOLD_FREEZE=GOV/"FORMAL_HALUMEM_V5_GOLD_SCORING_FREEZE.json"
JUDGE_LEDGER=RUNTIME/"v5_judge_ledger_qwen38_flash.sqlite3"
OUTPUT=RUNTIME/"HALUMEM_CONFIRMATORY_V5_OVERLAY_SCORE.json"
LEDGER=GOV/"research_api_usage.sqlite3"
RECOVERY_PATH=CAND/"HALUMEM_CONFIRMATORY_RUNNER_V2.py"
OFFICIAL_EVAL=FROZEN/"HALUMEM_OFFICIAL_EVALUATION.PY"
OFFICIAL_TOOLS=FROZEN/"HALUMEM_OFFICIAL_EVAL_TOOLS.PY"
JUDGE_WRAPPER=GOV/"formal_v5_judge_ledger.py"
CAL_SPEC=FROZEN/"HALUMEM_JUDGE_CALIBRATION_V1.json"
JUDGE_BINDING=FROZEN/"HALUMEM_JUDGE_BINDING.json"

class ScoreError(RuntimeError):pass
_REC=None
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))
def atomic(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name(p.name+".tmp")
    q.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8");q.replace(p)

def protocol_candidate():
    p=load(PROTOCOL)
    if p.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-v1" or p.get("status")!="PREFROZEN_FOR_INDEPENDENT_REVIEW":
        raise ScoreError("protocol candidate schema/status drift")
    impl=p.get("implementation") or {}
    if sha(Path(__file__))!=impl.get("scorer_overlay_sha256"):raise ScoreError("scorer overlay byte drift")
    for name,b in (p.get("bindings") or {}).items():
        fp=ROOT/str(b.get("path") or "")
        if not fp.is_file() or sha(fp)!=b.get("sha256") or fp.stat().st_size!=int(b.get("bytes") or -1):
            raise ScoreError("protocol bound byte drift: "+str(name))
    return p

def protocol():
    p=protocol_candidate()
    if not PROTOCOL_FREEZE.is_file():raise ScoreError("protocol independent freeze missing")
    f=load(PROTOCOL_FREEZE)
    if f.get("schema")!="xiaoyu-formal-halumem-v5-overlay-protocol-freeze-v1" or f.get("status")!="PROTOCOL_EXECUTION_READY" or f.get("protocol_sha256")!=sha(PROTOCOL):
        raise ScoreError("protocol independent freeze drift")
    return p,f

def recovery():
    global _REC
    if _REC is not None:return _REC
    p,_=protocol()
    if sha(RECOVERY_PATH)!=(p.get("bindings") or {}).get("recovery_runner",{}).get("sha256"):
        raise ScoreError("Recovery-V2 runner binding drift")
    for x in (str(CAND),str(FROZEN),str(GOV),str(ROOT)):
        if x not in sys.path:sys.path.insert(0,x)
    spec=importlib.util.spec_from_file_location("_xiaoyu_v5_recovery",RECOVERY_PATH)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    _REC=mod;return mod

def validate_prediction_seal():
    rec=recovery();m=rec.require_execution_manifest()
    return rec._validate_prediction_seal(m)

def input_material():
    if not INPUT_SEAL.is_file():raise ScoreError("V5 input seal missing")
    s=load(INPUT_SEAL)
    if s.get("schema")!="xiaoyu-formal-v5-answer-overlay-input-seal-v1" or s.get("sealed") is not True:
        raise ScoreError("V5 input seal invalid")
    if int(s.get("question_count") or 0)!=6282 or int(s.get("stream_count") or 0)!=36 or int(s.get("gold_fields_materialized") or 0)!=0:
        raise ScoreError("V5 input seal cardinality/gold drift")
    if s.get("prediction_seal_sha256")!=sha(recovery().base.SEAL) or s.get("overlay_candidate_sha256")!=sha(GOV/"formal_v5_answer_overlay_candidate.py"):
        raise ScoreError("V5 input seal prediction/overlay drift")
    streams={}
    ids=set()
    for spec in s.get("files") or []:
        fp=GOV/spec["path"]
        if not fp.is_file() or sha(fp)!=spec["sha256"]:raise ScoreError("V5 input stream byte drift")
        obj=load(fp)
        if obj.get("schema")!="xiaoyu-formal-v5-answer-overlay-input-stream-v1" or int(obj.get("gold_fields_materialized") or 0)!=0:
            raise ScoreError("V5 input stream schema/gold drift")
        key=(spec["variant"],spec["uuid_hash"])
        if key in streams:raise ScoreError("V5 input duplicate stream")
        rows=obj.get("rows") or []
        if len(rows)!=int(spec["question_count"]):raise ScoreError("V5 input stream cardinality drift")
        for x in rows:
            cid=str(x["case_id"])
            if cid in ids:raise ScoreError("V5 input duplicate case")
            ids.add(cid)
            raw=json.dumps(x["messages"],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
            if hashlib.sha256(raw).hexdigest()!=x["request_messages_sha256"]:raise ScoreError("V5 input request hash drift")
        streams[key]={"spec":spec,"obj":obj}
    if len(streams)!=36 or len(ids)!=6282:raise ScoreError("V5 input total membership drift")
    return s,streams

def durable_answer(cid,scope):
    con=sqlite3.connect(LEDGER);con.row_factory=sqlite3.Row
    try:r=con.execute("SELECT * FROM calls WHERE case_id=? ORDER BY created_at DESC LIMIT 1",(cid,)).fetchone()
    finally:con.close()
    if r is None:raise ScoreError("V5 answer durable row missing: "+cid)
    d=dict(r)
    if d.get("status")!="COMMITTED" or d.get("budget_scope")!=scope:raise ScoreError("V5 answer durable status/scope drift")
    text=d.get("response_text")
    if not isinstance(text,str) or hashlib.sha256(text.encode()).hexdigest()!=d.get("response_sha256"):
        raise ScoreError("V5 answer durable response hash drift")
    try:o=json.loads(text)
    except Exception as exc:raise ScoreError("V5 answer durable JSON invalid") from exc
    if not isinstance(o,dict) or set(o)!={"answer"} or not isinstance(o["answer"],str):raise ScoreError("V5 answer durable format drift")
    return d," ".join(o["answer"].strip().split())

def answer_map():
    p,_=protocol();validate_prediction_seal();inp,istreams=input_material()
    if not ANSWER_SEAL.is_file():raise ScoreError("V5 answer result seal required")
    s=load(ANSWER_SEAL)
    if s.get("schema")!="xiaoyu-formal-v5-answer-overlay-result-seal-v1" or s.get("sealed") is not True:
        raise ScoreError("V5 answer result seal invalid")
    required={
      "protocol_sha256":sha(PROTOCOL),"input_seal_sha256":sha(INPUT_SEAL),
      "question_count":6282,"stream_count":36,"gold_fields_materialized":0,
    }
    for k,v in required.items():
        if s.get(k)!=v:raise ScoreError("V5 answer result seal binding drift: "+k)
    ef=GOV/"FORMAL_HALUMEM_V5_ANSWER_EXECUTION_FREEZE.json"
    if not ef.is_file() or s.get("execution_freeze_sha256")!=sha(ef):raise ScoreError("V5 answer execution-freeze binding drift")
    execf=load(ef)
    if execf.get("protocol_sha256")!=sha(PROTOCOL) or execf.get("input_seal_sha256")!=sha(INPUT_SEAL):
        raise ScoreError("V5 execution freeze binding drift")
    if float(s.get("sealed_at_epoch") or 0)<=0:raise ScoreError("V5 answer seal lacks time")
    result_streams={}
    for spec in s.get("files") or []:
        fp=GOV/spec["path"]
        if not fp.is_file() or sha(fp)!=spec["sha256"]:raise ScoreError("V5 answer result stream byte drift")
        obj=load(fp)
        if obj.get("schema")!="xiaoyu-formal-v5-answer-overlay-stream-result-v1":raise ScoreError("V5 answer result stream schema drift")
        key=(spec["variant"],spec["uuid_hash"])
        if key in result_streams:raise ScoreError("V5 answer duplicate result stream")
        result_streams[key]={"spec":spec,"obj":obj}
    if set(result_streams)!=set(istreams):raise ScoreError("V5 answer/input stream membership drift")
    amap={};scope=p["answer_track"]["scope"]
    for key,iv in istreams.items():
        rv=result_streams[key];irows=iv["obj"]["rows"];rrows=rv["obj"].get("rows") or []
        if rv["obj"].get("input_stream_sha256")!=iv["spec"]["sha256"] or len(rrows)!=len(irows):
            raise ScoreError("V5 result/input stream binding drift")
        for x,y in zip(irows,rrows):
            fields=("case_id","variant","uuid_hash","session_index","question_index")
            if any(y.get(f)!=x.get(f) for f in fields):raise ScoreError("V5 result/input row location drift")
            qsha=hashlib.sha256(str(x["question"]).encode()).hexdigest()
            if y.get("question_sha256")!=qsha:raise ScoreError("V5 result question binding drift")
            d,ans=durable_answer(str(x["case_id"]),scope)
            if y.get("call_id")!=d.get("call_id") or y.get("response_sha256")!=d.get("response_sha256") or y.get("answer")!=ans:
                raise ScoreError("V5 result durable receipt drift")
            loc=(str(x["variant"]),str(x["uuid_hash"]),int(x["session_index"]),int(x["question_index"]))
            if loc in amap:raise ScoreError("V5 answer duplicate location")
            amap[loc]={"answer":ans,"question_sha256":qsha,"case_id":x["case_id"]}
    if len(amap)!=6282:raise ScoreError("V5 answer membership !=6282")
    return s,amap

def make_bundle(name):
    p,_=protocol()
    pairs=[(OFFICIAL_EVAL,"evaluation.py"),(OFFICIAL_TOOLS,"eval_tools.py"),(JUDGE_WRAPPER,"llms.py")]
    b=RUNTIME/"scorer_bundles"/name;b.mkdir(parents=True,exist_ok=True)
    expected={"official_evaluation":sha(OFFICIAL_EVAL),"official_eval_tools":sha(OFFICIAL_TOOLS),"judge_wrapper":sha(JUDGE_WRAPPER)}
    if expected["official_evaluation"]!=(p["bindings"]["official_evaluation"]["sha256"]) or expected["official_eval_tools"]!=(p["bindings"]["official_eval_tools"]["sha256"]) or expected["judge_wrapper"]!=(p["implementation"]["judge_wrapper_sha256"]):
        raise ScoreError("scorer bundle source binding drift")
    for src,dstname in pairs:
        dst=b/dstname;shutil.copyfile(src,dst)
        if sha(src)!=sha(dst):raise ScoreError("scorer bundle copy drift")
    return b

def judge_receipt(prompt_sha,answer_sha):
    if not JUDGE_LEDGER.is_file():raise ScoreError("V5 judge ledger missing")
    con=sqlite3.connect(JUDGE_LEDGER);con.row_factory=sqlite3.Row
    try:r=con.execute("SELECT * FROM judge_calls WHERE prompt_sha256=?",(prompt_sha,)).fetchone()
    finally:con.close()
    if r is None:raise ScoreError("V5 judge receipt missing")
    d=dict(r)
    if d.get("status")!="COMMITTED" or d.get("model")!="qwen3.8-flash" or d.get("binding_sha256")!=sha(JUDGE_BINDING) or d.get("protocol_sha256")!=sha(PROTOCOL) or d.get("answer_seal_sha256")!=answer_sha:
        raise ScoreError("V5 judge receipt binding drift")
    raw=str(d.get("response_json") or "");json.loads(raw)
    return {"prompt_sha256":prompt_sha,"binding_sha256":d["binding_sha256"],"model":d["model"],
      "protocol_sha256":d["protocol_sha256"],"answer_seal_sha256":d["answer_seal_sha256"],
      "response_json_sha256":hashlib.sha256(raw.encode()).hexdigest(),"created_at":float(d["created_at"])}

def load_eval_tools(bundle):
    old=list(sys.path);sys.path.insert(0,str(bundle))
    for n in ("llms","eval_tools"):sys.modules.pop(n,None)
    captured=[]
    try:
        ls=importlib.util.spec_from_file_location("llms",bundle/"llms.py");lm=importlib.util.module_from_spec(ls);sys.modules["llms"]=lm;ls.loader.exec_module(lm)
        orig=lm.llm_request_for_json
        def capture(prompt):
            captured.append(hashlib.sha256(str(prompt).encode()).hexdigest());return orig(prompt)
        lm.llm_request_for_json=capture
        es=importlib.util.spec_from_file_location("eval_tools",bundle/"eval_tools.py");em=importlib.util.module_from_spec(es);es.loader.exec_module(em)
        return em,captured
    finally:sys.path[:]=old

def validate_calibration():
    answer,_=answer_map();asha=sha(ANSWER_SEAL)
    if not CAL_RESULT.is_file():raise ScoreError("V5 fresh calibration missing")
    cal=load(CAL_SPEC);old=load(CAL_RESULT)
    required={"schema":"xiaoyu-formal-v5-judge-calibration-result-v1","binding_sha256":sha(JUDGE_BINDING),
      "calibration_sha256":sha(CAL_SPEC),"prediction_seal_sha256":sha(recovery().base.SEAL),
      "answer_seal_sha256":asha,"protocol_sha256":sha(PROTOCOL),"judge_wrapper_sha256":sha(JUDGE_WRAPPER),
      "passed":12,"total":12,"required":12}
    for k,v in required.items():
        if old.get(k)!=v:raise ScoreError("V5 calibration binding drift: "+k)
    if float(old.get("calibrated_at_epoch") or 0)<float(answer.get("sealed_at_epoch") or 0):
        raise ScoreError("V5 calibration is not post-answer-seal")
    rows=old.get("rows") or [];receipts=old.get("judge_receipts") or [];cases=cal.get("cases") or []
    if len(rows)!=12 or len(receipts)!=12 or [x.get("id") for x in rows]!=[x.get("id") for x in cases]:raise ScoreError("V5 calibration cardinality/order drift")
    for row,case in zip(rows,cases):
        if row.get("metric")!=case.get("metric") or row.get("expected")!=case.get("expected") or row.get("ok") is not True:raise ScoreError("V5 calibration row drift")
        got=row.get("got")
        if not isinstance(got,dict) or not all(str(got.get(k))==str(v) for k,v in case["expected"].items()):raise ScoreError("V5 calibration expected mismatch")
    for receipt in receipts:
        if judge_receipt(receipt["prompt_sha256"],asha)!=receipt:raise ScoreError("V5 calibration durable receipt drift")
    return old

def judge_calibration():
    answer,_=answer_map();asha=sha(ANSWER_SEAL)
    if CAL_RESULT.is_file():return validate_calibration()
    cal=load(CAL_SPEC);bundle=make_bundle("v5-calibration-"+asha[:12]);tools,captured=load_eval_tools(bundle)
    rows=[];receipts=[];passed=0
    for case in cal.get("cases") or []:
        metric=case["metric"];x=case["input"];expected=case["expected"]
        if metric=="memory_integrity":got=tools.evaluation_for_memory_integrity(x["memories"],x["expected_memory_point"])
        elif metric=="memory_accuracy":got=tools.evaluation_for_memory_accuracy(x["dialogue"],x["golden_memories"],x["candidate_memory"])
        elif metric=="memory_update":got=tools.evaluation_for_update_memory(x["memories"],x["updated_memory"],x["original_memory"])
        elif metric=="question_answering":got=tools.evaluation_for_question(x["question"],x["reference_answer"],x["key_memory_points"],x["response"])
        else:raise ScoreError("unknown calibration metric")
        ok=all(str(got.get(k))==str(v) for k,v in expected.items())
        if len(captured)!=len(rows)+1:raise ScoreError("calibration prompt capture drift")
        receipts.append(judge_receipt(captured[-1],asha));passed+=int(ok)
        rows.append({"id":case["id"],"metric":metric,"ok":ok,"expected":expected,"got":got})
    out={"schema":"xiaoyu-formal-v5-judge-calibration-result-v1","binding_sha256":sha(JUDGE_BINDING),
      "calibration_sha256":sha(CAL_SPEC),"prediction_seal_sha256":sha(recovery().base.SEAL),
      "answer_seal_sha256":asha,"protocol_sha256":sha(PROTOCOL),"judge_wrapper_sha256":sha(JUDGE_WRAPPER),
      "passed":passed,"total":len(rows),"required":12,"calibrated_at_epoch":time.time(),"rows":rows,"judge_receipts":receipts}
    atomic(CAL_RESULT,out)
    if passed!=12 or len(rows)!=12:raise ScoreError("V5 judge calibration failed")
    return validate_calibration()

def gold_freeze():
    p,_=protocol();answer,_=answer_map();cal=validate_calibration()
    if not GOLD_FREEZE.is_file():raise ScoreError("independent gold-scoring freeze missing")
    f=load(GOLD_FREEZE)
    req={"schema":"xiaoyu-formal-halumem-v5-gold-scoring-freeze-v1","status":"GOLD_SCORING_AUTHORIZED",
      "protocol_sha256":sha(PROTOCOL),"prediction_seal_sha256":sha(recovery().base.SEAL),
      "answer_seal_sha256":sha(ANSWER_SEAL),"calibration_result_sha256":sha(CAL_RESULT)}
    for k,v in req.items():
        if f.get(k)!=v:raise ScoreError("gold-scoring freeze drift: "+k)
    return f

def overlay_prediction(variant,pred,answers):
    out=copy.deepcopy(pred);uh=str(pred["uuid_hash"]);count=0
    for si,s in enumerate(out.get("sessions") or []):
        if int(s.get("session_index"))!=si:raise ScoreError("prediction session index drift")
        for qi,q in enumerate(s.get("questions") or []):
            a=answers.get((variant,uh,si,qi))
            if a is None:raise ScoreError("missing V5 answer location")
            if hashlib.sha256(str(q.get("question") or "").encode()).hexdigest()!=a["question_sha256"]:raise ScoreError("V5 answer question drift")
            q["system_response"]=a["answer"];count+=1
    return out,count

def run_variant(variant,source,selected,answers):
    asha=sha(ANSWER_SEAL);csha=sha(CAL_RESULT)
    bundle=make_bundle("score-v5-"+asha[:12]+"-"+csha[:12]+"-"+variant)
    result_dir=bundle/"results"/("memzero-xiaoyu-"+("medium" if variant=="m" else "long"));result_dir.mkdir(parents=True,exist_ok=True)
    inputp=result_dir/"memzero_eval_results.jsonl";rows=[];qcount=0
    rec=recovery()
    for row in rec.base._load_full_selected(source,selected):
        uh=hashlib.sha256(str(row["uuid"]).encode()).hexdigest();pred=load(rec.base.prediction_path(variant,uh));over,n=overlay_prediction(variant,pred,answers);qcount+=n
        rows.append(rec.base._enriched_user(variant,row,over))
    if len(rows)!=18 or qcount!=3141:raise ScoreError("official scorer variant cardinality drift")
    raw="".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in rows);ish=hashlib.sha256(raw.encode()).hexdigest()
    marker=result_dir/"INPUT_BINDING_V5.json";expected={"input_sha256":ish,"prediction_seal_sha256":sha(rec.base.SEAL),"answer_seal_sha256":asha,"calibration_sha256":csha,"protocol_sha256":sha(PROTOCOL),"variant":variant,"question_count":qcount}
    if marker.is_file() and load(marker)!=expected:raise ScoreError("official scorer input binding drift")
    inputp.write_text(raw,"utf-8");atomic(marker,expected)
    outp=result_dir/"memzero_eval_stat_result.json"
    if outp.exists():outp.unlink()
    launcher=bundle/"run_exact_official_v5.py";launcher.write_text("import evaluation\n"+f"evaluation.main('memzero','xiaoyu-{'medium' if variant=='m' else 'long'}',user_num=18,max_workers=1)\n","utf-8")
    env=dict(os.environ);env["XIAOYU_PROJECT_ROOT"]=str(ROOT)
    cp=subprocess.run([sys.executable,str(launcher)],cwd=bundle,env=env,text=True)
    if cp.returncode!=0 or not outp.is_file():raise ScoreError("official scorer failed/missing result")
    con=sqlite3.connect(JUDGE_LEDGER)
    try:bad=con.execute("SELECT status,count(*) FROM judge_calls WHERE status!='COMMITTED' GROUP BY status").fetchall()
    finally:con.close()
    if bad:raise ScoreError("V5 judge ledger has non-COMMITTED outcomes: "+repr(bad))
    return {"variant":variant,"question_count":qcount,"input_sha256":ish,"result_path":str(outp.relative_to(GOV)).replace("\\","/"),"result_sha256":sha(outp),"result":load(outp)}

def gold_scoring():
    gold_freeze();_answer,answers=answer_map();cal=validate_calibration();rec=recovery()
    split=rec.base.split_config();selected=set(split["uuids"])
    medium=run_variant("m",rec.base.MEDIUM,selected,answers);long=run_variant("l",rec.base.LONG,selected,answers)
    out={"schema":"xiaoyu-halumem-confirmatory-v5-overlay-score-v1","stage":"gold_scoring",
      "protocol_sha256":sha(PROTOCOL),"prediction_seal_sha256":sha(rec.base.SEAL),
      "answer_overlay_seal_sha256":sha(ANSWER_SEAL),"judge_calibration_sha256":sha(CAL_RESULT),
      "gold_scoring_freeze_sha256":sha(GOLD_FREEZE),"official_evaluation_sha256":sha(OFFICIAL_EVAL),
      "official_eval_tools_sha256":sha(OFFICIAL_TOOLS),"medium":medium,"long":long,"official_metric":True,"e2_claim_allowed":False}
    atomic(OUTPUT,out);return out

def preflight():
    p=protocol_candidate()
    return {"schema":"xiaoyu-formal-v5-scorer-preflight-v2","candidate_status":p["status"],
      "protocol_freeze_exists":PROTOCOL_FREEZE.is_file(),"prediction_seal_exists":(RUNTIME/"PREDICTION_SEAL.json").is_file(),
      "answer_result_seal_exists":ANSWER_SEAL.is_file(),"v5_calibration_exists":CAL_RESULT.is_file(),
      "gold_scoring_freeze_exists":GOLD_FREEZE.is_file(),"gold_reads":0,"judge_calls":0}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("action",nargs="?",default="preflight",choices=["preflight","judge_calibration","gold_scoring"]);a=ap.parse_args()
    try:out=preflight() if a.action=="preflight" else judge_calibration() if a.action=="judge_calibration" else gold_scoring()
    except Exception as exc:
        print(json.dumps({"ok":False,"action":a.action,"error":type(exc).__name__+":"+str(exc)},ensure_ascii=False,indent=2));raise SystemExit(2)
    print(json.dumps({"ok":True,"action":a.action,"result":out},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
