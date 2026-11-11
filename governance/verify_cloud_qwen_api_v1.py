# -*- coding: utf-8 -*-
"""Owner-authorized, single-request, cost-capped Qwen cloud API smoke.

Does not use local Ollama, user/private benchmark data, or Codex.
This is a connectivity test, not a V1 cross-model scientific result.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
sys.path.insert(0, str(ROOT))
import model_adapter

LEDGER = GOV / "cloud_qwen_api_usage.sqlite3"
OUT = GOV / "CLOUD_QWEN_API_SMOKE_RESULT_20261103.json"
DIRECTIVE = GOV / "V1_CLOUD_QWEN_OWNER_DIRECTIVE_20261103.json"
MODEL = "qwen3.8-flash"
# Upper bound across global/international list prices; CNY per million tokens.
INPUT_CNY_PER_M = 1.094
OUTPUT_CNY_PER_M = 3.427
SCOPE_HARD_CAP_CNY = 0.02
MAX_CALLS = 1
MAX_COMPLETION_TOKENS = 48
MESSAGES = [
    {"role": "system", "content": "Respond with a tiny JSON object, no commentary."},
    {"role": "user", "content": '仅返回 {"ok":true}。'},
]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Send exactly one cloud API request")
    args = ap.parse_args()
    directive = json.loads(DIRECTIVE.read_text(encoding="utf-8"))
    assert directive["status"] == "OWNER_DIRECTIVE_ACTIVE"
    spec = directive["cloud_primary"]
    assert spec["provider"] == "qwen" and spec["model"] == MODEL
    assert spec["key_env"] == "DASHSCOPE_API_KEY" and spec["hosted_api_only"] is True
    if not os.environ.get("DASHSCOPE_API_KEY", "").strip():
        print(json.dumps({"ok": False, "reason": "DASHSCOPE_API_KEY_MISSING"}))
        return 2
    config = {
        "provider": "qwen", "model": MODEL,
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_env": "DASHSCOPE_API_KEY", "enable_thinking": False,
        "temperature": 0, "response_format": {"type": "json_object"},
    }
    model_adapter.validate(config)
    # UTF-8 byte length + overhead pessimistically bounds the token count.
    input_bound = len(json.dumps(MESSAGES, ensure_ascii=False).encode("utf-8")) + 1024
    reserved_cny = (input_bound * INPUT_CNY_PER_M +
                    MAX_COMPLETION_TOKENS * OUTPUT_CNY_PER_M) / 1_000_000
    assert 0 < reserved_cny < SCOPE_HARD_CAP_CNY < 10
    assert float(directive["cost_guard"]["project_budget_ceiling_cny"]) == 100

    con = sqlite3.connect(LEDGER, timeout=30, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("""CREATE TABLE IF NOT EXISTS smoke_calls (
            id TEXT PRIMARY KEY, started_utc REAL NOT NULL,
            status TEXT NOT NULL, model TEXT NOT NULL,
            reserved_cny REAL NOT NULL, actual_estimate_cny REAL,
            prompt_tokens INTEGER, completion_tokens INTEGER,
            failure_type TEXT
        )""")
        if not args.execute:
            print(json.dumps({"ready": True, "provider": "qwen",
                              "model": MODEL, "cloud_only": True,
                              "max_calls": MAX_CALLS,
                              "hard_cap_cny": SCOPE_HARD_CAP_CNY,
                              "reservation_cny": round(reserved_cny, 7)}))
            return 0
        call_id = str(uuid.uuid4())
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute("SELECT COUNT(*),COALESCE(SUM(reserved_cny),0) FROM smoke_calls").fetchone()
        if int(rows[0]) >= MAX_CALLS or float(rows[1]) + reserved_cny >= SCOPE_HARD_CAP_CNY:
            con.execute("ROLLBACK")
            print(json.dumps({"ok": False, "reason": "HARD_CAP_OR_CALL_COUNT_EXHAUSTED"}))
            return 3
        con.execute(
            "INSERT INTO smoke_calls (id,started_utc,status,model,reserved_cny) VALUES (?,?,?,?,?)",
            (call_id,time.time(),"RESERVED",MODEL,reserved_cny))
        con.execute("COMMIT")
        dispatched = [False]

        def mark_dispatched() -> None:
            dispatched[0] = True
            con.execute("UPDATE smoke_calls SET status='UNKNOWN' WHERE id=? AND status='RESERVED'", (call_id,))

        try:
            result, usage = model_adapter.chat(
                config, MESSAGES, max_tokens=MAX_COMPLETION_TOKENS,
                timeout=45, on_dispatched=mark_dispatched)
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            # Preserve reserved cost if provider omits usage.
            estimate = ((prompt_tokens * INPUT_CNY_PER_M + completion_tokens *
                         OUTPUT_CNY_PER_M) / 1_000_000 if prompt_tokens and completion_tokens else reserved_cny)
            con.execute(
                "UPDATE smoke_calls SET status='COMMITTED',actual_estimate_cny=?,prompt_tokens=?,completion_tokens=? WHERE id=?",
                (estimate,prompt_tokens,completion_tokens,call_id))
            parsed = json.loads(result)
            success = parsed == {"ok": True}
            payload = {"ok": success, "provider": "qwen", "model": MODEL,
                       "transport": "dashscope_cloud_api", "cloud_only": True,
                       "response_valid": isinstance(parsed,dict),
                       "json_ok": success, "prompt_tokens": prompt_tokens,
                       "completion_tokens": completion_tokens,
                       "estimated_cost_cny": round(estimate, 8),
                       "reserved_upper_cost_cny": round(reserved_cny, 8),
                       "release_gate_pass": False,
                       "note": "Synthetic API connectivity only; no cross-model or v1 release claim"}
            OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if success else 4
        except Exception as exc:
            status = "UNKNOWN" if dispatched[0] else "PRE_SEND_ERROR"
            con.execute("UPDATE smoke_calls SET status=?,failure_type=? WHERE id=?",
                        (status,type(exc).__name__,call_id))
            payload = {"ok": False, "provider": "qwen", "model": MODEL,
                       "cloud_only": True, "status": status,
                       "reason_class": type(exc).__name__,
                       "reserved_upper_cost_cny": round(reserved_cny,8),
                       "release_gate_pass": False}
            OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
            print(json.dumps(payload, ensure_ascii=False))
            return 5
    finally:
        con.close()

if __name__ == "__main__":
    raise SystemExit(main())
