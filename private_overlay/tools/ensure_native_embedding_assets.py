from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = "jinaai/jina-embeddings-v5-text-nano-retrieval"
REVISION = "ac5d898c8d382b17167c33e5c8af644a3519b47d"
PROFILE_ID = "local-text-retrieval-v1"
VARIANT = "int8"
PREPARED_MARKER = ".prepared.json"


def _native_profile_complete(neko_root: Path, output_root: Path) -> bool:
    sys.path.insert(0, str(neko_root))
    try:
        from memory._embeddings.profiles import profile_is_complete
    finally:
        try:
            sys.path.remove(str(neko_root))
        except ValueError:
            pass
    return bool(
        profile_is_complete(
            str(output_root),
            PROFILE_ID,
            VARIANT,
        )
    )


def inspect_assets(neko_root: Path) -> dict:
    output_root = neko_root / "data" / "embedding_models"
    profile_dir = output_root / PROFILE_ID
    marker_path = profile_dir / PREPARED_MARKER
    marker = None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        marker = None

    complete = _native_profile_complete(neko_root, output_root)
    pin_matches = bool(
        isinstance(marker, dict)
        and marker.get("repo") == REPO
        and marker.get("revision") == REVISION
    )
    return {
        "output_root": str(output_root),
        "profile_dir": str(profile_dir),
        "complete": complete,
        "pin_matches": pin_matches,
        "ready": bool(complete and pin_matches),
        "marker": marker,
    }


def ensure_assets(neko_root: Path, *, verify_only: bool = False) -> dict:
    state = inspect_assets(neko_root)
    if state["ready"]:
        state["action"] = "already_ready"
        return state

    if verify_only:
        raise RuntimeError(
            "N.E.K.O native embedding assets are incomplete or not pinned: "
            + json.dumps(state, ensure_ascii=False)
        )

    python = neko_root / ".venv" / "Scripts" / "python.exe"
    prepare = neko_root / "scripts" / "prepare_embedding_model.py"
    if not python.is_file():
        raise RuntimeError(f"N.E.K.O venv python not found: {python}")
    if not prepare.is_file():
        raise RuntimeError(f"N.E.K.O native embedding prepare script not found: {prepare}")

    subprocess.run(
        [
            str(python),
            str(prepare),
            "--repo",
            REPO,
            "--revision",
            REVISION,
            "--profile-id",
            PROFILE_ID,
            "--output-root",
            str(neko_root / "data" / "embedding_models"),
            "--variant",
            VARIANT,
        ],
        cwd=str(neko_root),
        check=True,
    )
    after = inspect_assets(neko_root)
    if not after["ready"]:
        raise RuntimeError(
            "N.E.K.O native embedding prepare completed without a ready pinned profile: "
            + json.dumps(after, ensure_ascii=False)
        )
    after["action"] = "prepared_by_neko_native_script"
    return after


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure XiaoYu uses N.E.K.O's pinned native local embedding assets."
    )
    parser.add_argument("--neko-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    result = ensure_assets(args.neko_root.resolve(), verify_only=args.verify_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
