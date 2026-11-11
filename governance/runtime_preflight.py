# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, importlib.util, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def resolve_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p

def check(spec: dict) -> dict:
    issues = []
    checked = []

    for name in spec.get("python_imports", []):
        ok = importlib.util.find_spec(name) is not None
        checked.append({"kind": "python_import", "name": name, "ok": ok})
        if not ok:
            issues.append({"kind": "python_import", "name": name, "reason": "module_not_found"})

    for value in spec.get("required_files", []):
        p = resolve_path(value)
        ok = p.is_file()
        checked.append({"kind": "file", "path": str(p), "ok": ok})
        if not ok:
            issues.append({"kind": "file", "path": str(p), "reason": "missing_required_file"})

    for group in spec.get("any_file_groups", []):
        paths = [resolve_path(x) for x in group]
        ok = any(p.is_file() for p in paths)
        checked.append({"kind": "any_file_group", "paths": [str(p) for p in paths], "ok": ok})
        if not ok:
            issues.append({"kind": "any_file_group", "paths": [str(p) for p in paths], "reason": "no_alternative_file_present"})

    for name in spec.get("required_env_vars", []):
        ok = bool(os.environ.get(name))
        checked.append({"kind": "env_var", "name": name, "ok": ok})
        if not ok:
            issues.append({"kind": "env_var", "name": name, "reason": "missing_or_empty"})

    for name in spec.get("required_commands", []):
        path = shutil.which(name)
        ok = path is not None
        checked.append({"kind": "command", "name": name, "resolved": path, "ok": ok})
        if not ok:
            issues.append({"kind": "command", "name": name, "reason": "not_on_path"})

    return {
        "schema": "xiaoyu-runtime-preflight-result-v1",
        "status": "PASS" if not issues else "BLOCKED_ENVIRONMENT_DEPENDENCY",
        "scientific_outcome_if_blocked": "NOT_TESTED",
        "checked": checked,
        "issues": issues,
        "network_used": False,
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--write")
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if spec.get("schema") not in (None, "xiaoyu-runtime-preflight-spec-v1"):
        raise SystemExit("unsupported preflight schema")
    result = check(spec)
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.write:
        Path(args.write).write_text(body, encoding="utf-8")
    print(body, end="")
    return 0 if result["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
