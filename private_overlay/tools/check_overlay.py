import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig"))
PATCHES = json.loads((ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig"))


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def managed_patch_paths() -> set[str]:
    paths: set[str] = set()
    for patch in PATCHES["patches"]:
        patch_path = ROOT / "patches" / patch["file"]
        if not patch_path.is_file():
            continue
        for line in patch_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("+++ b/"):
                paths.add(line[len("+++ b/") :].strip())
    return paths


def dirty_paths(status: str) -> set[str]:
    paths: set[str] = set()
    for raw in status.splitlines():
        if not raw.strip():
            continue
        entry = raw[3:].strip() if len(raw) >= 4 else raw.strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        if entry:
            paths.add(entry.replace("\\", "/"))
    return paths


def main() -> int:
    neko_root = Path(os.environ.get("NEKO_ROOT", r"D:\xiaoyu_external_audit\N.E.K.O"))
    print(f"overlay={ROOT}")
    print(f"neko_root={neko_root}")

    if not neko_root.exists():
        print("FAIL: N.E.K.O checkout not found")
        return 2

    head = git(neko_root, "rev-parse", "HEAD")
    branch = git(neko_root, "branch", "--show-current")
    status = subprocess.check_output(
        ["git", "-C", str(neko_root), "status", "--short"],
        text=True,
        stderr=subprocess.STDOUT,
    ).rstrip("\r\n")

    print(f"neko_branch={branch}")
    print(f"neko_head={head}")
    print(f"tested_commit={LOCK['tested_commit']}")
    print(f"core_patch_count={len(PATCHES['patches'])}")

    if LOCK["allow_dual_write"]:
        print("FAIL: dual-write must stay disabled")
        return 3
    if len(PATCHES["patches"]) > LOCK["core_patch_budget"]:
        print("FAIL: patch queue exceeds declared budget")
        return 4

    expected_dirty = managed_patch_paths()
    actual_dirty = dirty_paths(status)
    unmanaged_dirty = actual_dirty - expected_dirty
    if unmanaged_dirty:
        print("FAIL: upstream checkout has unmanaged changes")
        for path in sorted(unmanaged_dirty):
            print(path)
        return 5
    if actual_dirty:
        print(
            "PASS: upstream checkout changes are fully explained by managed patches: "
            + ", ".join(sorted(actual_dirty))
        )

    if head != LOCK["tested_commit"]:
        print("WARN: N.E.K.O HEAD differs from the last tested commit")
        print("      run acceptance before updating the lock")

    print("PASS: private overlay contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
