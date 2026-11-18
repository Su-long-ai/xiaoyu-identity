import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STAGE = Path(r"D:\xiaoyu_private_overlay_state\migration\current")
DEFAULT_SANDBOX = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--isolated-root", type=Path, default=DEFAULT_SANDBOX)
    args = parser.parse_args()

    args.isolated_root.mkdir(parents=True, exist_ok=True)
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(args.isolated_root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(args.isolated_root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(args.isolated_root / ".runtime")

    sys.path.insert(0, str(args.neko_root))
    from memory.external_markdown_import import (  # noqa: E402
        MarkdownSourceFile,
        build_import_candidates,
    )

    sources = []
    for name in ("SOUL.md", "USER.md", "MEMORY.md"):
        source_path = args.stage / name
        if source_path.exists():
            sources.append(
                MarkdownSourceFile(
                    name,
                    source_path.read_text(encoding="utf-8"),
                )
            )

    analysis = build_import_candidates(sources, source_format="openclaw")
    candidates = analysis["candidates"]
    summary = {
        "source_format": analysis["source_format"],
        "files": analysis["files"],
        "candidate_count": len(candidates),
        "persona_candidates": sum(c["target"] == "persona" for c in candidates),
        "fact_candidates": sum(c["target"] == "facts" for c in candidates),
        "neko_persona_candidates": sum(
            c["target"] == "persona" and c["entity"] == "neko" for c in candidates
        ),
        "master_persona_candidates": sum(
            c["target"] == "persona" and c["entity"] == "master" for c in candidates
        ),
        "warnings": [
            {
                "source_file": w.get("source_file"),
                "patterns": w.get("patterns", []),
            }
            for w in analysis["warnings"]
        ],
        "writes_performed": 0,
        "isolated_root": str(args.isolated_root),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["warnings"]:
        return 3
    if summary["neko_persona_candidates"] < 1:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
