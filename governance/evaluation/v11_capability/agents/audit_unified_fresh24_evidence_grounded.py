# -*- coding: utf-8 -*-
from pathlib import Path
from collections import Counter,defaultdict
import collections,hashlib,json,re,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_ANSWER_CONTRACT_UNIFIED_FRESH24_20261114"
EXT=ROOT/"governance/evaluation/external_suite"
RROOT=ROOT/"external/benchmarks/rhelm"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat

TASK="M2-X342"
def load(p):return json.loads(Path(p).read_text("utf-8"))
def jl(p):
 p=Path(p);return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
def append(p,x):
 with Path(p).open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def decode(s):
 t=str(s).strip();ticks=chr(96)*3
 if t.startswith(ticks):t=t.replace(ticks+"json","").replace(ticks+"JSON","").replace(ticks,"").strip()
 i=t.find("{");j=t.rfind("}")
 if i<0 or j<i:raise ValueError("json missing")
 return json.loads(t[i:j+1])

def persona_docs(persona):
 out={}
 for p in sorted((RROOT/"conversations"/persona).glob("*.json")):
  o=json.loads(p.read_text("utf-8"));date=str(o.get("date") or "")
  for t in o.get("conversation") or []:
   sid=f"{date}:{int(t['turn'])}"
   out[sid]=f"User: {t.get('user','')}\nAssistant: {t.get('assistant','')}"
 by=collections.defaultdict(list)
 for p in sorted((RROOT/"emails"/persona).glob("*.txt")):
  m=re.search(r"(\d{4})_(\d{2})_(\d{2})",p.name)
  if m:by["-".join(m.groups())].append(p)
 for d,ps in sorted(by.items()):
  out[f"Emails_{d}"]="\n\n".join(f"### {p.name}\n"+p.read_text("utf-8",errors="replace") for p in ps)
 for p in sorted((RROOT/"attachments"/persona).glob("*")):
  if p.is_file():out[p.name]=p.read_text("utf-8",errors="replace")
 return out

def main():
 verdict=load(P/"FRESH24_STRICT_VERDICT.json")
 suite={x["case_id"]:x for x in load(P/"FRESH24_FROZEN_NO_GOLD.json")["cases"]}
 report={x["case_id"]:x for x in load(EXT/"runs/v11ext_20261113_215159_rhelm.json")["rows"]}
 gold={x["case_id"]:x for x in jl(EXT/"normalized/rhelm_cases.jsonl") if x["case_id"] in suite}
 base={x["case_id"]:x for x in jl(P/"BASELINE_ANSWERS.jsonl")}
 cand={x["case_id"]:x for x in jl(P/"CANDIDATE_ANSWERS.jsonl")}
 primary={x["case_id"]:x for x in verdict["rows"]}
 outj=P/"EVIDENCE_GROUNDED_JUDGMENTS.jsonl";done={x["case_id"]:x for x in jl(outj)}
 cfg=dict(PROVIDERS["qwen"]);cfg.update({"provider":"qwen","model":"qwen3.8-flash","temperature":0,
  "enable_thinking":False,"response_format":{"type":"json_object"},"_capture_finish_reason":True})
 cache={}
 for cid,c in suite.items():
  if cid in done:continue
  person=c["scope_id"];docs=cache.setdefault(person,persona_docs(person))
  ids=list(dict.fromkeys(report[cid].get("resolved_evidence_ids") or []))
  ev=[]
  for sid in ids:
   if sid in docs:ev.append(f"[SOURCE {sid}]\n{docs[sid]}")
  evidence="\n\n".join(ev)
  pair=[("baseline",base[cid]["answer"]),("candidate",cand[cid]["answer"])]
  if int(hashlib.sha256(("eg-audit|"+cid).encode()).hexdigest(),16)%2:pair.reverse()
  prompt=f"""Post-seal evaluation audit. The REFERENCE ANSWER is authoritative for the required answer.
COMPLETE RESOLVED RAW EVIDENCE is supplied only to check factual support and contradictions in extra details.
Do not use outside knowledge or dataset familiarity.

Rules:
- Correct iff the answer gives the substantive answer required by REFERENCE and does not contradict REFERENCE.
- Extra detail not mentioned in REFERENCE is not automatically wrong; only penalize it if RAW EVIDENCE contradicts it or it materially changes the answer.
- Cautious caveats do not make a correct direct answer wrong unless they explicitly deny a fact that REFERENCE requires.
- If REFERENCE corrects a false premise (e.g. event did not happen/person absent), the answer must communicate that correction, not merely say 'not found' when RAW EVIDENCE establishes the correction.
- For list/count/multipart questions, all reference-required content must be present.
Return JSON only:
{{"A_correct":bool,"B_correct":bool,"A_problem":"none|unsupported_extra|contradiction|missing_required|wrong_core|overhedge","B_problem":"none|unsupported_extra|contradiction|missing_required|wrong_core|overhedge","reason":"<=220 chars"}}

QUESTION:
{c["question"]}

REFERENCE ANSWER:
{gold[cid]["gold_answer"]}

COMPLETE RESOLVED RAW EVIDENCE:
{evidence if evidence else "[No resolved raw evidence IDs were supplied by benchmark metadata]"}

ANSWER A:
{pair[0][1]}

ANSWER B:
{pair[1][1]}
"""
  wire,u=cached_chat(cfg,[{"role":"system","content":"Evidence-grounded post-seal paired auditor. Strict JSON only."},
                          {"role":"user","content":prompt}],
    max_tokens=480,timeout=120,namespace="unified-f24-evidence-audit-v1",budget_scope=TASK,cache_only=False)
  o=decode(wire);mapped={}
  for lab,(arm,_) in zip(("A","B"),pair):
   mapped[arm]={"correct":bool(o[lab+"_correct"]),"problem":str(o.get(lab+"_problem") or "none")}
  item={"case_id":cid,"resolved_source_ids":ids,"resolved_evidence_chars":len(evidence),
    "baseline_correct":mapped["baseline"]["correct"],"candidate_correct":mapped["candidate"]["correct"],
    "baseline_problem":mapped["baseline"]["problem"],"candidate_problem":mapped["candidate"]["problem"],
    "reason":str(o.get("reason") or "")[:600],"finish_reason":u.get("_finish_reason")}
  append(outj,item);done[cid]=item
  print("EGAUDIT",len(done),"/24",cid,item["baseline_correct"],item["candidate_correct"],flush=True)

 comparisons=[];pb=pc=ab=ac=0
 for cid in suite:
  p=primary[cid];a=done[cid]
  pb+=int(p["baseline_correct"]);pc+=int(p["candidate_correct"])
  ab+=int(a["baseline_correct"]);ac+=int(a["candidate_correct"])
  if p["baseline_correct"]!=a["baseline_correct"] or p["candidate_correct"]!=a["candidate_correct"]:
   comparisons.append({"case_id":cid,"primary_baseline":p["baseline_correct"],
      "primary_candidate":p["candidate_correct"],"audit_baseline":a["baseline_correct"],
      "audit_candidate":a["candidate_correct"],"reason":a["reason"]})
 result={"schema":"xiaoyu-unified-fresh24-evidence-grounded-audit-v1",
  "status":"POSTSEAL_DIAGNOSTIC_PRIMARY_VERDICT_IMMUTABLE",
  "n":24,"primary":{"baseline_correct":pb,"candidate_correct":pc,"net":pc-pb},
  "audit":{"baseline_correct":ab,"candidate_correct":ac,"net":ac-ab},
  "judgment_disagreement_count":len(comparisons),"disagreements":comparisons,
  "primary_verdict_path":str(P/"FRESH24_STRICT_VERDICT.json"),
  "does_not_replace_primary":True}
 out=P/"EVIDENCE_GROUNDED_JUDGE_AUDIT.json"
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3") as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",(str(out),time.time(),TASK));db.commit()
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
