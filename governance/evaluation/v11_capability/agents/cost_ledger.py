# -*- coding: utf-8 -*-
"""Forward-only, shared PUBLIC-DEV API cost-proxy ledger.

This does NOT account for historical provider charges or protect calls that do
not use api_efficiency.cached_chat. CNY numbers use the project's established
2/8 CNY per million input/output token planning proxy, NOT a provider invoice.

Each unique dispatched request is reserved before transmission. Aborted-before-
dispatch requests release their reservation; uncertain post-dispatch requests
keep it, so an unknown result cannot silently be billed again.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DEFAULT_PROJECT_CAP_CNY = 100.0
DEFAULT_SCOPE_CAP_CNY = 9.99
INPUT_CNY_PER_MILLION = 2.0
OUTPUT_CNY_PER_MILLION = 8.0


class BudgetExceeded(RuntimeError):
    pass


def cost_cny(prompt_tokens, completion_tokens):
    return (max(0, int(prompt_tokens)) * INPUT_CNY_PER_MILLION
            + max(0, int(completion_tokens)) * OUTPUT_CNY_PER_MILLION) / 1_000_000


def reservation_cny(messages, max_tokens):
    """Conservative preflight allowance, including generated text capacity."""
    chars = len(json.dumps(messages, ensure_ascii=False))
    return cost_cny(chars + 128, int(max_tokens))


def default_scope(namespace):
    """Normalize known Agent task IDs so changing a case namespace does not reset its cap."""
    found = re.search(r"(?i)(?:^|[^a-z0-9])((?:m[1-3]|d[1-6]|a1)-x[0-9]{2,3})(?![0-9])",
                      str(namespace))
    return found.group(1).upper() if found else str(namespace)


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("""CREATE TABLE IF NOT EXISTS request_costs (
        request_key TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('RESERVED','SENT','DONE')),
        reserved_cny REAL NOT NULL,
        actual_cny REAL,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        updated_at REAL NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS request_costs_scope ON request_costs(scope)")
    return db


def reserve(path, key, scope, allowance_cny,
            project_limit_cny=DEFAULT_PROJECT_CAP_CNY,
            scope_limit_cny=DEFAULT_SCOPE_CAP_CNY,
            scope_requests_limit=None, project_requests_limit=None):
    """SQLite immediate transaction: concurrent agents cannot over-reserve."""
    assert key and scope
    assert allowance_cny >= 0
    with closing(_connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM request_costs WHERE request_key=?", (key,)).fetchone()
        if row:
            db.execute("ROLLBACK")
            raise BudgetExceeded("Request already has cost reservation: " + key[:12])
        project_total = db.execute("""SELECT COALESCE(SUM(
            CASE WHEN status='DONE' THEN actual_cny ELSE reserved_cny END), 0)
            FROM request_costs""").fetchone()[0]
        scope_total = db.execute("""SELECT COALESCE(SUM(
            CASE WHEN status='DONE' THEN actual_cny ELSE reserved_cny END), 0)
            FROM request_costs WHERE scope=?""", (scope,)).fetchone()[0]
        project_calls = db.execute("SELECT COUNT(*) FROM request_costs").fetchone()[0]
        scope_calls = db.execute(
            "SELECT COUNT(*) FROM request_costs WHERE scope=?", (scope,)
        ).fetchone()[0]
        if ((project_requests_limit is not None and project_calls >= project_requests_limit)
                or (scope_requests_limit is not None and scope_calls >= scope_requests_limit)
                or project_total + allowance_cny > project_limit_cny + 1e-9
                or scope_total + allowance_cny > scope_limit_cny + 1e-9):
            db.execute("ROLLBACK")
            raise BudgetExceeded(
                "PUBLIC DEV API proxy limit reached: scope=%s reserved=%.4f project=%.4f "
                "next_allowance=%.4f scope_cap=%.2f project_cap=%.2f"
                % (scope, scope_total, project_total, allowance_cny,
                   scope_limit_cny, project_limit_cny))
        db.execute("""INSERT INTO request_costs(
            request_key,scope,status,reserved_cny,updated_at)
            VALUES(?,?,?,?,?)""",
            (key, scope, "RESERVED", float(allowance_cny), time.time()))
        db.execute("COMMIT")


def mark_sent(path, key):
    with closing(_connect(path)) as db:
        db.execute("""UPDATE request_costs SET status='SENT',updated_at=?
            WHERE request_key=? AND status='RESERVED'""", (time.time(), key))


def release_before_dispatch(path, key):
    with closing(_connect(path)) as db:
        db.execute("DELETE FROM request_costs WHERE request_key=? AND status='RESERVED'", (key,))


def finish(path, key, usage):
    pt = int((usage or {}).get("prompt_tokens") or 0)
    ct = int((usage or {}).get("completion_tokens") or 0)
    with closing(_connect(path)) as db:
        # Unknown token usage must not be counted as free.
        row = db.execute("SELECT reserved_cny FROM request_costs WHERE request_key=?", (key,)).fetchone()
        assert row, "Missing dispatched cost reservation"
        actual = (cost_cny(pt, ct) if "prompt_tokens" in (usage or {})
                  and "completion_tokens" in (usage or {}) else float(row[0]))
        db.execute("""UPDATE request_costs SET status='DONE',
            actual_cny=?,prompt_tokens=?,completion_tokens=?,updated_at=?
            WHERE request_key=? AND status IN ('RESERVED','SENT')""",
            (actual, pt, ct, time.time(), key))


def report(path, since=None):
    path = Path(path)
    if not path.is_file():
        return {"tracked_new_calls":0, "paid_proxy_cny":0.0,
                "uncertain_reserved_cny":0.0, "scopes":{}}
    with closing(_connect(path)) as db:
        rows = db.execute("""SELECT scope,status,COUNT(*),
            COALESCE(SUM(CASE WHEN status='DONE' THEN actual_cny ELSE 0 END),0),
            COALESCE(SUM(CASE WHEN status!='DONE' THEN reserved_cny ELSE 0 END),0)
            FROM request_costs WHERE (? IS NULL OR updated_at >= ?) GROUP BY scope,status""", (since,since)).fetchall()
    scopes = {}
    paid = reserve_unknown = 0.0
    count = 0
    for scope, status, n, actual, unknown in rows:
        dst=scopes.setdefault(scope,{"requests":0,"paid_proxy_cny":0.0,
                                      "uncertain_reserved_cny":0.0,"statuses":{}})
        dst["requests"]+=n
        dst["statuses"][status]=n
        dst["paid_proxy_cny"]+=actual
        dst["uncertain_reserved_cny"]+=unknown
        count+=n;paid+=actual;reserve_unknown+=unknown
    return {"tracked_new_calls":count,"paid_proxy_cny":round(paid,6),
            "uncertain_reserved_cny":round(reserve_unknown,6),"scopes":scopes}


if __name__=="__main__":
    import argparse
    cli=argparse.ArgumentParser()
    cli.add_argument("--db",type=Path,default=Path(__file__).resolve().with_name(".api_cost_ledger.sqlite3"))
    cli.add_argument("--recent-hours",type=float,default=None,help="Report requests from the most recent N hours")
    args=cli.parse_args()
    since=(time.time()-args.recent_hours*3600 if args.recent_hours is not None else None)
    result=report(args.db,since=since)
    if args.recent_hours is not None:
        result["recent_hours"]=args.recent_hours
        result["scopes"]=dict(sorted(result["scopes"].items(),key=lambda kv:kv[1]["paid_proxy_cny"],reverse=True))
    print(json.dumps(result,ensure_ascii=False,indent=2))
