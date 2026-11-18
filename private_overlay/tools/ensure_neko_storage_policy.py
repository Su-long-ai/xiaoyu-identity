from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _bind_storage(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, required=True)
    ap.add_argument("--storage-root", type=Path, required=True)
    args = ap.parse_args()

    storage_root = args.storage_root.resolve()
    if not storage_root.is_dir():
        raise SystemExit(f"storage root does not exist: {storage_root}")

    _bind_storage(storage_root)
    sys.path.insert(0, str(args.neko_root.resolve()))

    from utils.config_manager import get_config_manager
    from utils.storage.location_bootstrap import build_storage_location_bootstrap_payload
    from utils.storage.policy import save_storage_policy

    cm = get_config_manager()
    before = build_storage_location_bootstrap_payload(cm)
    reason = str(before.get("blocking_reason") or "").strip()

    wrote = False
    if reason == "selection_required":
        current = Path(str(before.get("current_root") or "")).resolve()
        if current != storage_root:
            raise SystemExit(
                f"refuse storage selection mismatch: current={current} requested={storage_root}"
            )
        save_storage_policy(
            cm,
            selected_root=storage_root,
            selection_source="default",
            anchor_root=storage_root,
        )
        wrote = True
    elif reason:
        raise SystemExit(
            f"N.E.K.O storage requires native recovery/migration first: {reason}"
        )

    after = build_storage_location_bootstrap_payload(cm)
    result = {
        "verdict": "PASS" if not after.get("blocking_reason") else "FAIL",
        "storage_root": str(storage_root),
        "policy_written": wrote,
        "selection_required": bool(after.get("selection_required")),
        "blocking_reason": str(after.get("blocking_reason") or ""),
        "used_neko_native_policy": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PASS" else 5


if __name__ == "__main__":
    raise SystemExit(main())