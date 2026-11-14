# -*- coding: utf-8 -*-
"""Build question/gold-free per-persona X355 source runtimes once."""
from __future__ import annotations
import argparse,concurrent.futures,hashlib,json,os,re,shutil,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
HOME=A/"results/product_integration/LEAD_AUTH_DOCUMENT_ANSWER_CONTRACT_FRESH24_20261114"
CAND=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_20261114"
RC=CAND/"AUTH_DOCUMENT_INGRESS_RC"
MAN=CAND/"AUTH_DOCUMENT_INGRESS_MANIFEST.json"
CACHE=HOME/"source_runtime_cache"
SUITE=HOME/"FRESH24_FROZEN_NO_GOLD.json"
sys.path.insert(0,str(A))
from run_auth_doc_exact_product_fresh24 import persona_documents

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def safe(s):return re.sub(r"[^A-Za-z0-9_.-]+","_",str(s))
def corpus_sha(docs):
 rows=[{"source_key":x["source_key"],
        "text_sha256":hashlib.sha256(x["text"].encode("utf-8")).hexdigest(),
        "known_at":x.get("known_at"),"valid_at":x.get("valid_at"),
        "lineage_key":x.get("lineage_key")} for x in docs]
 raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
 return hashlib.sha256(raw).hexdigest()

def verify_candidate():
 m=json.loads(MAN.read_text("utf-8"))
 for rel,dig in m["files_sha256"].items():
  if sha(RC/rel)!=dig:raise RuntimeError("candidate_drift:"+rel)
 return sha(MAN)

def child(persona):
 manifest_sha=verify_candidate()
 docs=persona_documents(persona); csha=corpus_sha(docs)
 final=CACHE/safe(persona)
 sealp=final/"CACHE_SEAL.json"
 if sealp.exists():
  seal=json.loads(sealp.read_text("utf-8"))
  if (seal.get("candidate_manifest_sha256")==manifest_sha and
      seal.get("corpus_sha256")==csha and seal.get("document_count")==len(docs)):
   print("CACHE_HIT",persona,len(docs),flush=True);return

 CACHE.mkdir(parents=True,exist_ok=True)
 tmp=Path(tempfile.mkdtemp(prefix=safe(persona)+"_",dir=str(CACHE)))
 local=tmp/"RC";t0=time.time()
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
  finally:
   rt.close()
  sys.path=[x for x in sys.path if x!=str(local)]
  runtime=local/"runtime"
  dbs={x.name:sha(x) for x in sorted(runtime.glob("*.sqlite3"))}
  seal={
   "schema":"xiaoyu-auth-doc-persona-runtime-cache-v1",
   "persona":persona,"candidate_manifest_sha256":manifest_sha,
   "corpus_sha256":csha,"document_count":len(docs),
   "runtime_sqlite_sha256":dbs,
   "gold_loaded":False,"question_loaded":False,"model_calls":0,
   "build_seconds":round(time.time()-t0,3),
  }
  (tmp/"CACHE_SEAL.json").write_text(
      json.dumps(seal,ensure_ascii=False,indent=2)+"\n","utf-8")
  if final.exists():shutil.rmtree(final)
  os.replace(tmp,final)
  print("CACHE_DONE",persona,len(docs),seal["build_seconds"],flush=True)
 except Exception:
  shutil.rmtree(tmp,ignore_errors=True)
  raise

def parent():
 verify_candidate()
 suite=json.loads(SUITE.read_text("utf-8"))
 personas=sorted({x["scope_id"] for x in suite["cases"]})
 # Separate processes avoid Python module collisions between copied RCs.
 def run(persona):
  cp=subprocess.run([sys.executable,str(Path(__file__).resolve()),
      "--child","--persona",persona],cwd=A,text=True)
  if cp.returncode:raise RuntimeError("cache_child_failed:"+persona)
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
  futs=[ex.submit(run,p) for p in personas]
  for f in concurrent.futures.as_completed(futs):f.result()
 seals=[]
 for p in personas:
  seal=json.loads((CACHE/safe(p)/"CACHE_SEAL.json").read_text("utf-8"))
  seals.append(seal)
 out={
  "schema":"xiaoyu-auth-doc-runtime-cache-index-v1",
  "candidate_manifest_sha256":sha(MAN),"personas":len(personas),
  "documents":sum(x["document_count"] for x in seals),
  "all_gold_loaded_false":all(x["gold_loaded"] is False for x in seals),
  "all_question_loaded_false":all(x["question_loaded"] is False for x in seals),
  "all_model_calls_zero":all(x["model_calls"]==0 for x in seals),
  "seals":seals}
 (CACHE/"CACHE_INDEX.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
 print(json.dumps({k:v for k,v in out.items() if k!="seals"},ensure_ascii=False,indent=2))

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--child",action="store_true");ap.add_argument("--persona")
 a=ap.parse_args()
 if a.child:child(a.persona)
 else:parent()
if __name__=="__main__":main()
