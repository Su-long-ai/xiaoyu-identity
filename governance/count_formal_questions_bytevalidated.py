#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducible formal-safe HaluMem question-count provenance.

Formal confirmatory rows are never json-decoded. For selected confirmatory rows,
the script only counts the exact JSON field-name byte sequence "question".
That structural counting rule is first validated against the two exposed pilot
UUIDs in BOTH Medium and Long by comparing it to ordinary JSON session question
cardinality. Dataset and split-manifest bytes are bound into the output.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
FILES={
 "m":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Medium.jsonl",
 "l":ROOT/"external"/"halumem_dataset_cache"/"HaluMem-Long.jsonl",
}
OUT=GOV/"FORMAL_SAFE_QUESTION_COUNT_V4.json"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    split=json.loads(SPLIT.read_text("utf-8"))["halumem"]
    pilots=set(map(str,split["pilot_uuids"]))
    confirms=set(map(str,split["confirmatory_uuids"]))
    if len(pilots)!=2 or len(confirms)!=18 or pilots & confirms:
        raise RuntimeError("split cardinality/overlap drift")
    uuid_bytes={u:u.encode() for u in pilots|confirms}
    out={
      "schema":"xiaoyu-formal-question-count-bytevalidated-v2",
      "method":"selected-line raw-byte exact field-name count after exposed-pilot schema validation",
      "generator_path":"governance/count_formal_questions_bytevalidated.py",
      "generator_sha256":sha(Path(__file__)),
      "split_manifest_path":"governance/E2_SPLIT_MANIFEST.json",
      "split_manifest_sha256":sha(SPLIT),
      "dataset_bindings":{},
      "gold_fields_materialized_formal":0,
      "pilot_validation":{},
      "confirmatory":{},
    }
    for variant,path in FILES.items():
        out["dataset_bindings"][variant]={"path":str(path.relative_to(ROOT)).replace("\\","/"),"sha256":sha(path),"bytes":path.stat().st_size}
        pv=[]; cr=[]; seen=set()
        with path.open("rb") as f:
            for raw in f:
                uid=None
                for u,ub in uuid_bytes.items():
                    if ub in raw:
                        uid=u;break
                if uid is None:continue
                if uid in seen:raise RuntimeError(f"duplicate selected uuid {variant}:{uid}")
                seen.add(uid)
                byte_n=raw.count(b'"question"')
                if uid in pilots:
                    obj=json.loads(raw)
                    exact=sum(len(s.get("questions") or []) for s in obj.get("sessions") or [])
                    pv.append({"uuid":uid,"byte_count":byte_n,"json_exact":exact,"match":byte_n==exact})
                else:
                    cr.append({"uuid_hash":hashlib.sha256(uid.encode()).hexdigest(),"question_count":byte_n})
        out["pilot_validation"][variant]={"rows":sorted(pv,key=lambda x:x["uuid"]),"pass":len(pv)==2 and all(x["match"] for x in pv)}
        out["confirmatory"][variant]={"rows":len(cr),"questions":sum(x["question_count"] for x in cr),"per_user":sorted(cr,key=lambda x:x["uuid_hash"])}
    out["pilot_validation_pass"]=all(x["pass"] for x in out["pilot_validation"].values())
    out["total_questions"]=sum(x["questions"] for x in out["confirmatory"].values())
    if not out["pilot_validation_pass"] or any(out["confirmatory"][v]["rows"]!=18 for v in ("m","l")) or out["total_questions"]!=6282:
        raise RuntimeError("question-count provenance validation failed")
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({"m":out["confirmatory"]["m"]["questions"],"l":out["confirmatory"]["l"]["questions"],"total":out["total_questions"],"formal_gold_materialized":0,"output_sha256":sha(OUT)},indent=2))

if __name__=="__main__":main()
