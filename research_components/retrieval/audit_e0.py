# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAST = ROOT/"governance"/"fastlane"
RUNNER = ROOT/"research_components"/"retrieval"/"run_local_e2e.py"
OOD_FIXTURE = FAST/"audit_holdout"/"local_ood_v1_120.json"
OOD_EXPECTED_SHA = "27b9752076574a51a22668a6bb160498a28021b7b80a813b5984943b9c266028"
OOD_MIN_CORRECT_DELTA = 3
DEV_FIXTURE_MANIFEST = FAST/"LOCAL_DEV_FIXTURES.json"

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def resolve_component(path_text: str) -> Path:
    p = Path(path_text)
    if not p.is_absolute():
        p = ROOT/p
    return p.resolve()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--e0",required=True)
    args=ap.parse_args()
    e0_path=Path(args.e0).resolve()
    e0=json.loads(e0_path.read_text(encoding="utf-8"))
    if e0.get("schema")=="xiaoyu-fast-retrieval-e0-v4" or e0.get("status")=="E0_EXTERNAL_DEV_QUALIFIED":
        raise SystemExit("CURRENT_E0_V4_DOES_NOT_USE_LIGHT_AUDIT: proceed to Candidate Freeze, then LongMemEval.")
    pause_path = FAST/"LIGHT_AUDIT_PAUSE.json"
    if pause_path.is_file():
        try:
            pause = json.loads(pause_path.read_text(encoding="utf-8-sig"))
        except Exception:
            pause = {"status":"PAUSED"}
        if str(pause.get("status","")).upper() == "PAUSED":
            allowed={str(x) for x in (pause.get("allow_e0_ids") or [])}
            if str(e0.get("e0_id") or "") not in allowed:
                raise SystemExit("LIGHT_AUDIT_PAUSED: general light-audit pause is active and this E0 is not owner-whitelisted.")
    if e0.get("status")!="E0_READY_FOR_LIGHT_AUDIT":
        raise SystemExit("E0 is not ready for light audit")
    component=resolve_component(e0["component"]["path"])
    expected_sha=str(e0["component"]["sha256"])
    if sha(component)!=expected_sha:
        raise SystemExit("component SHA drift before audit")

    source=component.read_text(encoding="utf-8",errors="replace")
    forbidden=[
        "locomo-b200",
        "LOCOMO_EXPOSED_DEV",
        "CAPABILITY_EXTERNAL_LOCOMO200_RESULT",
        "evidence_diagnostic.json",
        "gold_answer",
    ]
    leaks=[x for x in forbidden if x.casefold() in source.casefold()]

    label="audit_"+re.sub(r"[^A-Za-z0-9_.-]+","_",str(e0["e0_id"]))
    cmd=[
        sys.executable,str(RUNNER),
        "--component",str(component),
        "--provider","none",
        "--agent-id","independent-auditor",
        "--run-label",label,
    ]
    fixture_meta=e0.get("fixture") if isinstance(e0.get("fixture"),dict) else None
    if fixture_meta and fixture_meta.get("path"):
        cmd.extend(["--fixture",str(fixture_meta["path"])])
    started=time.time()
    proc=subprocess.run(cmd,cwd=str(ROOT),text=True,capture_output=True,timeout=1800)
    dev_pass=False
    ood_run=None
    ood_pass=False
    ood_reason="not run because dev reproduction failed"
    if proc.returncode!=0:
        verdict="FAIL"
        run=None
        reason="local E2E reproduction failed to execute"
    else:
        run_path=FAST/"runs"/f"{label}.json"
        run=json.loads(run_path.read_text(encoding="utf-8"))
        c=run["candidate"]; b=run["baseline"]; d=run["delta"]
        real_advantage=(
            int(d["correct_cases"])>=1
            and float(d["accuracy"])>0
            and float(d["full_evidence_rate"])>=0
        )
        same_cap=int(run.get("context_cap") or 0)==20
        sha_ok=sha(component)==expected_sha
        expected_baseline=e0.get("baseline_id")
        same_baseline=(not expected_baseline) or str(run.get("baseline_id"))==str(expected_baseline)
        expected_fixture=(e0.get("fixture") or {}).get("sha256") if isinstance(e0.get("fixture"),dict) else None
        same_fixture=(not expected_fixture) or str((run.get("fixture") or {}).get("sha256"))==str(expected_fixture)
        primary_dev_sha=None
        if DEV_FIXTURE_MANIFEST.is_file():
            try:
                primary_dev_sha=str((json.loads(DEV_FIXTURE_MANIFEST.read_text(encoding="utf-8")).get("default_dev") or {}).get("sha256") or "")
            except Exception:
                primary_dev_sha=None
        current_primary_dev=bool(primary_dev_sha and str(expected_fixture)==primary_dev_sha)
        dev_pass=bool(real_advantage and same_cap and sha_ok and same_baseline and same_fixture and current_primary_dev and not leaks)
        if dev_pass:
            if (not OOD_FIXTURE.is_file()) or sha(OOD_FIXTURE)!=OOD_EXPECTED_SHA:
                ood_reason="OOD fixture missing or SHA drift"
            else:
                ood_label="audit_ood_"+re.sub(r"[^A-Za-z0-9_.-]+","_",str(e0["e0_id"]))
                ood_cmd=[
                    sys.executable,str(RUNNER),
                    "--component",str(component),
                    "--provider","none",
                    "--agent-id","independent-auditor",
                    "--run-label",ood_label,
                    "--fixture",str(OOD_FIXTURE),
                ]
                ood_proc=subprocess.run(ood_cmd,cwd=str(ROOT),text=True,capture_output=True,timeout=1800)
                if ood_proc.returncode==0:
                    ood_path=FAST/"runs"/f"{ood_label}.json"
                    ood_run=json.loads(ood_path.read_text(encoding="utf-8"))
                    od=ood_run["delta"]
                    ood_pass=bool(
                        int(od["correct_cases"])>=OOD_MIN_CORRECT_DELTA
                        and float(od["accuracy"])>0
                        and float(od["full_evidence_rate"])>=0
                        and str((ood_run.get("fixture") or {}).get("sha256"))==OOD_EXPECTED_SHA
                        and str(ood_run.get("baseline_id"))==str(e0.get("baseline_id"))
                    )
                    ood_reason=(
                        "OOD generalization advantage reproduced"
                        if ood_pass else
                        "candidate did not clear frozen OOD generalization margin"
                    )
                else:
                    ood_reason="OOD reproduction failed to execute"
        verdict="PASS" if dev_pass and ood_pass else "FAIL"
        reason=(
            "dev advantage reproduced and independent Local-OOD120 generalization gate passed"
            if verdict=="PASS" else
            ("dev reproduction failed" if not dev_pass else ood_reason)
        )

    audit_id="AUDIT-"+str(e0["e0_id"])
    out={
        "schema":"xiaoyu-fast-retrieval-light-audit-v3",
        "audit_id":audit_id,
        "created_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "e0_id":e0["e0_id"],
        "e0_path":str(e0_path),
        "component":{"path":str(component),"sha256":expected_sha},
        "checks":{
            "component_sha_unchanged":sha(component)==expected_sha,
            "obvious_external200_leak_tokens":leaks,
            "context_cap_20":bool(run and int(run.get("context_cap") or 0)==20),
            "same_baseline":bool(run and ((not e0.get("baseline_id")) or str(run.get("baseline_id"))==str(e0.get("baseline_id")))),
            "same_fixture":bool(run and ((not ((e0.get("fixture") or {}).get("sha256") if isinstance(e0.get("fixture"),dict) else None)) or str((run.get("fixture") or {}).get("sha256"))==str((e0.get("fixture") or {}).get("sha256")))),
            "current_primary_dev_fixture":bool(run and current_primary_dev),
            "local_e2e_advantage_reproduced":bool(run and int(run["delta"]["correct_cases"])>=1 and float(run["delta"]["accuracy"])>0),
            "full_evidence_nonregression":bool(run and float(run["delta"]["full_evidence_rate"])>=0),
            "ood_fixture_sha256":OOD_EXPECTED_SHA,
            "ood_generalization_pass":bool(ood_pass),
        },
        "ood_gate":{
            "fixture":str(OOD_FIXTURE.relative_to(ROOT)).replace("\\","/"),
            "fixture_sha256":OOD_EXPECTED_SHA,
            "min_correct_delta":OOD_MIN_CORRECT_DELTA,
            "pass":bool(ood_pass),
            "reason":ood_reason,
            "reproduction_run":(
                str((FAST/"runs"/("audit_ood_"+re.sub(r"[^A-Za-z0-9_.-]+","_",str(e0["e0_id"]))+".json")).relative_to(ROOT)).replace("\\","/")
                if ood_run else None
            ),
            "baseline":(ood_run or {}).get("baseline"),
            "candidate":(ood_run or {}).get("candidate"),
            "delta":(ood_run or {}).get("delta"),
        },
        "verdict":verdict,
        "reason":reason,
        "reproduction_run":str((FAST/"runs"/f"{label}.json").relative_to(ROOT)).replace("\\","/") if run else None,
        "external_stage1_authorized":verdict=="PASS",
        "external200_authorized":False,
        "external200_gate":"REQUIRES_EXTERNAL100_PASS",
        "local_provider_policy":"NONE_ONLY",
        "elapsed_seconds":time.time()-started,
        "runner_stdout_tail":proc.stdout[-4000:],
        "runner_stderr_tail":proc.stderr[-4000:],
    }
    out_path=FAST/"audits"/f"{audit_id}.json"
    out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"verdict":verdict,"audit":str(out_path),"reason":reason,"checks":out["checks"]},ensure_ascii=False,indent=2))
    raise SystemExit(0 if verdict=="PASS" else 2)

if __name__=="__main__":
    main()
