# -*- coding: utf-8 -*-
"""Dual-boundary freshness guard for current product context send + reply persistence."""
from __future__ import annotations
import inspect
import json
import sqlite3

class FreshnessChanged(RuntimeError):
    pass

def _generation(conn) -> int:
    row=conn.execute("SELECT value FROM settings WHERE key='memory_change_seq'").fetchone()
    if row is not None:
        return int(json.loads(row[0]))
    row=conn.execute("SELECT COALESCE(MAX(change_seq),0) FROM memories").fetchone()
    return int(row[0] or 0)

def capture_expectations(bridge, rows):
    out=[]
    if bridge is None:
        return out
    for row in rows:
        mid=int(row["memory_id"])
        out.append({
            "memory_id":mid,
            "text":str(row["text"]),
            "source_message_id":bridge._r47.source_message_id(
                "xiaoyu-product-confirmed-memory",f"memory-{mid}"
            ),
        })
    return out

def _validate_identity(conn, expected_generation, expectations):
    current=_generation(conn)
    if int(current)!=int(expected_generation):
        raise FreshnessChanged(
            f"identity_generation_changed:{expected_generation}->{current}"
        )
    if not expectations:
        return
    ids=[int(x["memory_id"]) for x in expectations]
    marks=",".join("?" for _ in ids)
    rows={
        int(r[0]):(str(r[1]),str(r[2]))
        for r in conn.execute(
            f"SELECT memory_id,text,status FROM memories WHERE memory_id IN ({marks})",
            ids,
        )
    }
    for x in expectations:
        got=rows.get(int(x["memory_id"]))
        if got!=(str(x["text"]),"active"):
            raise FreshnessChanged("identity_selected_memory_changed")

def _validate_r47(conn, expectations):
    if not expectations:
        return
    sids=[str(x["source_message_id"]) for x in expectations]
    marks=",".join("?" for _ in sids)
    rows=conn.execute(
        f"""SELECT s.source_message_id,s.lifecycle,
                   c.claim_id,c.claim_text,c.source_role,c.authority_base,
                   c.relation_kind,c.status
            FROM source_messages s
            LEFT JOIN claims c ON c.source_message_id=s.source_message_id
            WHERE s.source_message_id IN ({marks})
            ORDER BY s.source_message_id,c.ordinal,c.created_order""",
        sids,
    ).fetchall()
    by_sid={sid:[] for sid in sids}
    life={}
    for r in rows:
        sid=str(r[0])
        life[sid]=str(r[1])
        if r[2] is not None:
            by_sid.setdefault(sid,[]).append(r)

    claim_for_sid={}
    for x in expectations:
        sid=str(x["source_message_id"])
        cs=by_sid.get(sid,[])
        if life.get(sid)!="active":
            raise FreshnessChanged("r47_source_not_active")
        if len(cs)!=1:
            raise FreshnessChanged("r47_claim_cardinality_changed")
        c=cs[0]
        if not (
            str(c[3])==str(x["text"])
            and str(c[4])=="user"
            and str(c[5])=="user_assertion"
            and str(c[6])=="NEW"
            and str(c[7])=="active"
        ):
            raise FreshnessChanged("r47_claim_authority_changed")
        claim_for_sid[sid]=str(c[2])

    cids=list(claim_for_sid.values())
    cm=",".join("?" for _ in cids)
    q=f"""SELECT cr.child_claim_id,cr.parent_claim_id
          FROM claim_relations cr
          JOIN claims a ON a.claim_id=cr.child_claim_id
          JOIN claims b ON b.claim_id=cr.parent_claim_id
          WHERE cr.relation='CONFLICTS'
            AND a.status='active' AND b.status='active'
            AND a.source_role='user' AND b.source_role='user'
            AND (cr.child_claim_id IN ({cm}) OR cr.parent_claim_id IN ({cm}))"""
    conflicted=set()
    for edge in conn.execute(q,cids+cids):
        conflicted.add(str(edge[0])); conflicted.add(str(edge[1]))
    if any(cid in conflicted for cid in cids):
        raise FreshnessChanged("r47_selected_claim_conflicted")

def _open_locked(path):
    conn=sqlite3.connect(str(path),timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("BEGIN IMMEDIATE")
    return conn

def _close_lock(conn):
    if conn is None:
        return
    try:
        if conn.in_transaction:
            conn.rollback()
    finally:
        conn.close()

class _FreshAttemptGuard:
    """Revalidate protected context independently for one provider attempt."""
    def __init__(
        self,
        identity_db_path,
        r47_db_path,
        expected_generation,
        expectations,
    ):
        self.identity_db_path=identity_db_path
        self.r47_db_path=r47_db_path
        self.expected_generation=expected_generation
        self.expectations=expectations
        self.iconn=None
        self.rconn=None
        self.released=False

    def __enter__(self):
        try:
            self.iconn=_open_locked(self.identity_db_path)
            _validate_identity(
                self.iconn,
                self.expected_generation,
                self.expectations,
            )
            if self.expectations:
                self.rconn=_open_locked(self.r47_db_path)
                _validate_r47(
                    self.rconn,
                    self.expectations,
                )
            return self
        except Exception:
            self.release()
            raise

    def release(self):
        if self.released:
            return
        self.released=True
        _close_lock(self.rconn)
        self.rconn=None
        _close_lock(self.iconn)
        self.iconn=None

    def on_dispatched(self):
        self.release()

    def __exit__(self,exc_type,exc,tb):
        self.release()
        return False


def dual_guarded_chat(
    chat_fn,config,messages,identity_db_path,r47_db_path,
    expected_generation,expectations
):
    """Revalidate protected context at every concrete provider attempt."""
    try:
        parameters=inspect.signature(chat_fn).parameters
    except (TypeError,ValueError):
        parameters={}

    # New adapter path: each primary/fallback attempt gets a fresh lock and
    # validation window.  If authority changes after one provider dispatch,
    # the next guard fails before any bytes are sent to another provider.
    if "attempt_guard" in parameters:
        def guard_factory(candidate):
            return _FreshAttemptGuard(
                identity_db_path,
                r47_db_path,
                expected_generation,
                expectations,
            )
        kwargs={"attempt_guard":guard_factory}
        if "required_data_class" in parameters:
            kwargs["required_data_class"]="OWNER_PRIVATE"
        return chat_fn(config,messages,**kwargs)

    # Compatibility path for chat implementations that only expose the old
    # single-dispatch callback.  They cannot safely support multiple guarded
    # provider attempts, so validate/serialize exactly as before.
    iconn=rconn=None
    released=False
    def release():
        nonlocal released,iconn,rconn
        if released:
            return
        released=True
        _close_lock(rconn); rconn=None
        _close_lock(iconn); iconn=None
    try:
        iconn=_open_locked(identity_db_path)
        _validate_identity(iconn,expected_generation,expectations)
        if expectations:
            rconn=_open_locked(r47_db_path)
            _validate_r47(rconn,expectations)
        if "on_dispatched" in parameters:
            return chat_fn(config,messages,on_dispatched=release)
        return chat_fn(config,messages)
    finally:
        release()

def persist_assistant_if_fresh(
    store,bridge,expected_generation,expectations,content
):
    """Atomically validate final context freshness and persist the normal assistant event."""
    if store.conn.in_transaction:
        raise RuntimeError("assistant_freshness_requires_clean_identity_transaction")
    rconn=None
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        _validate_identity(store.conn,expected_generation,expectations)
        if expectations:
            rconn=_open_locked(bridge.db_path)
            _validate_r47(rconn,expectations)
        if len(str(content)) > 30000:
            raise ValueError("Event too large")
        event_id=store._insert_event("conversation.assistant","assistant",content)
        store.conn.commit()
        return int(event_id)
    except Exception:
        if store.conn.in_transaction:
            store.conn.rollback()
        raise
    finally:
        _close_lock(rconn)
