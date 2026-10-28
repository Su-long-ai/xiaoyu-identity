# -*- coding: utf-8 -*-
"""Capped paid-API gateway for XiaoYu research.

Only synthetic/public benchmark material may be sent through this module.
The owner-approved token authorization is enforced with durable SQLite
reservations. Unknown outcomes remain charged until explicitly reconciled.

Cost-control additions:
- per-scope rolling raw-token / cache-miss / output / call circuit breakers;
- a single-request reservation ceiling;
- cache telemetry and CNY cost-range reporting;
- optional benchmark-phase peak-hour blocking;
- normalized budget scopes so numbered cases share one rolling guard.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model_adapter


class ResearchBudgetError(RuntimeError):
    pass


# Opaque in-process capability passed by research_api_proxy.Handler.
# This is governance provenance, not an OS security boundary.
_PROXY_AUTH_SENTINEL = object()


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ResearchBudgetError(f"Invalid JSON object: {path}")
    return data


def normalize_budget_scope(purpose: str) -> str:
    """Collapse per-case numeric variation into one durable cost-control scope."""
    raw = str(purpose or "").strip()
    if not raw:
        raise ResearchBudgetError("purpose must be non-empty")
    if raw.startswith("proxy:"):
        return raw[:120]
    # Case IDs / indexes are common cache-hostile variation. Replacing every
    # digit deliberately groups e.g. case-12, case-13 and pl_028 together.
    raw = re.sub(r"\d+", "#", raw.lower())
    chars = []
    for ch in raw:
        chars.append(ch if (ch.isalnum() or ch in "._:#-") else "_")
    norm = re.sub(r"_+", "_", "".join(chars)).strip("_")
    return ("direct:" + (norm or "research"))[:120]


def _weekday_peak_beijing(ts: float) -> bool:
    """Conservative weekday peak check; public holidays may be over-blocked."""
    dt = datetime.fromtimestamp(float(ts), timezone(timedelta(hours=8)))
    if dt.weekday() >= 5:
        return False
    return (9 <= dt.hour < 12) or (14 <= dt.hour < 18)


class ResearchApiBudget:
    def __init__(self, root: Path = ROOT, clock=time.time, transport=None):
        self.root = Path(root)
        self.gov = self.root / "governance"
        self.policy = _read_json(self.gov / "policy.json")
        self.clock = clock
        self.transport = transport or model_adapter.chat
        self.db_path = self.gov / "research_api_usage.sqlite3"
        self.conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS calls(
            call_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            finished_at REAL,
            phase TEXT NOT NULL,
            purpose TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            reserved_tokens INTEGER NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            actual_tokens INTEGER,
            cache_hit_tokens INTEGER,
            cache_miss_tokens INTEGER,
            reasoning_tokens INTEGER,
            error_class TEXT,
            budget_scope TEXT,
            request_bytes INTEGER,
            gateway_origin TEXT,
            case_id TEXT,
            prompt_prefix_sha256 TEXT
        )""")
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(calls)")}
        migrations = {
            "cache_hit_tokens": "INTEGER",
            "cache_miss_tokens": "INTEGER",
            "reasoning_tokens": "INTEGER",
            "budget_scope": "TEXT",
            "request_bytes": "INTEGER",
            "gateway_origin": "TEXT",
            "case_id": "TEXT",
            "prompt_prefix_sha256": "TEXT",
        }
        for name, typ in migrations.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE calls ADD COLUMN {name} {typ}")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_calls_scope_time ON calls(budget_scope,created_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_calls_created ON calls(created_at)"
        )

    def close(self):
        self.conn.close()

    def _cfg(self) -> dict:
        cfg = self.policy.get("budget", {}).get("paid_research")
        if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
            raise ResearchBudgetError("Paid research gateway is disabled by governance policy")
        return cfg

    def _guard_cfg(self) -> dict:
        cfg = self._cfg().get("runtime_guard") or {}
        return cfg if isinstance(cfg, dict) else {}

    @staticmethod
    def request_bytes(messages) -> int:
        return len(
            json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )

    @classmethod
    def conservative_reservation(cls, messages, max_tokens: int) -> int:
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ResearchBudgetError("max_tokens must be a positive integer")
        return cls.request_bytes(messages) + max_tokens + 1024

    def _used_locked(self, phase=None) -> int:
        if phase is None:
            row = self.conn.execute("""SELECT COALESCE(SUM(
                CASE WHEN status='COMMITTED' THEN actual_tokens
                     WHEN status IN ('RESERVED','UNKNOWN') THEN reserved_tokens
                     ELSE 0 END),0) AS n FROM calls""").fetchone()
        else:
            row = self.conn.execute("""SELECT COALESCE(SUM(
                CASE WHEN status='COMMITTED' THEN actual_tokens
                     WHEN status IN ('RESERVED','UNKNOWN') THEN reserved_tokens
                     ELSE 0 END),0) AS n FROM calls WHERE phase=?""", (phase,)).fetchone()
        return int(row["n"])

    def _scope_usage_locked(self, scope: str, since: float) -> dict:
        row = self.conn.execute(
            """SELECT
                COUNT(*) AS calls,
                COALESCE(SUM(CASE WHEN status='COMMITTED' THEN actual_tokens
                                  WHEN status IN ('RESERVED','UNKNOWN') THEN reserved_tokens
                                  ELSE 0 END),0) AS raw,
                COALESCE(SUM(CASE WHEN status='COMMITTED'
                                  THEN COALESCE(cache_miss_tokens,prompt_tokens,0)
                                  ELSE 0 END),0) AS miss,
                COALESCE(SUM(CASE WHEN status='COMMITTED'
                                  THEN COALESCE(completion_tokens,0)
                                  ELSE 0 END),0) AS output
               FROM calls
              WHERE budget_scope=? AND created_at>=?""",
            (scope, since),
        ).fetchone()
        return {k: int(row[k] or 0) for k in ("calls", "raw", "miss", "output")}

    def _e2_execution_manifest(self) -> dict | None:
        cfg=self.policy.get("e2_transition") or {}
        rel=cfg.get("pilot_execution_manifest")
        if not rel:
            return None
        path=self.root/str(rel)
        if not path.is_file():
            raise ResearchBudgetError("E2 pilot execution manifest is missing")
        raw=path.read_bytes()
        actual=__import__("hashlib").sha256(raw).hexdigest()
        expected=str(cfg.get("pilot_execution_manifest_sha256") or "")
        if not expected or actual!=expected:
            raise ResearchBudgetError("E2 pilot execution manifest hash does not match frozen policy")
        data=json.loads(raw.decode("utf-8"))
        if data.get("schema")!="xiaoyu-e2-pilot-execution-manifest-v1":
            raise ResearchBudgetError("Unsupported E2 pilot execution manifest schema")
        protocol=self.gov/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
        split=self.gov/"E2_SPLIT_MANIFEST.json"
        if not protocol.is_file() or __import__("hashlib").sha256(protocol.read_bytes()).hexdigest()!=data.get("protocol_sha256"):
            raise ResearchBudgetError("E2 protocol hash drift against execution manifest")
        if not split.is_file() or __import__("hashlib").sha256(split.read_bytes()).hexdigest()!=data.get("split_manifest_sha256"):
            raise ResearchBudgetError("E2 split hash drift against execution manifest")
        return data

    @staticmethod
    def _scope_guard_value(guard: dict, scope: str, override_key: str, base_key: str) -> int:
        overrides=guard.get("scope_overrides") or {}
        row=overrides.get(scope) if isinstance(overrides,dict) else None
        if isinstance(row,dict) and row.get(override_key) is not None:
            return int(row.get(override_key) or 0)
        return int(guard.get(base_key) or 0)

    def _pricing(self) -> dict:
        p = self._cfg().get("pricing_cny_per_million") or {}
        return p if isinstance(p, dict) else {}

    @staticmethod
    def _cost_range_from_counts(
        prompt: int, completion: int, hit: int, miss: int, pricing: dict
    ) -> dict:
        prompt = max(0, int(prompt or 0))
        completion = max(0, int(completion or 0))
        hit = max(0, int(hit or 0))
        miss = max(0, int(miss or 0))
        measured = min(prompt, hit + miss)
        unmeasured = max(0, prompt - measured)
        try:
            off_hit = float(pricing["cache_hit"]["off_peak"])
            peak_hit = float(pricing["cache_hit"]["peak"])
            off_miss = float(pricing["cache_miss"]["off_peak"])
            peak_miss = float(pricing["cache_miss"]["peak"])
            off_out = float(pricing["output"]["off_peak"])
            peak_out = float(pricing["output"]["peak"])
        except Exception:
            return {
                "available": False,
                "unmeasured_prompt_tokens": unmeasured,
            }
        lower = ((hit + unmeasured) * off_hit + miss * off_miss + completion * off_out) / 1_000_000
        upper = (hit * peak_hit + (miss + unmeasured) * peak_miss + completion * peak_out) / 1_000_000
        measured_off = (hit * off_hit + miss * off_miss + completion * off_out) / 1_000_000
        measured_peak = (hit * peak_hit + miss * peak_miss + completion * peak_out) / 1_000_000
        return {
            "available": True,
            "unmeasured_prompt_tokens": unmeasured,
            "off_peak_measured_cny": round(measured_off, 6),
            "peak_measured_cny": round(measured_peak, 6),
            "conservative_cost_range_cny": [round(lower, 6), round(upper, 6)],
        }

    def status(self) -> dict:
        cfg = self._cfg()
        total = self._used_locked()
        phase = cfg["active_phase"]
        phase_used = self._used_locked(phase)
        phase_cap = int(
            cfg["smoke_max_tokens"] if phase == "smoke" else cfg["benchmark_max_tokens"]
        )
        cache = self.conn.execute("""SELECT
            COALESCE(SUM(prompt_tokens),0) AS prompt,
            COALESCE(SUM(completion_tokens),0) AS completion,
            COALESCE(SUM(cache_hit_tokens),0) AS hit,
            COALESCE(SUM(cache_miss_tokens),0) AS miss,
            COUNT(cache_hit_tokens) AS measured
            FROM calls WHERE status='COMMITTED'""").fetchone()
        prompt = int(cache["prompt"])
        completion = int(cache["completion"])
        hit = int(cache["hit"])
        miss = int(cache["miss"])
        measured = int(cache["measured"])
        denom = hit + miss
        measured_prompt_coverage = (denom / prompt) if prompt else None
        phase_cache = self.conn.execute("""SELECT
            COALESCE(SUM(prompt_tokens),0) AS prompt,
            COALESCE(SUM(completion_tokens),0) AS completion,
            COALESCE(SUM(cache_hit_tokens),0) AS hit,
            COALESCE(SUM(cache_miss_tokens),0) AS miss,
            COUNT(cache_hit_tokens) AS measured,
            COUNT(*) AS committed
            FROM calls WHERE status='COMMITTED' AND phase=?""",(phase,)).fetchone()
        phase_prompt=int(phase_cache["prompt"] or 0)
        phase_completion=int(phase_cache["completion"] or 0)
        phase_hit=int(phase_cache["hit"] or 0)
        phase_miss=int(phase_cache["miss"] or 0)
        phase_measured=int(phase_cache["measured"] or 0)
        phase_committed=int(phase_cache["committed"] or 0)
        phase_denom=phase_hit+phase_miss
        phase_observation={
            "committed_calls":phase_committed,
            "measured_committed_calls":phase_measured,
            "prompt_tokens_total":phase_prompt,
            "completion_tokens_total":phase_completion,
            "hit_tokens":phase_hit,
            "miss_tokens":phase_miss,
            "hit_rate":round(phase_hit/phase_denom,6) if phase_denom else None,
            "measured_prompt_coverage":round(phase_denom/phase_prompt,6) if phase_prompt else None,
            "avg_prompt_tokens_per_call":round(phase_prompt/phase_committed,2) if phase_committed else None,
            "avg_completion_tokens_per_call":round(phase_completion/phase_committed,2) if phase_committed else None,
            "avg_cache_miss_tokens_per_call":round(phase_miss/phase_measured,2) if phase_measured else None,
            "note":"Current paid phase only; use this for E2 optimization rather than lifetime smoke history."
        }
        e2_cfg=self.policy.get("e2_transition") or {}
        e2_pilot_guard=None
        if e2_cfg.get("current_stage")=="E2_PILOT":
            try:
                em=self._e2_execution_manifest()
                pilot_cap=int(em.get("benchmark_pilot_hard_cap_tokens") or 0)
                allowed_scopes=[t.get("scope") for t in (em.get("tracks") or {}).values()]
                case_count=sum(int(t.get("case_count") or 0) for t in (em.get("tracks") or {}).values())
                case_rows=self.conn.execute("""SELECT
                    COUNT(*) AS calls,
                    COUNT(DISTINCT case_id) AS unique_cases,
                    SUM(CASE WHEN status='RESERVED' THEN 1 ELSE 0 END) AS reserved,
                    SUM(CASE WHEN status='UNKNOWN' THEN 1 ELSE 0 END) AS unknown
                    FROM calls WHERE phase='benchmark'""").fetchone()
                e2_pilot_guard={
                    "healthy":True,
                    "hard_cap_tokens":pilot_cap,
                    "used_or_reserved_tokens":phase_used if phase=="benchmark" else 0,
                    "remaining_tokens":max(0,pilot_cap-(phase_used if phase=="benchmark" else 0)),
                    "manifest_case_count":case_count,
                    "paid_calls":int(case_rows["calls"] or 0),
                    "unique_paid_cases":int(case_rows["unique_cases"] or 0),
                    "reserved_calls":int(case_rows["reserved"] or 0),
                    "unknown_calls":int(case_rows["unknown"] or 0),
                    "allowed_scopes":allowed_scopes,
                    "manifest_sha256":e2_cfg.get("pilot_execution_manifest_sha256"),
                    "duplicate_paid_case_forbidden":True,
                    "invariant_prefix_hash_required":True,
                }
            except Exception as exc:
                e2_pilot_guard={
                    "healthy":False,
                    "error":type(exc).__name__+":"+str(exc),
                    "hard_cap_tokens":e2_cfg.get("pilot_hard_cap_tokens"),
                }
        guard = self._guard_cfg()
        return {
            "enabled": True,
            "provider": cfg["provider"],
            "active_phase": phase,
            "benchmark_unlocked": bool(cfg.get("benchmark_unlocked", False)),
            "total_cap_tokens": int(cfg["max_total_tokens"]),
            "total_used_or_reserved_tokens": total,
            "total_remaining_tokens": max(0, int(cfg["max_total_tokens"]) - total),
            "phase_cap_tokens": phase_cap,
            "phase_used_or_reserved_tokens": phase_used,
            "phase_remaining_tokens": max(0, phase_cap - phase_used),
            "calls_by_status": {
                r["status"]: int(r["n"])
                for r in self.conn.execute(
                    "SELECT status,count(*) AS n FROM calls GROUP BY status"
                )
            },
            "phase_cache_observation": phase_observation,
            "phase_cost_estimate": self._cost_range_from_counts(
                phase_prompt, phase_completion, phase_hit, phase_miss, self._pricing()
            ),
            "e2_pilot_guard": e2_pilot_guard,
            "cache_observation": {
                "measured_committed_calls": measured,
                "prompt_tokens_total": prompt,
                "hit_tokens": hit,
                "miss_tokens": miss,
                "hit_rate": (round(hit / denom, 6) if denom else None),
                "measured_prompt_coverage": (
                    round(measured_prompt_coverage, 6)
                    if measured_prompt_coverage is not None
                    else None
                ),
                "note": "Historical calls before cache telemetry migration are excluded from hit/miss."
            },
            "cost_estimate": self._cost_range_from_counts(
                prompt, completion, hit, miss, self._pricing()
            ),
            "runtime_guard": {
                "enabled": bool(guard.get("enabled", False)),
                "effective_after_epoch": guard.get("effective_after_epoch"),
                "rolling_window_seconds": guard.get("rolling_window_seconds"),
                "scope_raw_token_cap": guard.get("scope_raw_token_cap"),
                "scope_cache_miss_cap": guard.get("scope_cache_miss_cap"),
                "scope_output_token_cap": guard.get("scope_output_token_cap"),
                "scope_call_cap": guard.get("scope_call_cap"),
                "scope_epoch_raw_token_cap": guard.get("scope_epoch_raw_token_cap"),
                "scope_epoch_cache_miss_cap": guard.get("scope_epoch_cache_miss_cap"),
                "scope_epoch_output_token_cap": guard.get("scope_epoch_output_token_cap"),
                "scope_epoch_call_cap": guard.get("scope_epoch_call_cap"),
                "max_single_reservation_tokens": guard.get("max_single_reservation_tokens"),
                "require_proxy_tag": bool(guard.get("require_proxy_tag", False)),
                "max_proxy_completion_tokens_smoke": guard.get(
                    "max_proxy_completion_tokens_smoke"
                ),
                "block_benchmark_weekday_peak": bool(
                    guard.get("block_benchmark_weekday_peak", False)
                ),
            },
        }

    def report(self, since_hours: float = 24.0, limit: int = 30) -> dict:
        if since_hours <= 0:
            raise ResearchBudgetError("since_hours must be positive")
        limit = max(1, min(int(limit), 200))
        now = float(self.clock())
        since = now - float(since_hours) * 3600.0
        rows = self.conn.execute(
            """SELECT
                 COALESCE(budget_scope,'legacy-unscoped') AS scope,
                 COUNT(*) AS calls,
                 SUM(CASE WHEN status='COMMITTED' THEN 1 ELSE 0 END) AS committed,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN actual_tokens ELSE 0 END),0) AS raw,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN prompt_tokens ELSE 0 END),0) AS prompt,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN completion_tokens ELSE 0 END),0) AS completion,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN cache_hit_tokens ELSE 0 END),0) AS hit,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN cache_miss_tokens ELSE 0 END),0) AS miss,
                 COALESCE(SUM(CASE WHEN status IN ('RESERVED','UNKNOWN') THEN reserved_tokens ELSE 0 END),0) AS open_reserved
               FROM calls
              WHERE created_at>=?
              GROUP BY COALESCE(budget_scope,'legacy-unscoped')
              ORDER BY raw DESC
              LIMIT ?""",
            (since, limit),
        ).fetchall()
        pricing = self._pricing()
        groups = []
        for row in rows:
            d = dict(row)
            for k in ("calls", "committed", "raw", "prompt", "completion", "hit", "miss", "open_reserved"):
                d[k] = int(d[k] or 0)
            den = d["hit"] + d["miss"]
            d["cache_hit_rate"] = round(d["hit"] / den, 6) if den else None
            d["measured_prompt_coverage"] = (
                round(den / d["prompt"], 6) if d["prompt"] else None
            )
            d["cost_estimate"] = self._cost_range_from_counts(
                d["prompt"], d["completion"], d["hit"], d["miss"], pricing
            )
            groups.append(d)
        totals = self.conn.execute(
            """SELECT
                 COUNT(*) AS calls,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN actual_tokens ELSE 0 END),0) AS raw,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN prompt_tokens ELSE 0 END),0) AS prompt,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN completion_tokens ELSE 0 END),0) AS completion,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN cache_hit_tokens ELSE 0 END),0) AS hit,
                 COALESCE(SUM(CASE WHEN status='COMMITTED' THEN cache_miss_tokens ELSE 0 END),0) AS miss
               FROM calls WHERE created_at>=?""",
            (since,),
        ).fetchone()
        td = {k: int(totals[k] or 0) for k in totals.keys()}
        den = td["hit"] + td["miss"]
        td["cache_hit_rate"] = round(td["hit"] / den, 6) if den else None
        td["measured_prompt_coverage"] = round(den / td["prompt"], 6) if td["prompt"] else None
        td["cost_estimate"] = self._cost_range_from_counts(
            td["prompt"], td["completion"], td["hit"], td["miss"], pricing
        )
        return {
            "since_hours": since_hours,
            "generated_at_epoch": now,
            "pricing": pricing,
            "totals": td,
            "groups": groups,
            "note": (
                "Cost range treats unmeasured prompt tokens as cache-hit at off-peak "
                "for the lower bound and cache-miss at peak for the upper bound."
            ),
        }

    def reserve(
        self,
        messages,
        max_tokens: int,
        purpose: str,
        phase: str | None = None,
        response_format=None,
        budget_scope: str | None = None,
        case_id: str | None = None,
        prompt_prefix_sha256: str | None = None,
        _proxy_auth=None,
    ) -> tuple[str, int, dict]:
        if response_format is not None and response_format != {"type": "json_object"}:
            raise ResearchBudgetError("Only response_format={type: json_object} is supported")
        cfg = self._cfg()
        active = str(cfg["active_phase"])
        phase = phase or active
        if phase != active:
            raise ResearchBudgetError(f"Only active paid phase '{active}' may run")
        if phase == "benchmark" and not cfg.get("benchmark_unlocked", False):
            raise ResearchBudgetError("Benchmark paid phase is still locked")
        if phase not in ("smoke", "benchmark"):
            raise ResearchBudgetError("Unknown paid research phase")

        now = float(self.clock())
        guard = self._guard_cfg()
        if (
            phase == "benchmark"
            and guard.get("block_benchmark_weekday_peak", False)
            and _weekday_peak_beijing(now)
        ):
            raise ResearchBudgetError(
                "Benchmark paid phase is blocked during weekday Beijing peak hours by cost policy"
            )

        purpose = str(purpose or "").strip()
        scope = str(budget_scope or normalize_budget_scope(purpose))[:120]
        if not scope:
            raise ResearchBudgetError("budget_scope must be non-empty")
        guard_active=(bool(guard.get("enabled",False))
                      and now >= float(guard.get("effective_after_epoch") or 0.0)
                      and bool(guard.get("require_proxy_tag",False)))
        is_proxy_scope=scope.startswith("proxy:")
        proxy_authenticated=(_proxy_auth is _PROXY_AUTH_SENTINEL)
        if guard_active:
            if is_proxy_scope and not proxy_authenticated:
                raise ResearchBudgetError(
                    "Proxy budget scopes may only be created by the authenticated local HTTP proxy path")
            if not is_proxy_scope:
                raise ResearchBudgetError(
                    "Direct paid research calls are forbidden while runtime_guard.require_proxy_tag=true; "
                    "use an allowlisted local-budget-proxy tag")
        gateway_origin="http_proxy" if proxy_authenticated else "direct"

        # E2 pilot execution envelope: benchmark access is restricted to the
        # frozen pilot manifest, with exact case membership, byte-stable
        # invariant prompt prefix and durable duplicate-paid-work prevention.
        e2_cfg=self.policy.get("e2_transition") or {}
        e2_manifest=None
        e2_track=None
        if phase=="benchmark" and e2_cfg.get("current_stage")=="E2_PILOT":
            e2_manifest=self._e2_execution_manifest()
            if e2_manifest is None:
                raise ResearchBudgetError("E2 pilot execution manifest is required")
            tracks=e2_manifest.get("tracks") or {}
            for _name,_track in tracks.items():
                if isinstance(_track,dict) and _track.get("scope")==scope:
                    e2_track=_track
                    break
            if e2_track is None:
                raise ResearchBudgetError(
                    f"Benchmark scope '{scope}' is not authorized by frozen E2 pilot manifest")
            case_id=str(case_id or "").strip()
            if not case_id:
                raise ResearchBudgetError("E2 benchmark case_id is required")
            allowed=set(str(x) for x in e2_track.get("case_ids",[]))
            if case_id not in allowed:
                raise ResearchBudgetError("E2 benchmark case_id is outside frozen pilot split")
            expected_prefix=str(e2_track.get("invariant_prefix_sha256") or "")
            if not expected_prefix or str(prompt_prefix_sha256 or "")!=expected_prefix:
                raise ResearchBudgetError("E2 benchmark invariant prompt prefix hash mismatch")
            cap=int(e2_track.get("max_completion_tokens") or 0)
            if cap<=0 or max_tokens>cap:
                raise ResearchBudgetError(
                    f"E2 benchmark max_tokens {max_tokens} exceeds frozen track cap {cap}")
            required_fmt=e2_track.get("response_format")
            if required_fmt is not None and response_format!=required_fmt:
                raise ResearchBudgetError("E2 benchmark response_format differs from frozen track")
            prior=self.conn.execute(
                """SELECT call_id,status FROM calls
                   WHERE phase='benchmark' AND case_id=? AND status IN ('RESERVED','COMMITTED','UNKNOWN')
                   ORDER BY created_at DESC LIMIT 1""",(case_id,)).fetchone()
            if prior is not None:
                raise ResearchBudgetError(
                    f"E2 duplicate paid case blocked: {case_id} already {prior['status']}")

        request_bytes = self.request_bytes(messages)
        reserve = self.conservative_reservation(messages, max_tokens)
        max_single = int(guard.get("max_single_reservation_tokens") or 0)
        guard_enabled = bool(guard.get("enabled", False))
        effective_after = float(guard.get("effective_after_epoch") or 0.0)
        if guard_enabled and now >= effective_after and max_single > 0 and reserve > max_single:
            raise ResearchBudgetError(
                f"Single request reservation {reserve} exceeds runtime guard cap {max_single}"
            )

        provider_cfg = model_adapter.load_provider(self.root)
        if provider_cfg["provider"] != cfg["provider"]:
            raise ResearchBudgetError("Provider config does not match paid research policy")
        provider_cfg["thinking"] = str(cfg.get("thinking") or "disabled")
        provider_cfg["reasoning_effort"] = str(cfg.get("reasoning_effort") or "none")
        provider_cfg["temperature"] = float(cfg.get("temperature", 0.0))
        provider_cfg["top_p"] = float(cfg.get("top_p", 1.0))
        if response_format is not None:
            provider_cfg["response_format"] = {"type": "json_object"}

        call_id = "api-" + uuid.uuid4().hex
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # Authoritative duplicate check under the SQLite write lock. The
            # earlier check is only a fast failure path; this closes two-process
            # check-then-insert races.
            if phase=="benchmark" and e2_cfg.get("current_stage")=="E2_PILOT":
                prior=self.conn.execute(
                    """SELECT call_id,status FROM calls
                       WHERE phase='benchmark' AND case_id=?
                         AND status IN ('RESERVED','COMMITTED','UNKNOWN')
                       ORDER BY created_at DESC LIMIT 1""",(case_id,)).fetchone()
                if prior is not None:
                    raise ResearchBudgetError(
                        f"E2 duplicate paid case blocked atomically: {case_id} already {prior['status']}")
                warmup_n=int((e2_manifest or {}).get("warmup",{}).get(
                    "serial_real_cases_per_scope") or 0)
                if warmup_n>0:
                    committed_scope=int(self.conn.execute(
                        "SELECT count(*) FROM calls WHERE phase='benchmark' AND budget_scope=? AND status='COMMITTED'",
                        (scope,)).fetchone()[0])
                    reserved_scope=int(self.conn.execute(
                        "SELECT count(*) FROM calls WHERE phase='benchmark' AND budget_scope=? AND status='RESERVED'",
                        (scope,)).fetchone()[0])
                    if committed_scope < warmup_n and reserved_scope>0:
                        raise ResearchBudgetError(
                            f"E2 cache warmup requires serial execution for first {warmup_n} committed cases in scope '{scope}'")
            parallel_cap=int(self.policy.get("budget",{}).get("max_parallel_experiments") or 0)
            if parallel_cap>0:
                reserved_now=int(self.conn.execute(
                    "SELECT count(*) FROM calls WHERE status='RESERVED'").fetchone()[0])
                if reserved_now>=parallel_cap:
                    raise ResearchBudgetError(
                        f"Paid research parallel reservation cap reached ({reserved_now} >= {parallel_cap})")
            total = self._used_locked()
            phase_used = self._used_locked(phase)
            max_calls = int(self.policy.get("budget", {}).get("max_paid_api_calls_per_day") or 0)
            if max_calls > 0:
                since = now - 86400.0
                recent_calls = int(
                    self.conn.execute(
                        "SELECT count(*) FROM calls WHERE created_at>=?", (since,)
                    ).fetchone()[0]
                )
                if recent_calls >= max_calls:
                    raise ResearchBudgetError("Rolling 24h paid API call cap would be exceeded")

            total_cap = int(cfg["max_total_tokens"])
            phase_cap = int(
                cfg["smoke_max_tokens"] if phase == "smoke" else cfg["benchmark_max_tokens"]
            )
            if total + reserve > total_cap:
                raise ResearchBudgetError("Phase-1 total token budget would be exceeded")
            if phase_used + reserve > phase_cap:
                raise ResearchBudgetError(f"{phase} token budget would be exceeded")
            if phase=="benchmark" and e2_cfg.get("current_stage")=="E2_PILOT":
                pilot_cap=int((e2_manifest or {}).get("benchmark_pilot_hard_cap_tokens") or
                              e2_cfg.get("pilot_hard_cap_tokens") or 0)
                if pilot_cap<=0:
                    raise ResearchBudgetError("E2 pilot hard token cap is missing")
                if phase_used + reserve > pilot_cap:
                    raise ResearchBudgetError(
                        f"E2 pilot token cap would be exceeded ({phase_used} + {reserve} > {pilot_cap})")

            if guard_enabled and now >= effective_after:
                window = max(1, int(guard.get("rolling_window_seconds") or 900))
                since = max(effective_after, now - window)
                usage = self._scope_usage_locked(scope, since)
                raw_cap = self._scope_guard_value(guard,scope,"rolling_raw_token_cap","scope_raw_token_cap")
                miss_cap = self._scope_guard_value(guard,scope,"rolling_cache_miss_cap","scope_cache_miss_cap")
                output_cap = self._scope_guard_value(guard,scope,"rolling_output_token_cap","scope_output_token_cap")
                call_cap = self._scope_guard_value(guard,scope,"rolling_call_cap","scope_call_cap")
                if raw_cap > 0 and usage["raw"] + reserve > raw_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' rolling raw-token guard would be exceeded "
                        f"({usage['raw']} + reservation {reserve} > {raw_cap})"
                    )
                if miss_cap > 0 and usage["miss"] >= miss_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' rolling cache-miss guard reached "
                        f"({usage['miss']} >= {miss_cap})"
                    )
                if output_cap > 0 and usage["output"] >= output_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' rolling output-token guard reached "
                        f"({usage['output']} >= {output_cap})"
                    )
                if call_cap > 0 and usage["calls"] >= call_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' rolling call guard reached "
                        f"({usage['calls']} >= {call_cap})"
                    )

                epoch_usage = self._scope_usage_locked(scope, effective_after)
                epoch_raw_cap = self._scope_guard_value(guard,scope,"epoch_raw_token_cap","scope_epoch_raw_token_cap")
                epoch_miss_cap = self._scope_guard_value(guard,scope,"epoch_cache_miss_cap","scope_epoch_cache_miss_cap")
                epoch_output_cap = self._scope_guard_value(guard,scope,"epoch_output_token_cap","scope_epoch_output_token_cap")
                epoch_call_cap = self._scope_guard_value(guard,scope,"epoch_call_cap","scope_epoch_call_cap")
                if epoch_raw_cap > 0 and epoch_usage["raw"] + reserve > epoch_raw_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' epoch raw-token guard would be exceeded "
                        f"({epoch_usage['raw']} + reservation {reserve} > {epoch_raw_cap})"
                    )
                if epoch_miss_cap > 0 and epoch_usage["miss"] >= epoch_miss_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' epoch cache-miss guard reached "
                        f"({epoch_usage['miss']} >= {epoch_miss_cap})"
                    )
                if epoch_output_cap > 0 and epoch_usage["output"] >= epoch_output_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' epoch output-token guard reached "
                        f"({epoch_usage['output']} >= {epoch_output_cap})"
                    )
                if epoch_call_cap > 0 and epoch_usage["calls"] >= epoch_call_cap:
                    raise ResearchBudgetError(
                        f"Scope '{scope}' epoch call guard reached "
                        f"({epoch_usage['calls']} >= {epoch_call_cap})"
                    )

            self.conn.execute(
                """INSERT INTO calls(
                    call_id,created_at,phase,purpose,provider,model,status,reserved_tokens,
                    budget_scope,request_bytes,gateway_origin,case_id,prompt_prefix_sha256)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    call_id,
                    now,
                    phase,
                    purpose[:200],
                    provider_cfg["provider"],
                    provider_cfg["model"],
                    "RESERVED",
                    reserve,
                    scope,
                    request_bytes,
                    gateway_origin,
                    case_id,
                    prompt_prefix_sha256,
                ),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return call_id, reserve, provider_cfg

    def finalize(self, call_id: str, usage: dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        cache_hit = usage.get("prompt_cache_hit_tokens")
        cache_miss = usage.get("prompt_cache_miss_tokens")
        details = usage.get("prompt_tokens_details") or {}
        if cache_hit is None and isinstance(details, dict):
            cache_hit = details.get("cached_tokens")
        cache_hit = int(cache_hit) if cache_hit is not None else None
        cache_miss = int(cache_miss) if cache_miss is not None else None
        completion_details = usage.get("completion_tokens_details") or {}
        reasoning = (
            int(completion_details.get("reasoning_tokens") or 0)
            if isinstance(completion_details, dict)
            else 0
        )
        if (
            total < 0
            or prompt < 0
            or completion < 0
            or (cache_hit is not None and cache_hit < 0)
            or (cache_miss is not None and cache_miss < 0)
        ):
            raise ResearchBudgetError("Provider returned invalid token usage")
        if (
            cache_hit is not None
            and cache_miss is not None
            and cache_hit + cache_miss != prompt
        ):
            raise ResearchBudgetError("Provider cache accounting does not match prompt_tokens")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT * FROM calls WHERE call_id=?", (call_id,)
            ).fetchone()
            if row is None or row["status"] != "RESERVED":
                raise ResearchBudgetError("Call reservation is not active")
            if total > int(row["reserved_tokens"]):
                self.conn.execute(
                    """UPDATE calls SET status='UNKNOWN',finished_at=?,
                    error_class='USAGE_EXCEEDED_RESERVATION' WHERE call_id=?""",
                    (float(self.clock()), call_id),
                )
                self.conn.execute("COMMIT")
                raise ResearchBudgetError(
                    "Provider usage exceeded conservative reservation"
                )
            self.conn.execute(
                """UPDATE calls SET status='COMMITTED',finished_at=?,
                prompt_tokens=?,completion_tokens=?,actual_tokens=?,
                cache_hit_tokens=?,cache_miss_tokens=?,reasoning_tokens=?
                WHERE call_id=?""",
                (
                    float(self.clock()),
                    prompt,
                    completion,
                    total,
                    cache_hit,
                    cache_miss,
                    reasoning,
                    call_id,
                ),
            )
            self.conn.execute("COMMIT")
        except Exception:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    def mark_unknown(self, call_id: str, error: Exception):
        self.conn.execute(
            """UPDATE calls SET status='UNKNOWN',finished_at=?,error_class=?
            WHERE call_id=? AND status='RESERVED'""",
            (float(self.clock()), type(error).__name__[:100], call_id),
        )

    def chat(
        self,
        messages,
        *,
        max_tokens=500,
        purpose="research",
        timeout=75,
        phase=None,
        response_format=None,
        budget_scope=None,
        case_id=None,
        prompt_prefix_sha256=None,
        _proxy_auth=None,
    ):
        call_id, reserved, provider_cfg = self.reserve(
            messages,
            max_tokens,
            purpose,
            phase,
            response_format=response_format,
            budget_scope=budget_scope,
            case_id=case_id,
            prompt_prefix_sha256=prompt_prefix_sha256,
            _proxy_auth=_proxy_auth,
        )
        try:
            response, usage = self.transport(
                provider_cfg, messages, max_tokens=max_tokens, timeout=timeout
            )
            self.finalize(call_id, usage)
            return response, usage, call_id
        except Exception as exc:
            self.mark_unknown(call_id, exc)
            raise


def _main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    report = sub.add_parser("report")
    report.add_argument("--hours", type=float, default=24.0)
    report.add_argument("--limit", type=int, default=30)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--max-tokens", type=int, default=8)
    args = ap.parse_args()
    b = ResearchApiBudget()
    try:
        if args.command == "status":
            print(json.dumps(b.status(), ensure_ascii=False, indent=2))
            return
        if args.command == "report":
            print(
                json.dumps(
                    b.report(since_hours=args.hours, limit=args.limit),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        response, usage, call_id = b.chat(
            [{"role": "user", "content": "Synthetic connectivity test. Reply with exactly: OK"}],
            max_tokens=args.max_tokens,
            purpose="T05 synthetic DeepSeek connectivity smoke",
            phase="smoke",
            budget_scope="direct:t05_connectivity",
        )
        print(
            json.dumps(
                {
                    "ok": response.strip() == "OK",
                    "response": response[:40],
                    "usage": usage,
                    "call_id": call_id,
                    "budget": b.status(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        b.close()


if __name__ == "__main__":
    _main()
