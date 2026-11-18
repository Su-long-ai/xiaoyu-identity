from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STORAGE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")

REQUIRED_TIERS = (
    "conversation",
    "summary",
    "correction",
    "emotion",
    "vision",
    "agent",
    "realtime",
    "tts_default",
    "tts_custom",
    "game_main",
    "game_summary",
)


def _set_storage(root: Path) -> None:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _usable(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and text != "free-access" and text != "__NEKO_SECRET_PRESENT__")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="One-time import of existing environment credentials into N.E.K.O native config."
    )
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    _set_storage(args.storage_root)
    sys.path.insert(0, str(args.neko_root.resolve()))

    from utils.config_manager import get_config_manager

    cm = get_config_manager()
    qwen_key = str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    deepseek_key = str(os.environ.get("DEEPSEEK_API_KEY") or "").strip()

    imported_fields: list[str] = []
    preserved_fields: list[str] = []

    if not args.verify_only:
        if not qwen_key and not deepseek_key:
            print(json.dumps({
                "verdict": "FAIL",
                "reason": "no_supported_environment_credentials",
                "secrets_recorded": False,
            }))
            return 11

        def mutate(cfg: dict):
            core_provider = str(cfg.get("coreApi") or "qwen").strip()
            assist_provider = str(cfg.get("assistApi") or "qwen").strip()

            if "coreApi" not in cfg:
                cfg["coreApi"] = core_provider
                imported_fields.append("coreApi")
            if "assistApi" not in cfg:
                cfg["assistApi"] = assist_provider
                imported_fields.append("assistApi")

            if qwen_key:
                if core_provider == "qwen" and not _usable(cfg.get("coreApiKey")):
                    cfg["coreApiKey"] = qwen_key
                    imported_fields.append("coreApiKey")
                elif _usable(cfg.get("coreApiKey")):
                    preserved_fields.append("coreApiKey")

                if not _usable(cfg.get("assistApiKeyQwen")):
                    cfg["assistApiKeyQwen"] = qwen_key
                    imported_fields.append("assistApiKeyQwen")
                else:
                    preserved_fields.append("assistApiKeyQwen")

            if deepseek_key:
                if not _usable(cfg.get("assistApiKeyDeepseek")):
                    cfg["assistApiKeyDeepseek"] = deepseek_key
                    imported_fields.append("assistApiKeyDeepseek")
                else:
                    preserved_fields.append("assistApiKeyDeepseek")

            return True

        cm.update_json_config("core_config.json", mutate)

    tiers = {}
    missing = []
    for tier in REQUIRED_TIERS:
        cfg = cm.get_model_api_config(tier)
        present = _usable(cfg.get("api_key"))
        tiers[tier] = {
            "model": cfg.get("model"),
            "base_url": cfg.get("base_url"),
            "provider_type": cfg.get("provider_type"),
            "api_key_present": present,
        }
        if not present:
            missing.append(tier)

    result = {
        "verdict": "PASS" if not missing else "FAIL",
        "mode": "verify_only" if args.verify_only else "import",
        "storage_root": str(args.storage_root.resolve()),
        "native_config_authority": True,
        "native_update_api": "ConfigManager.update_json_config",
        "environment_credentials_seen": {
            "DASHSCOPE_API_KEY": bool(qwen_key),
            "DEEPSEEK_API_KEY": bool(deepseek_key),
        },
        "imported_fields": sorted(set(imported_fields)),
        "preserved_fields": sorted(set(preserved_fields)),
        "required_tiers": tiers,
        "missing_key_tiers": missing,
        "secrets_recorded": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not missing else 12


if __name__ == "__main__":
    raise SystemExit(main())
