#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checkpoint-safe wrapper for the frozen E2 LongMemEval pilot.

Default is DRY-RUN. Paid execution requires:
  --execute
  --max-new-cases N
  --expected-initial-done K

The expected-count guard prevents a stale operator/parallel chain from silently
continuing after another executor has advanced the pilot.
"""
from __future__ import annotations
import argparse,concurrent.futures,json,subprocess,sys
from pathlib import Path

GOV=Path(__file__).resolve().parent
RUNNER=GOV/"e2_pilot_runner.py"
MANIFEST=GOV/"E2_PILOT_EXECUTION_MANIFEST.json"
INPUTS=GOV/"e2_pilot_inputs"
RUNTIME=GOV/"e2_pilot_runtime"

def run_one(cid):
    payload=INPUTS/f"{cid}.payload.json"
    cmd=[sys.executable,str(RUNNER),"run-case",
         "--track","longmemeval_answer","--case-id",cid,
         "--payload",str(payload)]
    cp=subprocess.run(cmd,cwd=str(GOV.parent),capture_output=True,text=True,timeout=240)
    if cp.returncode!=0:
        return {"case_id":cid,"ok":False,"returncode":cp.returncode,
                "stdout":cp.stdout[-4000:],"stderr":cp.stderr[-4000:]}
    try:out=json.loads(cp.stdout)
    except Exception:out={"raw_stdout":cp.stdout[-4000:]}
    return {"case_id":cid,"ok":True,"runner":out}

def state():
    manifest=json.loads(MANIFEST.read_text("utf-8"))
    track=manifest["tracks"]["longmemeval_answer"]
    if str(track.get("execution_status") or "READY")!="READY":
        raise SystemExit("LongMemEval frozen track is not READY")
    ids=list(track["case_ids"])
    done={p.stem for p in RUNTIME.glob("lme-a-*.json")}
    remaining=[cid for cid in ids if cid not in done]
    return ids,done,remaining

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--execute",action="store_true",
                    help="Actually delegate paid cases to the frozen runner.")
    ap.add_argument("--max-new-cases",type=int,
                    help="Maximum newly attempted cases; required with --execute.")
    ap.add_argument("--expected-initial-done",type=int,
                    help="Fail if current completed-count differs; required with --execute.")
    args=ap.parse_args()
    ids,done,remaining=state()
    preview={
      "mode":"EXECUTE" if args.execute else "DRY_RUN",
      "planned":len(ids),"initial_done":sum(cid in done for cid in ids),
      "remaining_count":len(remaining),"remaining":remaining,
    }
    if not args.execute:
        print(json.dumps(preview,ensure_ascii=False,indent=2));return
    if args.max_new_cases is None or args.max_new_cases<=0:
        raise SystemExit("--execute requires positive --max-new-cases")
    if args.expected_initial_done is None:
        raise SystemExit("--execute requires --expected-initial-done")
    actual_done=sum(cid in done for cid in ids)
    if actual_done!=args.expected_initial_done:
        raise SystemExit(
          f"checkpoint drift: expected {args.expected_initial_done} done, found {actual_done}")
    selected=remaining[:args.max_new_cases]
    if not selected:
        print(json.dumps({**preview,"attempted":0,"note":"nothing remaining"},ensure_ascii=False,indent=2))
        return
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        future_to_id={ex.submit(run_one,cid):cid for cid in selected}
        for fut in concurrent.futures.as_completed(future_to_id):
            row=fut.result();rows.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            if not row["ok"]:
                for other in future_to_id:
                    if not other.done():other.cancel()
                raise SystemExit(2)
    _,_,remaining_after=state()
    summary={
      "planned":len(ids),"initial_done":actual_done,
      "selected":selected,"attempted":len(rows),
      "success":sum(x["ok"] for x in rows),
      "remaining_count":len(remaining_after),"remaining":remaining_after,
    }
    print("SUMMARY "+json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
