#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal R49 destructive-confirmation atomic remediation.

All R49 SUPERSEDE/RETRACT/CONFLICT mutations must use this boundary.
Freshness is re-read after BEGIN IMMEDIATE and remains write-serialized
through the authoritative R47 mutation.  The submitted R47 store is not
modified; direct raw destructive R47 ingest remains outside this guarantee.
"""
from __future__ import annotations
import json
from r49_confirmed_transition import (
    ConfirmedSemanticTransition,current_generation,canonical_candidates
)

class R49AtomicConfirmedSemanticTransition(ConfirmedSemanticTransition):
    def propose(self,raw,model_payload,caller_binding,*,conversation_id,message_id,message_seq,
                source_role,source_text,effective_at):
        # Serialize deterministic action-id existence check + insert.  This
        # turns concurrent identical proposals into idempotent re-reads rather
        # than a UNIQUE(action_id) race, without changing the parent payload
        # schema or action identity.
        db=self.store.db
        try:
            db.execute("BEGIN IMMEDIATE")
            res=super().propose(
                raw,model_payload,caller_binding,
                conversation_id=conversation_id,message_id=message_id,
                message_seq=message_seq,source_role=source_role,
                source_text=source_text,effective_at=effective_at)
            if db.in_transaction:
                db.commit()
            return res
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise

    def reject(self,action_id,identity_id):
        if str(identity_id)!=self.identity_id:
            raise ValueError("confirmation_identity_mismatch")
        db=self.store.db
        try:
            db.execute("BEGIN IMMEDIATE")
            a=self._row(action_id)
            if not a:
                raise ValueError("pending_action_missing")
            if a["identity_id"]!=self.identity_id:
                raise ValueError("confirmation_identity_mismatch")
            payload=self._verify_row(a)
            if a["status"]=="applied":
                raise ValueError("applied_action_not_rejectable")
            if a["status"]=="rejected":
                db.rollback()
                return {"status":"already_rejected"}
            if a["status"]!="pending":
                raise ValueError("pending_action_not_rejectable")

            # A crash may have committed the authoritative R47 mutation before
            # the pending-action terminal status was persisted.  A terminal
            # reject must never overwrite that already-landed fact with a
            # contradictory "rejected" ledger state.  Reconcile exact source
            # + projection first while the SQLite write lock is held.
            candidates=canonical_candidates(payload["canonical"])
            landed,ids=self._exact_source_landed(payload,candidates)
            if landed:
                db.execute(
                  "UPDATE r49_pending_actions SET status='applied',claim_ids_json=? "
                  "WHERE action_id=? AND status='pending'",
                  (json.dumps(ids,separators=(",",":")),action_id))
                self._audit(action_id,"applied_recovered",
                            {"claim_ids":ids,"terminal_attempt":"reject"})
                db.commit()
                raise ValueError("applied_action_not_rejectable")

            cur=db.execute(
                "UPDATE r49_pending_actions SET status='rejected' "
                "WHERE action_id=? AND status='pending'",(action_id,))
            if cur.rowcount!=1:
                raise ValueError("reject_terminal_cas_lost")
            self._audit(action_id,"rejected",{"identity_id":self.identity_id})
            db.commit()
            return {"status":"rejected"}
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise

    def cancel(self,action_id,identity_id):
        if str(identity_id)!=self.identity_id:
            raise ValueError("confirmation_identity_mismatch")
        db=self.store.db
        try:
            db.execute("BEGIN IMMEDIATE")
            a=self._row(action_id)
            if not a:
                raise ValueError("pending_action_missing")
            if a["identity_id"]!=self.identity_id:
                raise ValueError("confirmation_identity_mismatch")
            payload=self._verify_row(a)
            if a["status"]=="applied":
                raise ValueError("applied_action_not_cancelable")
            if a["status"]=="canceled":
                db.rollback()
                return {"status":"already_canceled"}
            if a["status"]!="pending":
                raise ValueError("pending_action_not_cancelable")

            # Same recovery rule as reject(): once the exact source/projection
            # is durably present, cancellation is no longer a legal terminal
            # transition even if the action row still says pending.
            candidates=canonical_candidates(payload["canonical"])
            landed,ids=self._exact_source_landed(payload,candidates)
            if landed:
                db.execute(
                  "UPDATE r49_pending_actions SET status='applied',claim_ids_json=? "
                  "WHERE action_id=? AND status='pending'",
                  (json.dumps(ids,separators=(",",":")),action_id))
                self._audit(action_id,"applied_recovered",
                            {"claim_ids":ids,"terminal_attempt":"cancel"})
                db.commit()
                raise ValueError("applied_action_not_cancelable")

            cur=db.execute(
                "UPDATE r49_pending_actions SET status='canceled' "
                "WHERE action_id=? AND status='pending'",(action_id,))
            if cur.rowcount!=1:
                raise ValueError("cancel_terminal_cas_lost")
            self._audit(action_id,"canceled",{"identity_id":self.identity_id})
            db.commit()
            return {"status":"canceled"}
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise

    def confirm(self,action_id,identity_id,*,crash_at:str|None=None):
        if str(identity_id)!=self.identity_id:
            raise ValueError("confirmation_identity_mismatch")

        db=self.store.db
        try:
            # Acquire the SQLite write-serialization boundary BEFORE any
            # freshness/current-generation recheck.
            db.execute("BEGIN IMMEDIATE")
            a=self._row(action_id)
            if not a:
                raise ValueError("pending_action_missing")
            if a["identity_id"]!=self.identity_id:
                raise ValueError("confirmation_identity_mismatch")
            payload=self._verify_row(a)

            if a["status"]=="applied":
                db.rollback()
                return {"status":"already_applied",
                        "claim_ids":json.loads(a["claim_ids_json"])}
            if a["status"]!="pending":
                raise ValueError("pending_action_not_confirmable")

            # A previously materialized pending source whose lifecycle is no
            # longer active cannot be used to authorize a destructive action.
            existing_source=self.store._source(a["source_message_id"])
            if existing_source is not None and existing_source["lifecycle"]!="active":
                raise ValueError("confirmation_source_inadmissible_lifecycle")

            candidates=canonical_candidates(payload["canonical"])
            gen=current_generation(self.store)
            if gen!=a["state_generation"]:
                # Only the existing receipt-bound crash-recovery exception is
                # allowed: this exact source/projection already landed.
                landed,ids=self._exact_source_landed(payload,candidates)
                if not landed:
                    raise ValueError("confirmation_stale_state_generation")
                db.execute(
                  "UPDATE r49_pending_actions SET status='applied',claim_ids_json=? WHERE action_id=?",
                  (json.dumps(ids,separators=(",",":")),action_id))
                self._audit(action_id,"applied_recovered",{"claim_ids":ids})
                db.commit()
                return {"status":"applied_recovered","claim_ids":ids}

            if crash_at=="before_mutation":
                raise RuntimeError("synthetic_crash_before_mutation")

            # R47 ingest uses this same connection.  BEGIN IMMEDIATE above
            # prevents another writer from committing after the generation
            # check but before this authoritative destructive mutation.
            res=self.store.ingest(
              payload["conversation_id"],payload["message_id"],payload["message_seq"],
              payload["source_role"],payload["source_text"],payload["effective_at"],candidates)
            if db.in_transaction:
                db.commit()
            if res["status"] not in ("inserted","duplicate"):
                raise ValueError("confirmed_ingest_failed:"+res["status"])
            ids=list(res.get("claim_ids") or [])

            # Preserve the accepted post-R47/pre-action-status recovery model.
            if crash_at=="after_mutation_before_status":
                raise RuntimeError("synthetic_crash_after_mutation_before_status")

            with db:
                db.execute(
                  "UPDATE r49_pending_actions SET status='applied',claim_ids_json=? WHERE action_id=?",
                  (json.dumps(ids,separators=(",",":")),action_id))
                self._audit(action_id,"applied",
                            {"claim_ids":ids,"ingest_status":res["status"]})
            return {"status":"applied" if res["status"]=="inserted" else "applied_recovered",
                    "claim_ids":ids}
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise

__all__=["R49AtomicConfirmedSemanticTransition"]
