from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SANDBOX = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_CHARACTER = "XiaoYu"


def _set_env(root: Path) -> None:
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root.resolve())
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root.resolve())
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str((root / ".runtime").resolve())


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _probe(args: argparse.Namespace) -> int:
    _set_env(args.isolated_root)
    sys.path.insert(0, str(args.neko_root))
    from utils.config_manager import get_config_manager
    from memory.persona import PersonaManager
    from memory.event_log import EventLog

    cm = get_config_manager()
    cfg = cm.get_model_api_config("correction")
    persona = PersonaManager(event_log=EventLog()).get_persona(args.character_name)
    row = {
        "provider_case": args.provider_case,
        "model": cfg.get("model"),
        "base_url": cfg.get("base_url"),
        "provider_type": cfg.get("provider_type"),
        "api_key_present": bool(str(cfg.get("api_key") or "").strip()),
        "persona_sha256": _digest(persona),
    }
    print("XIAOYU_SWAP_PROBE=" + json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    return 0


def _run_child(args: argparse.Namespace, provider_case: str) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--probe",
        "--provider-case",
        provider_case,
        "--neko-root",
        str(args.neko_root),
        "--isolated-root",
        str(args.isolated_root),
        "--character-name",
        args.character_name,
    ]
    cp = subprocess.run(
        command,
        cwd=str(args.neko_root),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"probe {provider_case} failed: {cp.stderr[-2000:]}")
    for line in reversed(cp.stdout.splitlines()):
        if line.startswith("XIAOYU_SWAP_PROBE="):
            return json.loads(line.split("=", 1)[1])
    raise RuntimeError(f"probe {provider_case} produced no machine result")


def _parent(args: argparse.Namespace) -> int:
    config_path = args.isolated_root / "config" / "core_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    original = config_path.read_bytes() if config_path.exists() else None

    probes = []
    try:
        for provider_case in ("qwen", "free"):
            config_path.write_text(
                json.dumps(
                    {"assistApi": provider_case, "coreApi": provider_case},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            probes.append(_run_child(args, provider_case))
    finally:
        if original is None:
            config_path.unlink(missing_ok=True)
        else:
            config_path.write_bytes(original)

    digests = {p["persona_sha256"] for p in probes}
    changed_provider = len({(p["model"], p["base_url"]) for p in probes}) > 1
    result = {
        "verdict": "PASS" if len(digests) == 1 and changed_provider else "FAIL",
        "character_name": args.character_name,
        "provider_cases": [p["provider_case"] for p in probes],
        "resolved_models": [p["model"] for p in probes],
        "resolved_base_urls": [p["base_url"] for p in probes],
        "api_key_present": [p["api_key_present"] for p in probes],
        "persona_sha256": probes[0]["persona_sha256"] if len(digests) == 1 else None,
        "same_persona_digest": len(digests) == 1,
        "provider_resolution_changed": changed_provider,
        "network_calls_performed": 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PASS" else 6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--isolated-root", type=Path, default=DEFAULT_SANDBOX)
    ap.add_argument("--character-name", default=DEFAULT_CHARACTER)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--provider-case", default="")
    args = ap.parse_args()
    return _probe(args) if args.probe else _parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
