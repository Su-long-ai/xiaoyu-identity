import hashlib, json, shutil, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/"MANIFEST.json").read_text(encoding="utf-8"))
expected=set(manifest["files"])
actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and p.name!="MANIFEST.json"}
if actual!=expected:
    print("MANIFEST_MEMBERSHIP_DRIFT",json.dumps({"extra":sorted(actual-expected),"missing":sorted(expected-actual)}))
    raise SystemExit(2)
for rel,meta in manifest["files"].items():
    p=ROOT/rel; got=hashlib.sha256(p.read_bytes()).hexdigest()
    if got!=meta["sha256"]:
        print("MANIFEST_DRIFT",rel,got,meta["sha256"]); raise SystemExit(2)
print("MANIFEST_PASS",len(expected))
jobs=[
 ["private43",["py","-3.11","run_private_safe_contract.py"]],
 ["size",["py","-3.11","-m","unittest","-v","test_assistant_size_limit"]],
 ["m06_attacks",["py","-3.11","test_main06_v2_attacks.py"]],
 ["m06_authority",["py","-3.11","test_main06_v2_authority_matrix.py"]],
 ["m06_postdispatch",["py","-3.11","test_main06_v2_postdispatch_mutations.py"]],
 ["m06_http",["py","-3.11","test_main06_real_http_dispatch.py"]],
 ["m06_nonmemory",["py","-3.11","test_nonmemory_state_generation_bypass.py"]],
 ["m06_ui",["py","-3.11","test_main06_ui_pending_guards.py"]],
 ["r47v2_race",["py","-3.11","test_composed_r47v2_direct_race.py"]],
 ["m07_escape",["py","-3.11","-m","unittest","-v","test_main07_escape_budget"]],
 ["m07_attacks",["py","-3.11","test_main07_candidate.py"]],
 ["m07_binding",["py","-3.11","test_main07_growth_manager_binding.py"]],
 ["compile",["py","-3.11","-m","py_compile","companion.py","identity_core.py","model_adapter.py","product_memory_bridge.py","product_memory_bridge_base.py","send_guard.py"]]]
results=[]
with tempfile.TemporaryDirectory(prefix="xiaoyu_rc_v3_exec_",dir=ROOT.parent) as td:
    EXEC=Path(td)
    for rel in expected:
        src=ROOT/rel; out=EXEC/rel; out.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,out)
    for name,cmd in jobs:
        p=subprocess.run(cmd,cwd=EXEC,capture_output=True,text=True,encoding="utf-8",errors="replace")
        results.append({"name":name,"returncode":p.returncode,"stdout":p.stdout[-4000:],"stderr":p.stderr[-4000:]})
        print(name,"PASS" if p.returncode==0 else "FAIL")
        if p.returncode!=0:
            (ROOT.parent/(ROOT.name+"_LAST_RUN_RESULT.json")).write_text(json.dumps({"pass":False,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
            raise SystemExit(p.returncode)
(ROOT.parent/(ROOT.name+"_LAST_RUN_RESULT.json")).write_text(json.dumps({"pass":True,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
actual_after={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and p.name!="MANIFEST.json"}
if actual_after!=expected:
    print("POSTRUN_BUNDLE_MUTATED"); raise SystemExit(3)
print("RC_V3_ALL_PASS_BUNDLE_UNCHANGED")
