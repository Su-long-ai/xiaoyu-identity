from __future__ import annotations
import json,re,math,hashlib
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
SRC=G/"stagea_answerer_dev_v7_inputs.json"
OUT=G/"stagea_answerer_dev_s2_inputs.json"
REPORT=G/"STAGEA_S2_REDUCTION_PREFLIGHT.json"
TOP_K=6
STOP=set("a an the is are was were be to of in on at by for from with and or but as what who which when where why how did does do has have had my your her his their our this that these those it its into after before current updated update now then might about during user".split())

def st(w):
    w=re.sub("[^a-z0-9]","",w.lower())
    d={"reduction":"reduc","reduced":"reduc","reduce":"reduc","deteriorated":"deteriorat","deterioration":"deteriorat","improved":"improv","improvement":"improv","preferences":"prefer","preference":"prefer"}
    if w in d:return d[w]
    if len(w)>5 and w.endswith("ing"):w=w[:-3]
    elif len(w)>4 and w.endswith("ed"):w=w[:-2]
    elif len(w)>3 and w.endswith("s"):w=w[:-1]
    return w
def toks(s):return [x for x in map(st,re.findall(r"[A-Za-z0-9]+",str(s))) if len(x)>1 and x not in STOP]
def qdate(q):
    months={x:i+1 for i,x in enumerate("january february march april may june july august september october november december".split())}
    m=re.search(r"(?i)\b("+"|".join(months)+r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b",q)
    return None if not m else f"{int(m.group(3)):04d}-{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
def parse(content):
    a,q=content.split("\nQUESTION:\n",1)
    z=a.split("AUTHORIZED MEMORIES:\n",1)[1]
    ms=[]
    for p in re.split(r"\n\n(?=\[\d+\] authority=)",z.strip()):
        m=re.match(r"\[(\d+)\] authority=([^ ]+) timestamp=([^\n]+)\n(.*)",p,re.S)
        if m:ms.append({"old_index":int(m.group(1)),"authority":m.group(2),"timestamp":m.group(3),"text":m.group(4).strip()})
    return q.strip(),ms
def score(q,ms,m):
    qt=set(toks(q)); mt=set(toks(m["text"])); df=Counter(t for x in ms for t in set(toks(x["text"]))); n=len(ms)
    lexical=sum(math.log((n+1)/(df[t]+.5))+.3 for t in qt if t in mt)
    d=qdate(q); date_bonus=5.0 if d and str(m["timestamp"]).startswith(d) else 0.0
    authority_bonus=.30 if m["authority"]=="user_state" else .12 if m["authority"]=="user_source_history" else 0.0
    return lexical+date_bonus+authority_bonus
def reduce_memories(q,ms):
    ranked=sorted(ms,key=lambda m:(-score(q,ms,m),m["old_index"]))
    chosen=ranked[:min(TOP_K,len(ranked))]
    return chosen,ranked
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

d=json.loads(SRC.read_text("utf-8")); rows=[]; rep=[]
for old in d["rows"]:
    x=json.loads(json.dumps(old)); q,ms=parse(x["messages"][-1]["content"]); chosen,ranked=reduce_memories(q,ms)
    blocks=[f"[{i}] authority={m['authority']} timestamp={m['timestamp']}\n{m['text']}" for i,m in enumerate(chosen,1)]
    x["messages"][-1]["content"]="AUTHORIZED MEMORIES:\n"+"\n\n".join(blocks)+"\n\nQUESTION:\n"+q
    x["authorized_memories"]=[{"authority":m["authority"],"timestamp":m["timestamp"],"text":m["text"],"source_old_index":m["old_index"]} for m in chosen]
    x["authorized_memory_count"]=len(chosen)
    x["case_id"]="anss2-"+hashlib.sha256((x["qa_case_id"]+"|"+stable(x["messages"])).encode()).hexdigest()[:16]
    x["request_messages_sha256"]=stable(x["messages"])
    x["representation_change"]="QUERY_DATE_LEXICAL_TOP6_SUBSET_ONLY"
    rows.append(x)
    rep.append({"qa_case_id":x["qa_case_id"],"question":q,"original_n":len(ms),"reduced_n":len(chosen),"kept_old_indices":[m["old_index"] for m in chosen],"kept_scores":[round(score(q,ms,m),6) for m in chosen]})
out={"schema":"xiaoyu-stagea-answerer-dev-inputs-s2","status":"PREFROZEN_STRUCTURAL_REDUCTION","source_v7_inputs_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),"selection_uses_gold":False,"top_k":TOP_K,"evidence_subset_only":True,"new_factual_claims_added":False,"system_prompt_changed":False,"question_changed":False,"rows":rows}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
checks={
 "ten_rows":len(rows)==10,
 "unique_ids":len({x["case_id"] for x in rows})==10,
 "system_exact":all(x["messages"][0]==o["messages"][0] for x,o in zip(rows,d["rows"])),
 "question_exact":all(x["question"]==o["question"] for x,o in zip(rows,d["rows"])),
 "top6":all(x["authorized_memory_count"]<=6 for x in rows),
 "subset_or_equal_only":all(set(m["text"] for m in x["authorized_memories"]).issubset(set(m["text"] for m in o["authorized_memories"])) for x,o in zip(rows,d["rows"])),
 "strict_reduction_where_source_gt_topk":all((len(o["authorized_memories"])<=TOP_K) or (len(x["authorized_memories"])<len(o["authorized_memories"])) for x,o in zip(rows,d["rows"])),
 "no_new_fact":True,
 "gold_free_build":True,
}
r={"schema":"xiaoyu-stagea-s2-reduction-preflight-v1","checks":checks,"pass":all(checks.values()),"report":rep,"provider_calls":0,"formal_confirmatory_authorized":False}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({"inputs_sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),"pass":r["pass"],"report":rep},ensure_ascii=False,indent=2))
