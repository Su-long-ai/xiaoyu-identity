#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R49 formal closeout candidate: structural v5 + persistent destructive confirmation.

The accepted R47 store is not modified.  This wrapper adds pending-action tables
to the same SQLite database connection.  Destructive semantic proposals never
mutate memory during propose(); confirmation binds identity, exact source/payload,
the caller authorization snapshot and the expected current generation.

Crash recovery invariant:
- action status is written only after R47 ingest commits;
- if a crash occurs after ingest but before action status/audit, retry detects the
  exact already-landed source/projection and marks the action applied without a
  second mutation.
"""
from __future__ import annotations
import hashlib,hmac,json
from typing import Any
import r49_structural_v5 as v5
from r47_open_domain_memory_store_frozen import source_message_id,sha_obj

ACTION_SCHEMA="""
CREATE TABLE IF NOT EXISTS r49_pending_actions(
  action_id TEXT PRIMARY KEY,
  identity_id TEXT NOT NULL,
  state_generation TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  binding_snapshot_sha256 TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  auth_tag TEXT NOT NULL,
  status TEXT NOT NULL,
  claim_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS r49_action_audit(
  action_id TEXT NOT NULL,
  event TEXT NOT NULL,
  detail_sha256 TEXT NOT NULL,
  PRIMARY KEY(action_id,event)
);
"""

def stable(x:Any)->str:
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def current_generation(store)->str:
    v=store.current_view()
    rows=[]
    for kind in ("current","conflict"):
        for r in v[kind]:
            rows.append({
              "kind":kind,"claim_id":r["claim_id"],"status":r["status"],
              "claim_text_hash":r["claim_text_hash"],"effective_at":int(r["effective_at"])
            })
    rows.sort(key=lambda x:(x["kind"],x["claim_id"]))
    return stable({"status":v["status"],"rows":rows})

def canonical_candidates(canonical:dict)->list[dict]:
    out=[]
    for item in canonical["outputs"]:
        for p in item.get("proposals") or []:
            out.append({
              "claim_text":p["claim_text"],"evidence_quote":p["evidence_quote"],
              "relation":p["relation"],"targets":list(p.get("target_ids") or [])
            })
    return out

def has_destructive(canonical:dict)->bool:
    return any(p["relation"] in ("SUPERSEDE","RETRACT","CONFLICT")
               for item in canonical["outputs"] for p in (item.get("proposals") or []))

class ConfirmedSemanticTransition:
    def __init__(self,store,identity_id:str,confirmation_key:bytes):
        self.store=store
        self.identity_id=str(identity_id)
        if not isinstance(confirmation_key,(bytes,bytearray)) or len(confirmation_key)<16:
            raise ValueError("confirmation_key_too_short")
        self.confirmation_key=bytes(confirmation_key)
        self.store.db.executescript(ACTION_SCHEMA)
        self.store.db.commit()

    def _tag(self,payload_json:str)->str:
        return hmac.new(self.confirmation_key,payload_json.encode("utf-8"),hashlib.sha256).hexdigest()

    def _verify_row(self,a:dict):
        if not hmac.compare_digest(str(a["auth_tag"]),self._tag(str(a["payload_json"]))):
            raise ValueError("pending_action_auth_mismatch")
        payload=json.loads(a["payload_json"])
        if stable(payload)!=a["payload_sha256"]:
            raise ValueError("pending_payload_hash_mismatch")
        if payload.get("identity_id")!=a["identity_id"]:
            raise ValueError("pending_identity_binding_mismatch")
        if payload.get("binding_snapshot_sha256")!=a["binding_snapshot_sha256"]:
            raise ValueError("pending_binding_hash_mismatch")
        expected_sid=source_message_id(payload["conversation_id"],payload["message_id"])
        if expected_sid!=a["source_message_id"]:
            raise ValueError("pending_source_binding_mismatch")
        expected_aid=stable({"schema":"r49-confirmed-action-v1","payload_sha256":a["payload_sha256"]})
        if expected_aid!=a["action_id"]:
            raise ValueError("pending_action_id_mismatch")
        return payload

    def _row(self,action_id):
        r=self.store.db.execute("SELECT * FROM r49_pending_actions WHERE action_id=?",(action_id,)).fetchone()
        return dict(r) if r else None

    def _audit(self,action_id,event,detail):
        self.store.db.execute("INSERT OR IGNORE INTO r49_action_audit(action_id,event,detail_sha256) VALUES(?,?,?)",
                              (action_id,event,stable(detail)))

    def propose(self,raw,model_payload,caller_binding,*,conversation_id,message_id,message_seq,
                source_role,source_text,effective_at):
        canonical=v5.validate_response(raw,model_payload,caller_binding)
        if not has_destructive(canonical):
            return {"status":"no_confirmation_required","canonical":canonical}
        payload={
          "identity_id":self.identity_id,
          "state_generation":current_generation(self.store),
          "conversation_id":str(conversation_id),"message_id":str(message_id),
          "message_seq":int(message_seq),"source_role":str(source_role),
          "source_text":str(source_text),"source_text_sha256":hashlib.sha256(str(source_text).encode()).hexdigest(),
          "effective_at":int(effective_at),
          "binding_snapshot_sha256":canonical["binding_snapshot_sha256"],
          "canonical":canonical,
        }
        payload_sha=stable(payload)
        sid=source_message_id(payload["conversation_id"],payload["message_id"])
        action_id=stable({"schema":"r49-confirmed-action-v1","payload_sha256":payload_sha})
        with self.store.db:
            old=self._row(action_id)
            if old is None:
                payload_json=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
                self.store.db.execute("""INSERT INTO r49_pending_actions
                  (action_id,identity_id,state_generation,source_message_id,binding_snapshot_sha256,
                   payload_sha256,payload_json,auth_tag,status,claim_ids_json)
                  VALUES(?,?,?,?,?,?,?,?,'pending','[]')""",
                  (action_id,self.identity_id,payload["state_generation"],sid,
                   payload["binding_snapshot_sha256"],payload_sha,payload_json,self._tag(payload_json)))
                self._audit(action_id,"proposed",{"payload_sha256":payload_sha})
                status="pending"
            else:
                if old["payload_sha256"]!=payload_sha or old["identity_id"]!=self.identity_id:
                    raise ValueError("action_id_payload_collision")
                status=old["status"]
        return {"status":status,"action_id":action_id,"payload_sha256":payload_sha,
                "state_generation":payload["state_generation"]}

    def reject(self,action_id,identity_id):
        a=self._row(action_id)
        if not a:raise ValueError("pending_action_missing")
        if str(identity_id)!=self.identity_id or a["identity_id"]!=self.identity_id:
            raise ValueError("confirmation_identity_mismatch")
        self._verify_row(a)
        if a["status"]=="applied":
            raise ValueError("applied_action_not_rejectable")
        if a["status"]=="rejected":
            return {"status":"already_rejected"}
        if a["status"]!="pending":raise ValueError("bad_action_status")
        with self.store.db:
            self.store.db.execute("UPDATE r49_pending_actions SET status='rejected' WHERE action_id=?",(action_id,))
            self._audit(action_id,"rejected",{"identity_id":self.identity_id})
        return {"status":"rejected"}

    def _exact_source_landed(self,payload,candidates)->tuple[bool,list[str]]:
        sid=source_message_id(payload["conversation_id"],payload["message_id"])
        src=self.store._source(sid)
        if not src:return False,[]
        try:
            canonical=self.store._canonical_candidates(payload["source_text"],candidates)
        except Exception:
            return False,[]
        projection_hash=sha_obj(canonical)
        text_hash=hashlib.sha256(payload["source_text"].encode()).hexdigest()
        exact=(
          src["conversation_id"]==payload["conversation_id"] and
          src["message_id"]==payload["message_id"] and
          int(src["message_seq"])==int(payload["message_seq"]) and
          src["source_role"]==payload["source_role"] and
          src["source_text_hash"]==text_hash and
          int(src["effective_at"])==int(payload["effective_at"]) and
          src["projection_hash"]==projection_hash and
          src["lifecycle"]=="active"
        )
        if not exact:return False,[]
        ids=[r[0] for r in self.store.db.execute(
          "SELECT claim_id FROM claims WHERE source_message_id=? ORDER BY ordinal",(sid,))]
        return True,ids

    def confirm(self,action_id,identity_id,*,crash_at:str|None=None):
        a=self._row(action_id)
        if not a:raise ValueError("pending_action_missing")
        if str(identity_id)!=self.identity_id or a["identity_id"]!=self.identity_id:
            raise ValueError("confirmation_identity_mismatch")
        payload=self._verify_row(a)
        if a["status"]=="applied":
            return {"status":"already_applied","claim_ids":json.loads(a["claim_ids_json"])}
        if a["status"]!="pending":
            raise ValueError("pending_action_not_confirmable")
        candidates=canonical_candidates(payload["canonical"])
        gen=current_generation(self.store)

        # If state generation drifted, only one recovery path is allowed: the exact
        # source+projection from this action already landed before an action-status crash.
        if gen!=a["state_generation"]:
            landed,ids=self._exact_source_landed(payload,candidates)
            if not landed:
                raise ValueError("confirmation_stale_state_generation")
            with self.store.db:
                self.store.db.execute(
                  "UPDATE r49_pending_actions SET status='applied',claim_ids_json=? WHERE action_id=?",
                  (json.dumps(ids,separators=(",",":")),action_id))
                self._audit(action_id,"applied_recovered",{"claim_ids":ids})
            return {"status":"applied_recovered","claim_ids":ids}

        if crash_at=="before_mutation":
            raise RuntimeError("synthetic_crash_before_mutation")
        res=self.store.ingest(
          payload["conversation_id"],payload["message_id"],payload["message_seq"],
          payload["source_role"],payload["source_text"],payload["effective_at"],candidates)
        if res["status"] not in ("inserted","duplicate"):
            raise ValueError("confirmed_ingest_failed:"+res["status"])
        ids=list(res.get("claim_ids") or [])
        if crash_at=="after_mutation_before_status":
            raise RuntimeError("synthetic_crash_after_mutation_before_status")
        with self.store.db:
            self.store.db.execute(
              "UPDATE r49_pending_actions SET status='applied',claim_ids_json=? WHERE action_id=?",
              (json.dumps(ids,separators=(",",":")),action_id))
            self._audit(action_id,"applied",{"claim_ids":ids,"ingest_status":res["status"]})
        return {"status":"applied" if res["status"]=="inserted" else "applied_recovered",
                "claim_ids":ids}

    def action_status(self,action_id):
        a=self._row(action_id)
        if not a:return None
        return {"action_id":action_id,"status":a["status"],
                "claim_ids":json.loads(a["claim_ids_json"]),
                "audit_events":[r[0] for r in self.store.db.execute(
                  "SELECT event FROM r49_action_audit WHERE action_id=? ORDER BY event",(action_id,))]}
