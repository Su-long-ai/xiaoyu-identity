#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3.8-Flash judge ledger for the RMB50 HaluMem dev gate.

This is intentionally separate from the formal confirmatory judge ledger.
No call is allowed until the dev prediction is sealed and a score manifest
binds the exact wrapper, official prompt code, 51 QA inputs and call cap.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
FROZEN = GOV / "confirmatory_frozen"
RUNTIME = GOV / "budget50_halumem_dev_runtime_v1"
BINDING = FROZEN / "HALUMEM_JUDGE_BINDING.json"
SCORE_MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_SCORE_V1.json"
PREDICTION_SEAL = RUNTIME / "PREDICTION_SEAL.json"
LEDGER = RUNTIME / "judge_ledger_qwen38_flash_dev_v1.sqlite3"
THIS = Path(__file__).resolve()


class DevJudgeError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding() -> dict:
    b = json.loads(BINDING.read_text("utf-8"))
    j = b.get("judge") or {}
    if b.get("schema") != "xiaoyu-halumem-final-judge-binding-v2":
        raise DevJudgeError("judge binding schema drift")
    if j.get("provider") != "alibaba_model_studio" or j.get("model_id") != "qwen3.8-flash":
        raise DevJudgeError("judge provider/model drift")
    if float(j.get("temperature")) != 0.0 or int(j.get("max_tokens")) != 16384:
        raise DevJudgeError("judge config drift")
    if j.get("enable_thinking") is not False or j.get("substitution_allowed") is not False:
        raise DevJudgeError("judge thinking/substitution drift")
    return b


def _authorization() -> dict:
    if not PREDICTION_SEAL.is_file():
        raise DevJudgeError("dev prediction seal required before judge access")
    if not SCORE_MANIFEST.is_file():
        raise DevJudgeError("dev score manifest required")
    m = json.loads(SCORE_MANIFEST.read_text("utf-8"))
    if m.get("schema") != "xiaoyu-budget50-halumem-dev-score-v1":
        raise DevJudgeError("dev score manifest schema drift")
    if m.get("status") != "READY_FOR_QA_SCORING":
        raise DevJudgeError("dev score manifest not authorized")
    if (m.get("implementation") or {}).get("judge_wrapper_sha256") != sha(THIS):
        raise DevJudgeError("dev judge wrapper byte drift")
    if m.get("prediction_seal_sha256") != sha(PREDICTION_SEAL):
        raise DevJudgeError("dev prediction seal binding drift")
    if (m.get("judge") or {}).get("binding_sha256") != sha(BINDING):
        raise DevJudgeError("dev judge binding hash drift")
    return m


def _parse_json_block(content: str) -> dict:
    m = re.search(r"```json\s*(\{.*?\})\s*```", str(content or ""), re.DOTALL)
    if not m:
        raise DevJudgeError("No JSON block found in judge output")
    try:
        obj = json.loads(m.group(1).strip())
    except Exception as exc:
        raise DevJudgeError("invalid JSON block from judge") from exc
    if not isinstance(obj, dict):
        raise DevJudgeError("judge JSON is not object")
    return obj


def _db():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LEDGER, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS judge_calls(
        prompt_sha256 TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        model TEXT NOT NULL,
        binding_sha256 TEXT NOT NULL,
        response_json TEXT,
        response_text TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        error TEXT)"""
    )
    return con


def llm_request_for_json(prompt):
    manifest = _authorization()
    binding = _binding()
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise DevJudgeError("DASHSCOPE_API_KEY missing")
    base_url = os.getenv("DASHSCOPE_BASE_URL") or binding["runtime"]["default_base_url"]
    prompt = str(prompt)
    psha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    bsha = sha(BINDING)
    model = binding["judge"]["model_id"]
    cap = int((manifest.get("judge") or {}).get("max_total_calls") or 0)
    if cap != 63:
        raise DevJudgeError("dev judge call cap must be exactly 63")

    con = _db()
    try:
        row = con.execute("SELECT * FROM judge_calls WHERE prompt_sha256=?", (psha,)).fetchone()
        if row is not None:
            if row["binding_sha256"] != bsha or row["model"] != model:
                raise DevJudgeError("judge receipt binding drift")
            if row["status"] == "COMMITTED":
                return json.loads(row["response_json"])
            raise DevJudgeError(f"judge prompt already {row['status']}; paid retry forbidden")

        count = int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])
        if count >= cap:
            raise DevJudgeError("dev judge call cap exhausted")

        now = time.time()
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute("SELECT status FROM judge_calls WHERE prompt_sha256=?", (psha,)).fetchone()
            if row is not None:
                raise DevJudgeError(f"judge prompt concurrently {row['status']}")
            count = int(con.execute("SELECT count(*) FROM judge_calls").fetchone()[0])
            if count >= cap:
                raise DevJudgeError("dev judge call cap exhausted")
            con.execute(
                """INSERT INTO judge_calls(
                   prompt_sha256,status,model,binding_sha256,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                (psha, "RESERVED", model, bsha, now, now),
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        try:
            client = OpenAI(api_key=key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=16384,
                extra_body={"enable_thinking": False},
            )
            content = resp.choices[0].message.content or ""
            obj = _parse_json_block(content)
            usage = getattr(resp, "usage", None)
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            tt = int(getattr(usage, "total_tokens", pt + ct) or (pt + ct))
        except Exception as exc:
            con.execute(
                "UPDATE judge_calls SET status='UNKNOWN',updated_at=?,error=? WHERE prompt_sha256=?",
                (time.time(), type(exc).__name__ + ":" + str(exc), psha),
            )
            raise

        con.execute(
            """UPDATE judge_calls SET status='COMMITTED',response_json=?,response_text=?,
               prompt_tokens=?,completion_tokens=?,total_tokens=?,updated_at=?,error=NULL
               WHERE prompt_sha256=?""",
            (
                json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                content,
                pt,
                ct,
                tt,
                time.time(),
                psha,
            ),
        )
        return obj
    finally:
        con.close()


def llm_request(prompt):
    raise DevJudgeError("raw judge text path is not authorized")


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "model": "qwen3.8-flash",
                "ledger": str(LEDGER),
                "authorized": False,
                "note": "Requires sealed dev predictions and BUDGET50_HALUMEM_DEV_SCORE_V1.json",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
