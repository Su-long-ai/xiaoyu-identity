# -*- coding: utf-8 -*-
"""RC-v2 research candidate: collapsed ProductMemoryBridge wrappers."""
from __future__ import annotations
import sqlite3
import product_memory_bridge_base as base
EXPECTED=base.EXPECTED
ProductMemoryBridgeError=base.ProductMemoryBridgeError
USER_MEMORY_SOURCE_KINDS=base.USER_MEMORY_SOURCE_KINDS
safe_product_recall=base.safe_product_recall

class ProductMemoryBridge(base.ProductMemoryBridge):
    MAX_LINEARIZATION_RETRIES=3

    def __init__(self,*args,**kwargs):
        self.authority_batches=0
        self.authority_candidates=0
        self.authority_rejected=0
        self.linearization_attempts=0
        self.linearization_retries=0
        self.linearization_fail_closed=0
        super().__init__(*args,**kwargs)

    def _r47_authority_batch(self, mids, authoritative):
        """Return memory_id -> (allowed, reason) for a bounded ranked batch."""
        mids=[int(x) for x in mids]
        if not mids:
            return {}
        self.authority_batches += 1
        self.authority_candidates += len(mids)

        sid_by_mid={
            mid:self._r47.source_message_id(
                "xiaoyu-product-confirmed-memory", f"memory-{mid}"
            )
            for mid in mids
        }
        sids=list(sid_by_mid.values())
        marks=",".join("?" for _ in sids)

        rows=self.pipeline.store.db.execute(
            f"""SELECT s.source_message_id,
                       s.lifecycle,
                       c.claim_id,
                       c.claim_text,
                       c.source_role,
                       c.authority_base,
                       c.relation_kind,
                       c.status
                FROM source_messages s
                LEFT JOIN claims c
                  ON c.source_message_id=s.source_message_id
                WHERE s.source_message_id IN ({marks})
                ORDER BY s.source_message_id,c.ordinal,c.created_order""",
            sids,
        ).fetchall()

        by_sid={sid:[] for sid in sids}
        source_lifecycle={}
        for row in rows:
            sid=str(row["source_message_id"])
            source_lifecycle[sid]=str(row["lifecycle"])
            if row["claim_id"] is not None:
                by_sid.setdefault(sid,[]).append(dict(row))

        claim_ids=[]
        claim_to_mid={}
        provisional={}
        for mid in mids:
            m=authoritative.get(mid)
            sid=sid_by_mid[mid]
            claims=by_sid.get(sid,[])
            if m is None:
                provisional[mid]=(False,"identity_missing_or_inactive")
                continue
            if source_lifecycle.get(sid)!="active":
                provisional[mid]=(False,"r47_source_not_active")
                continue
            if len(claims)!=1:
                provisional[mid]=(False,"r47_product_claim_cardinality")
                continue
            c=claims[0]
            if (
                str(c["source_role"])!="user"
                or str(c["authority_base"])!="user_assertion"
                or str(c["relation_kind"])!="NEW"
                or str(c["status"])!="active"
                or str(c["claim_text"])!=str(m["text"])
            ):
                provisional[mid]=(False,"r47_claim_not_current_user_state")
                continue
            cid=str(c["claim_id"])
            claim_ids.append(cid)
            claim_to_mid[cid]=mid
            provisional[mid]=(True,"active")

        conflicted=set()
        if claim_ids:
            cm=",".join("?" for _ in claim_ids)
            # A product claim is not user_state if it participates in any active
            # user-user conflict edge. The other endpoint may be outside ProductMemoryBridge.
            q=f"""SELECT cr.child_claim_id,cr.parent_claim_id
                  FROM claim_relations cr
                  JOIN claims a ON a.claim_id=cr.child_claim_id
                  JOIN claims b ON b.claim_id=cr.parent_claim_id
                  WHERE cr.relation='CONFLICTS'
                    AND a.status='active' AND b.status='active'
                    AND a.source_role='user' AND b.source_role='user'
                    AND (cr.child_claim_id IN ({cm})
                         OR cr.parent_claim_id IN ({cm}))"""
            params=claim_ids+claim_ids
            for edge in self.pipeline.store.db.execute(q,params):
                conflicted.add(str(edge["child_claim_id"]))
                conflicted.add(str(edge["parent_claim_id"]))

        result={}
        for mid,(allowed,reason) in provisional.items():
            if allowed:
                sid=sid_by_mid[mid]
                cid=str(by_sid[sid][0]["claim_id"])
                if cid in conflicted:
                    allowed=False;reason="r47_unresolved_conflict"
            if not allowed:
                self.authority_rejected += 1
            result[mid]=(allowed,reason)
        return result

    def _recall_authority_filtered(self, query: str, limit: int = 7) -> list[dict]:
        self.sync()
        qk = sorted(base._keywords(query))
        if not qk:
            return []

        def quote_fts(token: str) -> str:
            return '"' + str(token).replace('"', '""') + '"'

        match = " OR ".join(quote_fts(x) for x in qk[:256])
        candidate_cap = max(64, min(256, int(limit) * 24))
        rows = self.index.execute(
            """SELECT product_memory_fts.memory_id AS memory_id,
                      product_memory_fts.terms AS terms,
                      product_memory_meta.priority AS priority
               FROM product_memory_fts
               JOIN product_memory_meta
                 ON product_memory_meta.memory_id =
                    CAST(product_memory_fts.memory_id AS INTEGER)
               WHERE product_memory_fts MATCH ?
                 AND product_memory_meta.status='active'
               ORDER BY bm25(product_memory_fts)
               LIMIT ?""",
            (match, candidate_cap),
        ).fetchall()

        query_terms = set(qk)
        ranked = []
        for row in rows:
            mid = int(row["memory_id"])
            overlap = len(query_terms & set(str(row["terms"]).split()))
            if overlap <= 0:
                continue
            priority = int(row["priority"] or 3)
            score = overlap * 12 + priority * 2 + min(mid, 1_000_000) / 1_000_000
            ranked.append((score, mid, priority))
        ranked.sort(key=lambda x: (-x[0], -x[1]))
        if not ranked:
            return []

        out = []
        seen = set()
        batch_size = max(16, min(64, max(1, int(limit)) * 4))
        for offset in range(0, len(ranked), batch_size):
            batch = ranked[offset : offset + batch_size]
            ids = [mid for _, mid, _ in batch]
            marks = ",".join("?" for _ in ids)
            authoritative = {
                int(row["memory_id"]): dict(row)
                for row in self.identity_store.conn.execute(
                    f"""SELECT memory_id,category,text,priority,status
                        FROM memories
                        WHERE status='active' AND memory_id IN ({marks})""",
                    ids,
                )
            }
            authority = self._r47_authority_batch(ids, authoritative)
            for _, mid, priority in batch:
                m = authoritative.get(mid)
                if m is None:
                    continue
                allowed,_reason=authority.get(mid,(False,"authority_missing"))
                if not allowed:
                    continue
                key = (str(m["category"]), str(m["text"]))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "memory_id": mid,
                        "category": key[0],
                        "text": key[1],
                        "priority": int(m.get("priority") or priority),
                        "authority": "user_state",
                        "source_id": self._external_id(mid),
                        "retrieval": "product_state+sqlite_fts5_zh_bigram_v2",
                    }
                )
                if len(out) >= max(1, min(20, int(limit))):
                    return out
        return out

    def recall(self, query: str, limit: int = 7) -> list[dict]:
        db = self.pipeline.store.db

        for _attempt in range(self.MAX_LINEARIZATION_RETRIES):
            self.linearization_attempts += 1

            # A supported ProductMemoryBridge recall begins outside an R47
            # transaction.  Never silently weaken the boundary if a caller
            # violates that assumption.
            if db.in_transaction:
                self.linearization_fail_closed += 1
                return []

            try:
                db.execute("BEGIN IMMEDIATE")
                rows = self._recall_authority_filtered(query, limit=limit)

                # A same-connection lifecycle mutation (including the exact
                # independent-audit hook) can commit the outer transaction.
                # The rows were then materialized outside the intended
                # serialization window, so discard them and retry from current
                # authoritative state.
                if not db.in_transaction:
                    self.linearization_retries += 1
                    continue

                db.commit()
                return rows
            except sqlite3.Error:
                if db.in_transaction:
                    db.rollback()
                raise
            except Exception:
                if db.in_transaction:
                    db.rollback()
                raise

        self.linearization_fail_closed += 1
        return []
