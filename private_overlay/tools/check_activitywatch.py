from __future__ import annotations
import argparse
import os
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--require-running", action="store_true")
    args=p.parse_args()
    local=Path(os.environ.get("LOCALAPPDATA",""))
    exe=local/"Programs"/"ActivityWatch"/"aw-qt.exe"
    cfg=local/"activitywatch"/"activitywatch"/"aw-watcher-window"/"aw-watcher-window.toml"
    errors=[]
    if not exe.is_file():
        errors.append(f"ActivityWatch executable missing: {exe}")
    if not cfg.is_file():
        errors.append(f"ActivityWatch window watcher config missing: {cfg}")
    else:
        text=cfg.read_text(encoding="utf-8-sig")
        active=[]
        for line in text.splitlines():
            stripped=line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.lower().startswith("exclude_title"):
                active.append(stripped)
        if not any(line.replace(" ","").lower()=="exclude_title=true" for line in active):
            errors.append("ActivityWatch must set exclude_title = true before XiaoYu may use it")
    if args.require_running and not errors:
        import urllib.request, json
        try:
            with urllib.request.urlopen("http://127.0.0.1:5600/api/0/info", timeout=2) as r:
                info=json.load(r)
            if str(info.get("version") or "") != "v0.14.3":
                errors.append(f"unexpected ActivityWatch version: {info.get('version')!r}")
        except Exception as exc:
            errors.append(f"ActivityWatch local API unavailable: {type(exc).__name__}")
    if errors:
        for e in errors:
            print("BLOCK_ACTIVITYWATCH:",e)
        return 2
    print("PASS: ActivityWatch 0.14.3 installation/privacy contract ready")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
