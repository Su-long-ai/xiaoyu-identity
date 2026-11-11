# -*- coding: utf-8 -*-
"""Dual-boundary freshness guard for current product context send + reply persistence."""
from __future__ import annotations
import hashlib
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

def _canonical_dump(obj):
    return json.dumps(obj,ensure_ascii=False,separators=(",",":"),sort_keys=True)

def _visible_nonmemory_hash(conn):
    def setting(key,default):
        row=conn.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        return json.loads(row[0]) if row is not None else default
    persona=setting("persona",{})
    recent=list(persona.get("growth_notes",[]) or [])[-5:]
    packed=recent
    if len(_canonical_dump(recent))>1800:
        packed=[]
        for row in recent:
            trial=packed+[row]
            if len(_canonical_dump(trial))>1800:
                break
            packed.append(row)
    state=setting("state",{})
    projection={
        "persona_section":_canonical_dump({k:persona.get(k) for k in
                                           ("name","identity_commitments","style","bond_description")})[:2800],
        "growth_section":_canonical_dump(packed),
        "state_section":_canonical_dump({k:state.get(k) for k in ("mood","hunger","energy","bond")}),
    }
    return hashlib.sha256(_canonical_dump(projection).encode("utf-8")).hexdigest()

def _token_parts(expected_generation):
    if isinstance(expected_generation,(list,tuple)) and len(expected_generation)==2:
        return int(expected_generation[0]),str(expected_generation[1])
    return int(expected_generation),None

def _validate_context_token(conn,expected_generation,expectations):
    generation,visible_hash=_token_parts(expected_generation)
    _validate_identity(conn,generation,expectations)
    if visible_hash is not None and _visible_nonmemory_hash(conn)!=visible_hash:
        raise FreshnessChanged("identity_visible_context_changed")

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

def dual_guarded_chat(
    chat_fn,config,messages,identity_db_path,r47_db_path,
    expected_generation,expectations
):
    """Revalidate and serialize both IdentityStore and selected R47 authority until dispatch."""
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
        _validate_context_token(iconn,expected_generation,expectations)
        if expectations:
            rconn=_open_locked(r47_db_path)
            _validate_r47(rconn,expectations)
        try:
            dispatch_aware="on_dispatched" in inspect.signature(chat_fn).parameters
        except (TypeError,ValueError):
            dispatch_aware=False
        if dispatch_aware:
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
        _validate_context_token(store.conn,expected_generation,expectations)
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
