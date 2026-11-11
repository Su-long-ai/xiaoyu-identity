from __future__ import annotations
import json,re,math,hashlib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];G=ROOT/"governance"
SRC=G/"stagea_answerer_dev_v7_inputs.json";OUT=G/"stagea_answerer_dev_s1_inputs.json"
STOP=set("a an the is are was were be to of in on at by for from with and or but as what who which when where why how did does do has have had my your her his their our this that these those it its into after before current updated update now then might about during user".split())
def st(w):
 w=re.sub("[^a-z0-9]","",w.lower());D={"reduction":"reduc","reduced":"reduc","reduce":"reduc","preference":"prefer","deteriorated":"deteriorat","deterioration":"deteriorat"}
 if w in D:return D[w]
 if len(w)>5 and w.endswith("ing"):w=w[:-3]
 elif len(w)>4 and w.endswith("ed"):w=w[:-2]
 elif len(w)>3 and w.endswith("s"):w=w[:-1]
 return w
def tk(s):return [x for x in map(st,re.findall("[A-Za-z0-9]+",str(s))) if len(x)>1 and x not in STOP]
def qdate(q):
 M={x:i+1 for i,x in enumerate("january february march april may june july august september october november december".split())};m=re.search(r"(?i)\b("+"|".join(M)+r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b",q)
 return None if not m else f"{int(m.group(3)):04d}-{M[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
def parse(c):
 a,q=c.split("\nQUESTION:\n",1);z=a.split("AUTHORIZED MEMORIES:\n",1)[1];ms=[]
 for p in re.split(r"\n\n(?=\[\d+\] authority=)",z.strip()):
  m=re.match(r"\[(\d+)\] authority=([^ ]+) timestamp=([^\n]+)\n(.*)",p,re.S)
  if m:ms.append({"old_index":int(m.group(1)),"authority":m.group(2),"timestamp":m.group(3),"text":m.group(4).strip()})
 return q.strip(),ms
def score(q,ms,m):
 qt=set(tk(q));mt=set(tk(m["text"]));df=Counter(t for x in ms for t in set(tk(x["text"])));n=len(ms)
 return sum(math.log((n+1)/(df[t]+.5))+.3 for t in qt if t in mt)+(.18 if m["authority"]=="user_state" else .08)
def order(q,ms):
 d=qdate(q)
 return sorted(ms,key=lambda m:(0 if d and m["timestamp"].startswith(d) else 1,-score(q,ms,m),m["old_index"]))
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
d=json.loads(SRC.read_text("utf-8"));rows=[]
for old in d["rows"]:
 x=json.loads(json.dumps(old));q,ms=parse(x["messages"][-1]["content"]);ordered=order(q,ms)
 blocks=[f"[{i}] authority={m['authority']} timestamp={m['timestamp']}\n{m['text']}" for i,m in enumerate(ordered,1)]
 x["messages"][-1]["content"]="AUTHORIZED MEMORIES:\n"+"\n\n".join(blocks)+"\n\nQUESTION:\n"+q
 x["case_id"]="anss1-"+hashlib.sha256((x["qa_case_id"]+"|"+stable(x["messages"])).encode()).hexdigest()[:16]
 x["request_messages_sha256"]=stable(x["messages"])
 x["representation_change"]="FULL_EVIDENCE_DATE_THEN_QUERY_REORDER_ONLY"
 rows.append(x)
out={"schema":"xiaoyu-stagea-answerer-dev-inputs-s1","status":"PREFROZEN_STRUCTURAL_REORDER","source_v7_inputs_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),"selection_uses_gold":False,"evidence_deleted":False,"new_factual_claims_added":False,"rows":rows}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({"inputs_sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),"cases":len(rows),"case_ids":[x["case_id"] for x in rows]},ensure_ascii=False,indent=2))
