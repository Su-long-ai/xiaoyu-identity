# -*- coding: utf-8 -*-
from pathlib import Path
import json,hashlib,sqlite3,sys,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
P=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_FRESH24_20261114"
TASK="M2-X365"
sys.path[:0]=[str(ROOT),str(A)]
from model_adapter import PROVIDERS
from governance.evaluation.v11_capability.agents.api_efficiency import cached_chat

def load(p):return json.loads(Path(p).read_text("utf-8"))
def decode(s):
 t=str(s).strip();ticks=chr(96)*3
 if t.startswith(ticks):
  t=t.replace(ticks+"json","").replace(ticks+"JSON","").replace(ticks,"").strip()
 i=t.find("{");j=t.rfind("}")
 return json.loads(t[i:j+1])

def main():
 v=load(P/"FRESH24_PRODUCT_VERDICT.json")
 changed=[r for r in v["rows"] if r["off_correct"]!=r["on_correct"]]
 if len(changed)!=5:raise RuntimeError("changed_case_count:"+str(len(changed)))
 cases=[]
 for r in changed:
  equal=(r["off_answer"]==r["on_answer"])
  cases.append({
    "case_id":r["case_id"],"question":r["question"],"reference":r["reference"],
    "off_answer":r["off_answer"],"on_answer":r["on_answer"],
    "byte_equal":equal,
  })
 prompt="""You are auditing only five paired answer judgments.
The REFERENCE ANSWER is authoritative. Use no outside knowledge, benchmark familiarity, hidden context, or retrieval labels.

Rules:
1. If OFF and ON are byte-identical, they MUST receive the same correctness.
2. Extra detail does not make an otherwise reference-correct answer wrong unless that extra detail contradicts the reference/question or introduces a material false claim.
3. If the reference requires refusal/correction because of a material personal constraint, an answer that first performs the unsafe/inappropriate requested action and only later adds a caveat is FALSE.
4. Wrong date/person/count/entity is FALSE even if some related facts are right.
5. Saying unknown when the reference supplies a definite answer is FALSE.
6. Evaluate semantic substance, not wording.

Return one JSON object:
{"cases":[{"case_id":"...","off_correct":bool,"on_correct":bool,
"reason":"<=180 chars"}]}

CASES:
"""+json.dumps(cases,ensure_ascii=False,indent=2)
 cfg=dict(PROVIDERS["qwen"]);cfg.update({
   "provider":"qwen","model":"qwen3.8-flash","temperature":0,
   "enable_thinking":False,"response_format":{"type":"json_object"},
   "_capture_finish_reason":True})
 wire,u=cached_chat(cfg,[
   {"role":"system","content":"Strict reference-only audit. JSON only."},
   {"role":"user","content":prompt}],
   max_tokens=1200,timeout=120,namespace="x360-changed-case-audit-v1",
   budget_scope=TASK,cache_only=False)
 obj=decode(wire)
 got={x["case_id"]:x for x in obj.get("cases") or []}
 if set(got)!={x["case_id"] for x in cases}:raise RuntimeError("audit_coverage")
 # Deterministic equality invariant always overrides judge asymmetry.
 for c in cases:
  if c["byte_equal"]:
   x=got[c["case_id"]]
   if bool(x["off_correct"])!=bool(x["on_correct"]):
    x["on_correct"]=bool(x["off_correct"])
    x["reason"]="Byte-identical OFF/ON: deterministic pair invariant forces identical correctness. "+str(x.get("reason") or "")[:100]

 original={r["case_id"]:r for r in v["rows"]}
 audit_rows=[]
 for c in cases:
  x=got[c["case_id"]]
  audit_rows.append({
    "case_id":c["case_id"],"byte_equal":c["byte_equal"],
    "original_off_correct":original[c["case_id"]]["off_correct"],
    "original_on_correct":original[c["case_id"]]["on_correct"],
    "audited_off_correct":bool(x["off_correct"]),
    "audited_on_correct":bool(x["on_correct"]),
    "reason":str(x.get("reason") or "")[:500],
  })

 # Rebuild aggregate using audited decisions only for the five changed cases.
 rows=[]
 for r in v["rows"]:
  nr=dict(r)
  if r["case_id"] in got:
   x=got[r["case_id"]]
   nr["off_correct"]=bool(x["off_correct"])
   nr["on_correct"]=bool(x["on_correct"])
   nr["changed_case_audit_reason"]=str(x.get("reason") or "")[:500]
  rows.append(nr)
 wins=sum(r["on_correct"] and not r["off_correct"] for r in rows)
 losses=sum(r["off_correct"] and not r["on_correct"] for r in rows)
 both=sum(r["off_correct"] and r["on_correct"] for r in rows)
 neither=len(rows)-wins-losses-both
 result={
  "schema":"xiaoyu-x360-changed-case-audit-v1",
  "status":"POST_GOLD_JUDGMENT_AUDIT_NO_CANDIDATE_CHANGES",
  "n_changed":len(cases),"audit_rows":audit_rows,
  "audited_off_correct":both+losses,"audited_on_correct":both+wins,
  "audited_wins":wins,"audited_losses":losses,
  "audited_net_final_correct":wins-losses,
  "audited_both_correct":both,"audited_both_wrong":neither,
  "original_verdict_sha256":hashlib.sha256(
      (P/"FRESH24_PRODUCT_VERDICT.json").read_bytes()).hexdigest(),
  "judge_finish_reason":u.get("_finish_reason"),
  "candidate_bytes_unchanged":True,"predictions_unchanged":True,
 }
 out=P/"CHANGED_CASE_AUDIT.json"
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 with sqlite3.connect(A/"TASKS.sqlite3",timeout=15) as db:
  db.execute("update tasks set status='DONE',artifact=?,updated_at=? where id=?",
    (str(out),time.time(),TASK));db.commit()
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
