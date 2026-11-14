# -*- coding: utf-8 -*-
from pathlib import Path
import collections,json,re,shutil,sys,tempfile,time

ROOT=Path(r"D:\dsh-fish")
A=ROOT/"governance/evaluation/v11_capability/agents"
RROOT=ROOT/"external/benchmarks/rhelm"
SRC=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_20261114/AUTH_DOCUMENT_INGRESS_RC_V2"
OUT=A/"results/product_integration/LEAD_AUTH_DOCUMENT_INGRESS_V2_20261114"

def docs(persona):
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
 return out

def main():
 persona="Martin_Keller";rows=docs(persona)
 td=Path(tempfile.mkdtemp(prefix="x360_bench_",dir=str(OUT)))
 local=td/"RC"
 try:
  shutil.copytree(SRC,local,ignore=shutil.ignore_patterns("runtime","__pycache__","*.pyc"))
  sys.path.insert(0,str(local))
  from unified_runtime import UnifiedTextRuntime
  rt=UnifiedTextRuntime()
  try:
   t0=time.perf_counter();out=rt.ingest_user_documents(rows);t1=time.perf_counter()
   again=rt.sync_read_index();t2=time.perf_counter()
   q0=time.perf_counter()
   found=rt.source_tool.search_memory_sources(
      query="Stuttgart cycling Black Forest",purpose="fact",limit=7)
   q1=time.perf_counter()
  finally:rt.close()
  result={
   "schema":"xiaoyu-auth-document-ingress-v2-local-benchmark-v1",
   "persona":persona,"question_loaded":False,"gold_loaded":False,"model_calls":0,
   "documents":len(rows),"characters":sum(len(x["text"]) for x in rows),
   "first_bulk_import_and_projection_seconds":round(t1-t0,3),
   "second_idempotent_projection_seconds":round(t2-t1,3),
   "search_seconds":round(q1-q0,4),
   "active_documents":out["read_index_sync"].get("active_documents"),
   "projection_changed":out["read_index_sync"]["document_projection"].get("changed"),
   "projection_skipped":out["read_index_sync"]["document_projection"].get("skipped"),
   "cjk_document_sync_count":out["read_index_sync"].get("cjk_document_sync_count"),
   "second_projection_changed":again["document_projection"].get("changed"),
   "second_projection_skipped":again["document_projection"].get("skipped"),
   "search_hits":len(found.get("hits") or []),
  }
  (OUT/"LOCAL_BULK_PROJECTION_BENCHMARK.json").write_text(
     json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
  print(json.dumps(result,ensure_ascii=False,indent=2))
 finally:
  shutil.rmtree(td,ignore_errors=True)

if __name__=="__main__":main()
