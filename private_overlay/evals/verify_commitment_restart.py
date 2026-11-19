from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
PROBE_PARENT = Path(r"D:\xiaoyu_private_overlay_state")
CHARACTER = "XiaoYuCommitmentProbe"
TEXT = "SYNTHETIC_XIAOYU_COMMITMENT_RESTART_PROBE"
NOW = 1_800_000_000.0


def _env(root: Path, neko: Path) -> None:
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")
    sys.path.insert(0, str(neko))


def _store(root: Path, neko: Path):
    _env(root, neko)
    from memory.pinned_facts import PinnedFactStore
    return PinnedFactStore()


def _phase(args) -> int:
    store = _store(args.root, args.neko_root)
    if args.phase == "seed":
        candidate = {
            "text": TEXT,
            "entity": "neko",
            "ttl_days": 3,
            "kind": "commitment",
            "due_at": NOW + 3600,
        }
        counts = store.apply_decisions(
            CHARACTER, [candidate], [("add", None)], now=NOW
        )
        active = store.get_active(CHARACTER, now=NOW)
        print(json.dumps({"counts": counts, "active": active}, ensure_ascii=False))
        return 0 if len(active) == 1 and active[0]["kind"] == "commitment" else 2

    due = store.get_due_commitment(CHARACTER, now=NOW)
    if args.phase == "read":
        print(json.dumps({"due": due}, ensure_ascii=False))
        return 0 if due and due["text"] == TEXT else 3
    if args.phase == "render":
        if not due:
            return 8
        from main_logic.topic.hooks import build_topic_hook_prompt

        commitment = {
            "id": due["id"],
            "text": due["text"],
            "due": "soon",
        }
        prompt = build_topic_hook_prompt("zh", commitment=commitment)
        result = {
            "prompt_nonempty": bool(prompt.strip()),
            "prompt_contains_commitment": TEXT in prompt,
            "prompt_sha256": __import__("hashlib").sha256(
                prompt.encode("utf-8")
            ).hexdigest(),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if all([
            result["prompt_nonempty"],
            result["prompt_contains_commitment"],
        ]) else 9
    if args.phase == "surface":
        if not due:
            return 4
        written = store.mark_surfaced(CHARACTER, [due["id"]], now=NOW)
        print(json.dumps({"due_id": due["id"], "written": written}, ensure_ascii=False))
        return 0 if written == [due["id"]] else 5
    if args.phase == "after":
        later = store.get_due_commitment(CHARACTER, now=NOW + 60)
        print(json.dumps({"due_after_surface": later}, ensure_ascii=False))
        return 0 if later is None else 6
    raise ValueError(args.phase)


def _child(script: Path, root: Path, neko: Path, phase: str) -> dict:
    cp = subprocess.run(
        [sys.executable, str(script), "--phase", phase, "--root", str(root),
         "--neko-root", str(neko)],
        text=True, capture_output=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"{phase} failed rc={cp.returncode}: {cp.stderr[-1200:]}")
    lines = [x for x in cp.stdout.splitlines() if x.strip().startswith("{")]
    return json.loads(lines[-1])


def _parent(args) -> int:
    PROBE_PARENT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="commitment-probe-", dir=PROBE_PARENT))
    try:
        script = Path(__file__).resolve()
        seed = _child(script, root, args.neko_root, "seed")
        read = _child(script, root, args.neko_root, "read")
        render = _child(script, root, args.neko_root, "render")
        surface = _child(script, root, args.neko_root, "surface")
        after = _child(script, root, args.neko_root, "after")
        result = {
            "verdict": "PASS",
            "neko_commit": "7b776173e758401a3819e3ad3d4179e86e23eb0e",
            "fresh_processes": 5,
            "synthetic_only": True,
            "product_data_touched": False,
            "seed_active_count": len(seed.get("active") or []),
            "restart_due_visible": bool(read.get("due")),
            "native_proactive_prompt_nonempty": bool(render.get("prompt_nonempty")),
            "native_proactive_prompt_contains_commitment": bool(
                render.get("prompt_contains_commitment")
            ),
            "native_proactive_prompt_sha256": render.get("prompt_sha256"),
            "surface_written": bool(surface.get("written")),
            "second_restart_duplicate_offer_suppressed": after.get("due_after_surface") is None,
        }
        if not all([
            result["seed_active_count"] == 1,
            result["restart_due_visible"],
            result["native_proactive_prompt_nonempty"],
            result["native_proactive_prompt_contains_commitment"],
            result["surface_written"],
            result["second_restart_duplicate_offer_suppressed"],
        ]):
            result["verdict"] = "FAIL"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.evidence:
            args.evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0 if result["verdict"] == "PASS" else 7
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--phase", choices=["seed", "read", "render", "surface", "after"])
    ap.add_argument("--evidence", type=Path)
    args = ap.parse_args()
    if args.phase:
        return _phase(args)
    return _parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
