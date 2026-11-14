# -*- coding: utf-8 -*-
"""Question/gold/model-free source runtime cache for frozen X360 candidate."""
from __future__ import annotations
import argparse,collections,concurrent.futures,hashlib,json,os,re,shutil,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
HOME=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_FRESH24_20261114"
CAND=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_20261114"
RC=CAND/"AUTH_DOCUMENT_INGRESS_RC_V2"
MAN=CAND/"AUTH_DOCUMENT_INGRESS_V2_MANIFEST.json"
RROOT=ROOT/"external/benchmarks/rhelm"
CACHE=HOME/"source_runtime_cache"
PERSONAS=HOME/"PERSONAS_ONLY.json"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def safe(s):return re.sub(r"[^A-Za-z0-9_.-]+","_",str(s))
def corpus_sha(docs):
 rows=[{"source_key":x["source_key"],
        "text_sha256":hashlib.sha256(x["text"].encode("utf-8")).hexdigest(),
        "known_at":x.get("known_at"),"valid_at":x.get("valid_at"),
        "lineage_key":x.get("lineage_key")} for x in docs]
 raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
 return hashlib.sha256(raw).hexdigest()

def persona_documents(persona):
 out=[]
 for fp in sorted((RROOT/"conversations"/persona).glob("*.json")):
  o=json.loads(fp.read_text("utf-8"));date=str(o.get("date") or "")
  for t in o.get("conversation") or []:
   sid=f"{date}:{int(t['turn'])}";ts=str(t.get("timestamp") or date)
   out.append({"source_key":sid,
    "text":f"[SOURCE {sid}]\nUser: {t.get('user','')}\nAssistant: {t.get('assistant','')}",
    "known_at":ts,"valid_at":ts,
    "lineage_key":f"rhelm:{persona}:conversation:{date}"})
 by=collections.defaultdict(list)
 for fp in sorted((RROOT/"emails"/persona).glob("*.txt")):
  m=re.search(r"(\d{4})_(\d{2})_(\d{2})",fp.name)
  if m:by["-".join(m.groups())].append(fp)
 for d,ps in sorted(by.items()):
  sid=f"Emails_{d}"
  out.append({"source_key":sid,
   "text":"[SOURCE "+sid+"]\n"+"\n\n".join(
     f"### {fp.name}\n"+fp.read_text("utf-8",errors="replace") for fp in ps),
   "known_at":d,"valid_at":d,"lineage_key":f"rhelm:{persona}:email:{d}"})
 for fp in sorted((RROOT/"attachments"/persona).glob("*")):
  if fp.is_file():
   sid=fp.name
   out.append({"source_key":sid,
    "text":f"[SOURCE {sid}]\n"+fp.read_text("utf-8",errors="replace"),
    "known_at":"","valid_at":None,"lineage_key":None})
 if len({x["source_key"] for x in out})!=len(out):
  raise RuntimeError("duplicate_source_key:"+persona)
 return out

def verify_candidate():
 m=json.loads(MAN.read_text("utf-8"))
 if m.get("default_off") is not True or m.get("auto_release") is not False:
  raise RuntimeError("candidate_not_default_off")
 for rel,dig in m["files_sha256"].items():
  if sha(RC/rel)!=dig:raise RuntimeError("candidate_drift:"+rel)
 return sha(MAN)

def child(persona):
 manifest_sha=verify_candidate()
 docs=persona_documents(persona);csha=corpus_sha(docs)
 final=CACHE/safe(persona);sealp=final/"CACHE_SEAL.json"
 if sealp.exists():
  seal=json.loads(sealp.read_text("utf-8"))
  if (seal.get("candidate_manifest_sha256")==manifest_sha and
      seal.get("corpus_sha256")==csha and
      seal.get("document_count")==len(docs)):
   print("CACHE_HIT",persona,len(docs),flush=True);return
 CACHE.mkdir(parents=True,exist_ok=True)
 tmp=Path(tempfile.mkdtemp(prefix=safe(persona)+"_",dir=str(CACHE)))
 local=tmp/"RC";t0=time.perf_counter()
 try:
  shutil.copytree(RC,local,ignore=shutil.ignore_patterns("runtime","__pycache__","*.pyc"))
  sys.path.insert(0,str(local))
  from unified_runtime import UnifiedTextRuntime
  rt=UnifiedTextRuntime()
  try:
   out=rt.ingest_user_documents(docs)
   if out.get("status")!="APPLIED" or out.get("count")!=len(docs):
    raise RuntimeError("bulk_import_failed:"+str(out)[:300])
   sync=out["read_index_sync"]
   if sync.get("active_documents")!=len(docs):
    raise RuntimeError("active_document_count_mismatch")
   again=rt.sync_read_index()
   if again["document_projection"].get("changed")!=0:
    raise RuntimeError("idempotent_projection_changed")
  finally:rt.close()
  sys.path=[x for x in sys.path if x!=str(local)]
  runtime=local/"runtime"
  dbs={x.name:sha(x) for x in sorted(runtime.glob("*.sqlite3"))}
  seal={"schema":"xiaoyu-auth-document-v2-persona-runtime-cache-v1",
    "persona":persona,"candidate_manifest_sha256":manifest_sha,
    "corpus_sha256":csha,"document_count":len(docs),
    "runtime_sqlite_sha256":dbs,
    "gold_loaded":False,"question_loaded":False,"model_calls":0,
    "build_seconds":round(time.perf_counter()-t0,3),
    "canonical_document_ingress":True,
    "idempotent_second_projection":True}
  (tmp/"CACHE_SEAL.json").write_text(json.dumps(seal,ensure_ascii=False,indent=2)+"\n","utf-8")
  if final.exists():shutil.rmtree(final)
  os.replace(tmp,final)
  print("CACHE_DONE",persona,len(docs),seal["build_seconds"],flush=True)
 except Exception:
  shutil.rmtree(tmp,ignore_errors=True)
  raise

def parent():
 verify_candidate()
 po=json.loads(PERSONAS.read_text("utf-8"))
 if po.get("question_loaded") is not False or po.get("gold_loaded") is not False:
  raise RuntimeError("personas_file_not_blind")
 personas=list(po["personas"])
 def run(persona):
  cp=subprocess.run([sys.executable,str(Path(__file__).resolve()),
    "--child","--persona",persona],cwd=A,encoding="utf-8",errors="replace")
  if cp.returncode:raise RuntimeError("cache_child_failed:"+persona+":"+str(cp.returncode))
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
  futs=[ex.submit(run,p) for p in personas]
  for f in concurrent.futures.as_completed(futs):f.result()
 seals=[]
 for persona in personas:
  seals.append(json.loads((CACHE/safe(persona)/"CACHE_SEAL.json").read_text("utf-8")))
 result={"schema":"xiaoyu-auth-document-v2-runtime-cache-index-v1",
  "candidate_manifest_sha256":sha(MAN),"personas":len(personas),
  "documents":sum(x["document_count"] for x in seals),
  "all_gold_loaded_false":all(x["gold_loaded"] is False for x in seals),
  "all_question_loaded_false":all(x["question_loaded"] is False for x in seals),
  "all_model_calls_zero":all(x["model_calls"]==0 for x in seals),
  "max_build_seconds":max(x["build_seconds"] for x in seals),
  "sum_build_seconds":round(sum(x["build_seconds"] for x in seals),3),
  "seals":seals}
 (CACHE/"CACHE_INDEX.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
 print(json.dumps({k:v for k,v in result.items() if k!="seals"},ensure_ascii=False,indent=2))

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--child",action="store_true");ap.add_argument("--persona")
 x=ap.parse_args()
 if x.child:
  if not x.persona:raise RuntimeError("persona_required")
  child(x.persona)
 else:parent()
if __name__=="__main__":main()
