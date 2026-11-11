#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json,pathlib,re,statistics,hashlib

G=pathlib.Path(__file__).resolve().parent
V5=G/"stagea_answerer_v5_full_inputs.json"
V6=G/"stagea_answerer_v6_offline_inputs.json"
QA=G/"budget50_halumem_dev_runtime_v1"/"QA_INPUTS_POST_SEAL.json"
JR=G/"stagea_answerer_v5_full_runtime"/"judge_result.json"
OUT=G/"STAGEA_V6_OFFLINE_AUDIT.json"

STOP={"the","a","an","is","was","are","were","to","of","in","on","at","for","and","or",
      "her","his","their","she","he","they","user","speaker","susan","thompson","jennifer","martin"}
EXCLUDED={"hm-m-q-161e74a81851-6-2","hm-m-q-161e74a81851-6-4"}

def load(p): return json.loads(p.read_text("utf-8"))
def toks(s):
    return {x for x in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?",str(s).casefold())
            if len(x)>1 and x not in STOP}
def cov(ev,ctx):
    et=toks(ev)
    return len(et&toks(ctx))/len(et) if et else 0.0
def stable(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def main():
    v5=load(V5); v6=load(V6); qa=load(QA); jr=load(JR)
    m5={x["qa_case_id"]:x for x in v5["rows"]}
    m6={x["qa_case_id"]:x for x in v6["rows"]}
    qm={x["qa_case_id"]:x for x in qa["rows"]}
    jm={x["qa_case_id"]:x for x in jr["rows"]}
    rows=[]
    for qid,q in qm.items():
        ev=" ".join(str(e.get("memory_content") or "") for e in q.get("evidence") or [])
        c5=" ".join(x["text"] for x in m5[qid]["authorized_memories"])
        c6=" ".join(x["text"] for x in m6[qid]["authorized_memories"])
        a,b=cov(ev,c5),cov(ev,c6)
        ref=str(q.get("answer") or "")
        unknown=ref.strip().casefold().startswith("unknown") or "not provided" in ref.casefold()
        rows.append({
            "qid":qid,"variant":q["variant"],"question":q["question"],
            "v5":round(a,4),"v6":round(b,4),"delta":round(b-a,4),
            "v5_label":jm[qid]["evaluation_result"],
            "authority_fixable":qid not in EXCLUDED,
            "gold_unknown":unknown,
            "context_changed":m5[qid]["authorized_memories"]!=m6[qid]["authorized_memories"],
            "v6_fields":m6[qid]["retrieval_meta"].get("v6_fields"),
            "v6_cross_n":sum(x.get("channel")=="cross_history_direct_fact" for x in m6[qid]["authorized_memories"]),
        })
    fix=[x for x in rows if x["authority_fixable"] and not x["gold_unknown"]]
    fails=[x for x in fix if x["v5_label"]!="Correct"]
    unknowns=[x for x in rows if x["gold_unknown"]]
    checks={
        "case_count_51":len(rows)==51,
        "context_cap":all(len(x["authorized_memories"])<=20 for x in m6.values()),
        "authority_only":all(
            mm.get("authority") in {"user_state","user_history","user_source_history"}
            for x in m6.values() for mm in x["authorized_memories"]
        ),
        "request_hashes":all(stable(x["messages"])==x["request_messages_sha256"] for x in m6.values()),
        "unknown_context_unchanged":all(not x["context_changed"] for x in unknowns),
        "no_unknown_cross_history":all(x["v6_cross_n"]==0 for x in unknowns),
    }
    out={
        "schema":"xiaoyu-stagea-v6-offline-audit-v2",
        "input_sha256":hashlib.sha256(V6.read_bytes()).hexdigest(),
        "checks":checks,
        "pass":all(checks.values()),
        "all51":{
            "mean_v5":statistics.mean(x["v5"] for x in rows),
            "mean_v6":statistics.mean(x["v6"] for x in rows),
            "improved":sum(x["delta"]>0 for x in rows),
            "worse":sum(x["delta"]<0 for x in rows),
            "same":sum(x["delta"]==0 for x in rows),
        },
        "authority_fixable_known":{
            "n":len(fix),"mean_v5":statistics.mean(x["v5"] for x in fix),
            "mean_v6":statistics.mean(x["v6"] for x in fix),
            "improved":sum(x["delta"]>0 for x in fix),
            "worse":sum(x["delta"]<0 for x in fix),
        },
        "v5_fail_fixable_known":{
            "n":len(fails),"mean_v5":statistics.mean(x["v5"] for x in fails),
            "mean_v6":statistics.mean(x["v6"] for x in fails),
            "improved":sum(x["delta"]>0 for x in fails),
            "worse":sum(x["delta"]<0 for x in fails),
        },
        "gold_unknown_safety":{
            "n":len(unknowns),
            "context_changed":sum(x["context_changed"] for x in unknowns),
            "cross_history_added":sum(x["v6_cross_n"]>0 for x in unknowns),
        },
        "failure_rows":sorted(fails,key=lambda x:x["delta"],reverse=True),
        "top_improvements":sorted(rows,key=lambda x:x["delta"],reverse=True)[:15],
        "top_regressions":sorted(rows,key=lambda x:x["delta"])[:10],
        "provider_calls":0,
        "formal_confirmatory_authorized":False,
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:v for k,v in out.items() if k not in ("failure_rows","top_improvements","top_regressions")},ensure_ascii=False,indent=2))
    print("TOP_IMPROVEMENTS",json.dumps(out["top_improvements"][:10],ensure_ascii=False))
    print("TOP_REGRESSIONS",json.dumps(out["top_regressions"][:8],ensure_ascii=False))
    raise SystemExit(0 if out["pass"] else 2)

if __name__=="__main__": main()
