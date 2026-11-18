# -*- coding: utf-8 -*-
"""Dual-boundary freshness guard for current product context send + reply persistence."""
from __future__ import annotations
import hashlib
import inspect
import json
import sqlite3

from xiaoyu.runtime.provider_registry import PrivacyClass, ProviderAttemptContext

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

def _messages_digest(messages):
    payload=json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return "sha256:"+hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context_fence(conn):
    settings={
        str(row[0]):str(row[1])
        for row in conn.execute(
            "SELECT key,value FROM settings "
            "WHERE key IN ('persona','state','memory_change_seq') ORDER BY key"
        )
    }
    event_row=conn.execute(
        "SELECT COALESCE(MAX(event_id),0),COUNT(*) FROM events"
    ).fetchone()
    memory_row=conn.execute(
        """SELECT COUNT(*),
                  COALESCE(MAX(memory_id),0),
                  COALESCE(MAX(change_seq),0),
                  COALESCE(SUM(memory_id),0),
                  COALESCE(SUM(CASE WHEN status='active' THEN 1 ELSE 0 END),0)
           FROM memories"""
    ).fetchone()
    payload={
        "settings":settings,
        "event_max_id":int(event_row[0] or 0),
        "event_count":int(event_row[1] or 0),
        "memory_count":int(memory_row[0] or 0),
        "memory_max_id":int(memory_row[1] or 0),
        "memory_max_change_seq":int(memory_row[2] or 0),
        "memory_id_sum":int(memory_row[3] or 0),
        "memory_active_count":int(memory_row[4] or 0),
    }
    return _messages_digest(payload)


def capture_context_fence(store_or_conn):
    conn=getattr(store_or_conn,"conn",store_or_conn)
    return _context_fence(conn)


def _validate_context_state_snapshot(
    provider,
    *,
    identity_id,
    principal_id,
    audience_scope,
    context_space,
    authorization_digest,
    routing_policy_digest,
    tool_result_digest,
    tool_implementation_digest,
    tool_schema_digest,
    viewer_principal_ids=(),
):
    if provider is None:
        return
    current=dict(provider() or {})
    expected={
        "identity_id":str(identity_id),
        "principal_id":str(principal_id),
        "audience_scope":str(audience_scope),
        "context_space":str(context_space),
        "authorization_digest":authorization_digest,
        "routing_policy_digest":routing_policy_digest,
        "tool_result_digest":tool_result_digest,
        "tool_implementation_digest":tool_implementation_digest,
        "tool_schema_digest":tool_schema_digest,
    }
    viewers=tuple(sorted(
        str(value) for value in viewer_principal_ids if str(value)
    ))
    current_viewers=tuple(sorted(
        str(value)
        for value in current.get("viewer_principal_ids", ())
        if str(value)
    ))
    if current_viewers != viewers:
        raise FreshnessChanged(
            "attempt_context_changed:viewer_principal_ids"
        )
    for key,value in expected.items():
        if current.get(key) != value:
            raise FreshnessChanged("attempt_context_changed:"+key)


class _FreshAttemptGuard:
    """Revalidate protected context independently for one provider attempt."""
    def __init__(
        self,
        identity_db_path,
        r47_db_path,
        expected_generation,
        expectations,
        expected_messages_digest,
        expected_context_fence,
        identity_id,
        principal_id,
        owner_principal_id,
        audience_scope,
        context_space,
        required_privacy_class,
        authorization_digest,
        routing_policy_digest,
        tool_result_digest,
        tool_implementation_digest,
        tool_schema_digest,
        source_contains_private_tool_result,
        context_state_provider,
        approved_provider_digests,
        viewer_principal_ids=(),
    ):
        self.identity_db_path=identity_db_path
        self.r47_db_path=r47_db_path
        self.expected_generation=expected_generation
        self.expectations=expectations
        self.expected_messages_digest=expected_messages_digest
        self.expected_context_fence=expected_context_fence
        self.identity_id=str(identity_id)
        self.principal_id=str(principal_id)
        self.owner_principal_id=(
            None if owner_principal_id is None else str(owner_principal_id)
        )
        self.audience_scope=str(audience_scope)
        self.context_space=str(context_space)
        self.required_privacy_class=str(required_privacy_class or "PUBLIC").upper()
        self.authorization_digest=authorization_digest
        self.routing_policy_digest=routing_policy_digest
        self.tool_result_digest=tool_result_digest
        self.tool_implementation_digest=tool_implementation_digest
        self.tool_schema_digest=tool_schema_digest
        self.source_contains_private_tool_result=bool(source_contains_private_tool_result)
        self.context_state_provider=context_state_provider
        self.approved_provider_digests=dict(approved_provider_digests or {})
        self.viewer_principal_ids=tuple(sorted(
            str(value) for value in viewer_principal_ids if str(value)
        ))
        self.iconn=None
        self.rconn=None
        self.released=False

    def _validate_context_state(self):
        _validate_context_state_snapshot(
            self.context_state_provider,
            identity_id=self.identity_id,
            principal_id=self.principal_id,
            audience_scope=self.audience_scope,
            context_space=self.context_space,
            authorization_digest=self.authorization_digest,
            routing_policy_digest=self.routing_policy_digest,
            tool_result_digest=self.tool_result_digest,
            tool_implementation_digest=self.tool_implementation_digest,
            tool_schema_digest=self.tool_schema_digest,
            viewer_principal_ids=self.viewer_principal_ids,
        )

    def __enter__(self):
        try:
            self._validate_context_state()
            self.iconn=_open_locked(self.identity_db_path)
            _validate_identity(self.iconn,self.expected_generation,self.expectations)
            if (
                self.expected_context_fence is not None
                and _context_fence(self.iconn) != self.expected_context_fence
            ):
                raise FreshnessChanged("identity_context_fence_changed")
            if self.expectations:
                self.rconn=_open_locked(self.r47_db_path)
                _validate_r47(self.rconn,self.expectations)
            if self.source_contains_private_tool_result and not self.tool_result_digest:
                raise FreshnessChanged("private_tool_result_requires_fresh_digest")
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

    def messages_for_attempt(self,messages):
        if _messages_digest(messages) != self.expected_messages_digest:
            raise FreshnessChanged("captured_messages_changed")
        return json.loads(json.dumps(messages,ensure_ascii=False))

    def provider_attempt_context(self,descriptor,required_data_class=None):
        approved=self.approved_provider_digests.get(descriptor.provider_id,{})
        privacy=str(required_data_class or self.required_privacy_class or "PUBLIC").upper()
        try:
            privacy_class=PrivacyClass(privacy)
        except ValueError:
            privacy_class=PrivacyClass.PUBLIC
        return ProviderAttemptContext(
            identity_id=self.identity_id,
            principal_id=self.principal_id,
            audience_scope=self.audience_scope,
            context_space=self.context_space,
            context_generation=str(
                self.expected_context_fence or self.expected_generation
            ),
            provider_id=descriptor.provider_id,
            required_capability="chat.completion",
            required_privacy_class=privacy_class,
            provider_descriptor_digest=descriptor.descriptor_digest,
            provider_capability_digest=descriptor.capability_digest,
            provider_implementation_digest=descriptor.implementation_digest,
            owner_principal_id=self.owner_principal_id,
            routing_policy_digest=self.routing_policy_digest,
            expected_descriptor_digest=approved.get("descriptor_digest"),
            expected_capability_digest=approved.get("capability_digest"),
            expected_approval_binding_digest=approved.get("approval_binding_digest"),
            authorization_digest=self.authorization_digest,
            tool_result_digest=self.tool_result_digest,
            tool_implementation_digest=self.tool_implementation_digest,
            tool_schema_digest=self.tool_schema_digest,
            source_contains_private_tool_result=self.source_contains_private_tool_result,
            viewer_principal_ids=self.viewer_principal_ids,
        )

    def on_response(self):
        iconn=rconn=None
        try:
            self._validate_context_state()
            iconn=_open_locked(self.identity_db_path)
            _validate_identity(iconn,self.expected_generation,self.expectations)
            if (
                self.expected_context_fence is not None
                and _context_fence(iconn) != self.expected_context_fence
            ):
                raise FreshnessChanged("identity_context_fence_changed")
            if self.expectations:
                rconn=_open_locked(self.r47_db_path)
                _validate_r47(rconn,self.expectations)
        finally:
            _close_lock(rconn)
            _close_lock(iconn)

    def __exit__(self,exc_type,exc,tb):
        self.release()
        return False


def dual_guarded_chat(
    chat_fn,config,messages,identity_db_path,r47_db_path,
    expected_generation,expectations,
    *,
    max_tokens=500,
    timeout=75,
    expected_context_fence=None,
    identity_id="xiaoyu",
    principal_id="owner",
    owner_principal_id="owner",
    audience_scope="PRIVATE",
    context_space="PERSONAL",
    required_privacy_class="OWNER_PRIVATE",
    authorization_digest=None,
    routing_policy_digest=None,
    tool_result_digest=None,
    tool_implementation_digest=None,
    tool_schema_digest=None,
    source_contains_private_tool_result=False,
    context_state_provider=None,
    approved_provider_digests=None,
    attempt_audit=None,
    provider_health=None,
    viewer_principal_ids=(),
):
    """Revalidate protected context at every concrete provider attempt."""
    viewers=tuple(sorted(
        str(value) for value in viewer_principal_ids if str(value)
    ))
    privacy_value=str(required_privacy_class).upper()
    if (
        privacy_value == "OWNER_PRIVATE"
        or source_contains_private_tool_result
    ):
        owner=str(owner_principal_id or "").strip().lower()
        normalized_viewers={
            str(value).strip().lower()
            for value in viewers
            if str(value).strip()
        }
        if not owner or normalized_viewers != {owner}:
            raise FreshnessChanged(
                "owner_private_viewer_principal_set_required"
            )
    if (
        str(audience_scope).upper() in {
            "GROUP", "GROUP_SHARED", "SHARED",
            "SHARED_ACTIVITY", "GUEST",
        }
        and not viewers
    ):
        raise FreshnessChanged(
            "non_private_viewer_principal_set_required"
        )
    try:
        parameters=inspect.signature(chat_fn).parameters
    except (TypeError,ValueError):
        parameters={}

    if "attempt_guard" in parameters:
        expected_messages_digest=_messages_digest(messages)
        def guard_factory(candidate):
            return _FreshAttemptGuard(
                identity_db_path,
                r47_db_path,
                expected_generation,
                expectations,
                expected_messages_digest,
                expected_context_fence,
                identity_id,
                principal_id,
                owner_principal_id,
                audience_scope,
                context_space,
                required_privacy_class,
                authorization_digest,
                routing_policy_digest,
                tool_result_digest,
                tool_implementation_digest,
                tool_schema_digest,
                source_contains_private_tool_result,
                context_state_provider,
                approved_provider_digests,
                viewers,
            )
        kwargs={"attempt_guard":guard_factory}
        if "max_tokens" in parameters:
            kwargs["max_tokens"]=max_tokens
        if "timeout" in parameters:
            kwargs["timeout"]=timeout
        if "required_data_class" in parameters:
            kwargs["required_data_class"]=required_privacy_class
        if "attempt_audit" in parameters and attempt_audit is not None:
            kwargs["attempt_audit"]=attempt_audit
        if "provider_health" in parameters and provider_health is not None:
            kwargs["provider_health"]=provider_health
        return chat_fn(config,messages,**kwargs)

    if config.get("fallbacks") and str(required_privacy_class).upper()!="PUBLIC":
        raise FreshnessChanged("private_fallback_requires_attempt_guard")
    if source_contains_private_tool_result and not tool_result_digest:
        raise FreshnessChanged("private_tool_result_requires_fresh_digest")

    def validate_live_scope():
        _validate_context_state_snapshot(
            context_state_provider,
            identity_id=identity_id,
            principal_id=principal_id,
            audience_scope=audience_scope,
            context_space=context_space,
            authorization_digest=authorization_digest,
            routing_policy_digest=routing_policy_digest,
            tool_result_digest=tool_result_digest,
            tool_implementation_digest=tool_implementation_digest,
            tool_schema_digest=tool_schema_digest,
            viewer_principal_ids=viewers,
        )

    def validate_locked_state():
        post_i=post_r=None
        try:
            validate_live_scope()
            post_i=_open_locked(identity_db_path)
            _validate_identity(post_i,expected_generation,expectations)
            if (
                expected_context_fence is not None
                and _context_fence(post_i) != expected_context_fence
            ):
                raise FreshnessChanged("identity_context_fence_changed")
            if expectations:
                post_r=_open_locked(r47_db_path)
                _validate_r47(post_r,expectations)
        finally:
            _close_lock(post_r)
            _close_lock(post_i)

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
        validate_live_scope()
        iconn=_open_locked(identity_db_path)
        _validate_identity(iconn,expected_generation,expectations)
        if (
            expected_context_fence is not None
            and _context_fence(iconn) != expected_context_fence
        ):
            raise FreshnessChanged("identity_context_fence_changed")
        if expectations:
            rconn=_open_locked(r47_db_path)
            _validate_r47(rconn,expectations)
        kwargs={}
        if "max_tokens" in parameters:
            kwargs["max_tokens"]=max_tokens
        if "timeout" in parameters:
            kwargs["timeout"]=timeout
        if "required_data_class" in parameters:
            kwargs["required_data_class"]=required_privacy_class
        if "provider_health" in parameters and provider_health is not None:
            kwargs["provider_health"]=provider_health
        if "on_dispatched" in parameters:
            kwargs["on_dispatched"]=release
        result=chat_fn(
            config,
            json.loads(json.dumps(messages,ensure_ascii=False)),
            **kwargs,
        )
        release()
        validate_locked_state()
        return result
    finally:
        release()

def persist_assistant_if_fresh(
    store,bridge,expected_generation,expectations,content,
    expected_context_fence=None,
):
    """Atomically validate final context freshness and persist the normal assistant event."""
    if store.conn.in_transaction:
        raise RuntimeError("assistant_freshness_requires_clean_identity_transaction")
    rconn=None
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        _validate_identity(store.conn,expected_generation,expectations)
        if (
            expected_context_fence is not None
            and _context_fence(store.conn) != expected_context_fence
        ):
            raise FreshnessChanged("identity_context_fence_changed")
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
