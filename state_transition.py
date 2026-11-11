# -*- coding: utf-8 -*-
"""Unified product-facing state transition façade for XiaoYu v1 closeout.

This module owns no durable state. It routes typed, already-admitted state
transitions into the existing IdentityStore + accepted R47 authority runtime.
There is deliberately no lexical, benchmark-family, or memory-category-specific
dispatch.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable

@dataclass(frozen=True)
class TransitionReceipt:
    kind: str
    object_id: str
    status: str

class UnifiedStateTransition:
    """One deterministic mutation boundary over the existing authoritative stores."""

    def __init__(self, store: Any, bridge: Any):
        self.store=store
        self.bridge=bridge

    def _sync(self):
        out=self.bridge.sync()
        if not isinstance(out,dict):
            raise RuntimeError("bridge_sync_contract")
        return out

    def _memory_claim_id(self, memory_id: int) -> str:
        sid=self.bridge._r47.source_message_id(
            "xiaoyu-product-confirmed-memory",f"memory-{int(memory_id)}")
        rows=self.bridge.pipeline.store.db.execute(
            """SELECT claim_id,status,claim_text,source_role
               FROM claims WHERE source_message_id=?
               ORDER BY ordinal,created_order""",(sid,)).fetchall()
        if len(rows)!=1:
            raise RuntimeError("memory_claim_cardinality")
        row=rows[0]
        if str(row["source_role"])!="user":
            raise RuntimeError("memory_claim_not_user")
        return str(row["claim_id"])

    def assert_state(self,text: str,category: str="shared") -> int:
        mid=int(self.store.add_memory(str(text),category=str(category),priority=4))
        self._sync()
        return mid

    def accept_proposal(self,message: str) -> int:
        """Confirmed semantic ingress: proposal remains non-authoritative until review."""
        message=str(message)
        event_id=int(self.store.record("conversation.user","user",message))
        proposal_id=self.store.propose_from_user_event(event_id,message)
        if proposal_id is None:
            raise ValueError("semantic_proposal_not_created")
        self.store.review_proposal(int(proposal_id),True)
        row=self.store.conn.execute(
            """SELECT memory_id FROM memories
               WHERE source_event=? AND status='active'
               ORDER BY memory_id DESC LIMIT 1""",(event_id,)).fetchone()
        if row is None:
            raise RuntimeError("accepted_proposal_memory_missing")
        self._sync()
        return int(row["memory_id"])

    def correct(self,memory_id: int,text: str) -> int:
        new_id=int(self.store.correct_memory(int(memory_id),str(text)))
        self._sync()
        return new_id

    def retract(self,memory_id: int) -> bool:
        ok=bool(self.store.retract_memory(int(memory_id)))
        if not ok:
            raise ValueError("active_memory_not_found")
        self._sync()
        return True

    def conflict(self,text: str,category: str,target_memory_id: int) -> int:
        """Commit an equal-user-authority conflict without minting a second truth."""
        new_id=int(self.store.add_memory(str(text),category=str(category),priority=4))
        self.bridge.commit_verified_conflict(new_id,int(target_memory_id))
        return new_id

    def derive(self,key: str,text: str,parent_memory_ids: Iterable[int]) -> str:
        """Create non-authoritative derived state bound to exact current parent claims."""
        self._sync()
        parent_ids=[self._memory_claim_id(int(x)) for x in parent_memory_ids]
        if not parent_ids:
            raise ValueError("derived_requires_parents")
        rows=[self.bridge.pipeline.store._claim(cid) for cid in parent_ids]
        if any(r is None for r in rows):
            raise ValueError("derived_parent_missing")
        effective_at=max(int(r["effective_at"]) for r in rows)+1
        out=self.bridge.pipeline.store.derive(
            str(key),str(text),parent_ids,effective_at)
        return str(out["claim_id"])

    def persona_growth(self,text: str,evidence_event_ids: Iterable[int]) -> None:
        self.store.propose_growth(
            str(text),[int(x) for x in evidence_event_ids],confirmed=True)

    def relationship_confirm(self,member_event_ids: Iterable[int]) -> dict:
        """Reuse the independently ACCEPT_E1 exact-event confirmation boundary."""
        proposal=self.store.propose_shared_episode([int(x) for x in member_event_ids])
        return self.store.confirm_shared_episode(
            int(proposal["proposal_event_id"]),str(proposal["proposal_token"]))

    def relationship_cancel(self,confirmation_event_id: int) -> dict:
        return self.store.cancel_shared_episode(int(confirmation_event_id))
