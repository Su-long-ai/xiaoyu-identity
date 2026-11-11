from __future__ import annotations
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];G=ROOT/"governance"
SRC=G/"stagea_answerer_dev_s2_offline_inputs.json";OUT=G/"stagea_answerer_dev_s2_inputs.json"
d=json.loads(SRC.read_text("utf-8"))
d["schema"]="xiaoyu-stagea-answerer-dev-inputs-s2"
d["status"]="PREFROZEN_STRUCTURAL_REDUCTION"
for x in d["rows"]:
    x["case_id"]="anss2-"+hashlib.sha256((x["qa_case_id"]+"|"+x["request_messages_sha256"]).encode()).hexdigest()[:16]
OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n","utf-8")
print(json.dumps({"sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),"cases":len(d["rows"]),"case_ids":[x["case_id"] for x in d["rows"]]},ensure_ascii=False,indent=2))
