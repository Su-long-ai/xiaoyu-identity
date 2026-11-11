#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a read-only audit snapshot index for recovery-v2 exact-byte review."""
from __future__ import annotations
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];GOV=ROOT/"governance"
MAN=GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    m=json.loads(MAN.read_text("utf-8"));msha=sha(MAN)
    out=GOV/"recovery_v2_audit_snapshot"/msha[:16]
    if out.exists():shutil.rmtree(out)
    out.mkdir(parents=True)
    rels=[str(MAN.relative_to(ROOT)).replace("\\","/")]
    for sec in ("base_execution","base_final_freeze"):
        rels.append(m[sec]["path"])
    for v in m["incidents"].values():rels.append(v["path"])
    for v in m["runners"].values():rels.append(v["path"])
    for v in m["support_files"].values():rels.append(v["path"])
    for v in m["origin_runners"].values():rels.append(v["path"])
    rels.append(m["legacy_committed_receipts_index"]["path"])
    rels.append(m["judge"]["binding"]["path"]);rels.append(m["judge"]["calibration_contract"]["path"])
    rels=sorted(set(rels))
    rows=[]
    for rel in rels:
        src=ROOT/rel
        if not src.is_file():raise SystemExit("missing snapshot source: "+rel)
        dst=out/rel.replace("/","__")
        shutil.copyfile(src,dst)
        rows.append({"source_path":rel,"source_sha256":sha(src),"bytes":src.stat().st_size,
                     "snapshot_path":str(dst.relative_to(ROOT)).replace("\\","/"),"snapshot_sha256":sha(dst)})
    idx={"schema":"xiaoyu-e2-recovery-v2-audit-snapshot-v1","recovery_manifest_sha256":msha,
         "count":len(rows),"files":rows}
    p=out/"AUDIT_SNAPSHOT_INDEX.json";p.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+"\n","utf-8",newline="\n")
    print(json.dumps({"snapshot_dir":str(out.relative_to(ROOT)).replace("\\","/"),"index":str(p.relative_to(ROOT)).replace("\\","/"),
                      "index_sha256":sha(p),"count":len(rows),"manifest_sha256":msha},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
