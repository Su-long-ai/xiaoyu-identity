from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = OVERLAY_ROOT / "privacy" / "provider_policy.json"
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STORAGE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")

MODEL_TIERS = (
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
    "image",
)


def _normalize_host(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlsplit(raw)
    return (parsed.hostname or "").strip().lower().rstrip(".")


def _is_local_host(host: str) -> bool:
    if host in {"localhost", "host.docker.internal"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.endswith(".localhost")


def _matches_suffix(host: str, suffix: str) -> bool:
    s = str(suffix or "").strip().lower().lstrip(".").rstrip(".")
    return bool(s) and (host == s or host.endswith("." + s))


def host_is_allowed(host: str, policy: dict) -> tuple[bool, str]:
    host = str(host or "").strip().lower().rstrip(".")
    if not host:
        return False, "missing_host"

    if policy.get("allow_localhost", False) and _is_local_host(host):
        return True, "localhost"

    for suffix in policy.get("explicitly_denied_host_suffixes", []):
        if _matches_suffix(host, suffix):
            return False, "explicitly_denied"

    for suffix in policy.get("allowed_host_suffixes", []):
        if _matches_suffix(host, suffix):
            return True, "allowlist"

    if policy.get("fail_closed_unknown_hosts", True):
        return False, "unknown_host"
    return True, "unknown_allowed_by_policy"


def _set_storage_root(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _resolved_rows(neko_root: Path, storage_root: Path, policy: dict) -> list[dict]:
    _set_storage_root(storage_root)
    sys.path.insert(0, str(neko_root.resolve()))
    from utils.config_manager import get_config_manager

    cm = get_config_manager()
    rows: list[dict] = []
    for tier in MODEL_TIERS:
        try:
            cfg = cm.get_model_api_config(tier)
        except ValueError:
            continue
        if not isinstance(cfg, dict):
            rows.append({"tier": tier, "eligible": False, "reason": "invalid_config"})
            continue
        if tier == "image" and cfg.get("enabled") is False:
            rows.append({"tier": tier, "enabled": False, "eligible": True, "reason": "disabled"})
            continue
        host = _normalize_host(cfg.get("base_url"))
        allowed, reason = host_is_allowed(host, policy)
        rows.append(
            {
                "tier": tier,
                "enabled": True,
                "model": cfg.get("model"),
                "host": host,
                "provider_type": cfg.get("provider_type"),
                "eligible": allowed,
                "reason": reason,
                "api_key_present": bool(str(cfg.get("api_key") or "").strip()),
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    rows = _resolved_rows(args.neko_root, args.storage_root, policy)
    failures = [row for row in rows if not row.get("eligible", False)]
    result = {
        "verdict": "PASS" if not failures else "FAIL",
        "policy": policy.get("policy"),
        "storage_root": str(args.storage_root.resolve()),
        "checked_tiers": len(rows),
        "failed_tiers": [row.get("tier") for row in failures],
        "rows": rows,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(
                f"{row.get('tier')}: host={row.get('host','')} model={row.get('model','')} "
                f"eligible={row.get('eligible')} reason={row.get('reason')}"
            )
        print("PASS: provider privacy admission" if not failures else "FAIL: provider privacy admission")
    return 0 if not failures else 4


if __name__ == "__main__":
    raise SystemExit(main())
