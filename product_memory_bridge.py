# -*- coding: utf-8 -*-
"""RC-v2 research candidate: collapsed ProductMemoryBridge wrappers."""
from __future__ import annotations
import sqlite3
import hashlib
import json
import product_memory_bridge_base as base
from product_retrieval_adapter import (
    FrozenV1RetrievalAdapter, ProductRetrievalFreshnessChanged,
    WINNER_COMPONENT_ID,
)
EXPECTED=base.EXPECTED
ProductMemoryBridgeError=base.ProductMemoryBridgeError
USER_MEMORY_SOURCE_KINDS=base.USER_MEMORY_SOURCE_KINDS

def safe_product_recall(bridge, query: str, limit: int = 7):
    """Use the frozen V1 retrieval path when available; fail closed on any error."""
    if bridge is None:
        return [], "memory_bridge_unavailable"
    try:
        selected=getattr(bridge, "recall_v1", None)
        rows=(selected(query,limit=limit) if callable(selected)
              else bridge.recall(query,limit=limit))
        status=bridge.status()
        quarantined=int(status.get("quarantined_rows") or 0)
        if quarantined:
            return rows, f"quarantined_memories:{quarantined}"
        return rows,None
    except Exception as err:
        return [], type(err).__name__ + ": " + str(err)

class ProductMemoryBridge(base.ProductMemoryBridge):
    MAX_LINEARIZATION_RETRIES=3

    def __init__(self,*args,**kwargs):
        self.authority_batches=0
        self.authority_candidates=0
        self.authority_rejected=0
        self.linearization_attempts=0
        self.linearization_retries=0
        self.linearization_fail_closed=0
        self._v1_retrieval_adapter=None
        super().__init__(*args,**kwargs)

    def close(self):
        adapter=self._v1_retrieval_adapter
        try:
            if adapter is not None:
                adapter.close()
        finally:
            self._v1_retrieval_adapter=None
            return super().close()

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
                or str(c["relation_kind"]) not in ("NEW","CONFLICT")
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

    def _active_incident_conflict(self, claim_id: str) -> bool:
        """Exact targeted R47 conflict check for one concrete user claim."""
        row=self.pipeline.store.db.execute(
            """SELECT 1
               FROM claim_relations cr
               JOIN claims a ON a.claim_id=cr.child_claim_id
               JOIN claims b ON b.claim_id=cr.parent_claim_id
               WHERE cr.relation='CONFLICTS'
                 AND a.status='active' AND b.status='active'
                 AND a.source_role='user' AND b.source_role='user'
                 AND (cr.child_claim_id=? OR cr.parent_claim_id=?)
               LIMIT 1""",
            (str(claim_id),str(claim_id)),
        ).fetchone()
        return row is not None

    def commit_verified_conflict(self, memory_id: int, target_memory_id: int):
        """Commit one caller-verified concrete conflict using only targeted R47 checks."""
        mid=int(memory_id); target_mid=int(target_memory_id)
        if mid==target_mid:
            raise ValueError("verified_conflict_requires_distinct_memories")

        mems={
            int(r["memory_id"]):dict(r)
            for r in self.identity_store.conn.execute(
                """SELECT memory_id,created_at,updated_at,category,text,source_event,
                          priority,status,change_seq
                   FROM memories WHERE memory_id IN (?,?)""",
                (mid,target_mid),
            )
        }
        row=mems.get(mid); target=mems.get(target_mid)
        if row is None or target is None:
            raise ValueError("verified_conflict_memory_missing")
        if str(row["status"])!="active" or str(target["status"])!="active":
            raise ValueError("verified_conflict_requires_active_memories")

        for item in (row,target):
            ev=self.identity_store.conn.execute(
                "SELECT event_id,kind,actor FROM events WHERE event_id=?",
                (item.get("source_event"),),
            ).fetchone()
            if not (
                ev and str(ev["actor"])=="user"
                and str(ev["kind"]) in base.USER_MEMORY_SOURCE_KINDS
            ):
                raise ValueError("verified_conflict_requires_user_confirmed_sources")

        target_sid=self._r47.source_message_id(
            "xiaoyu-product-confirmed-memory",f"memory-{target_mid}"
        )
        target_source=self.pipeline.store._source(target_sid)
        if target_source is None or str(target_source["lifecycle"])!="active":
            raise ValueError("verified_conflict_target_not_synchronized")
        target_claims=self.pipeline.store.db.execute(
            """SELECT claim_id,claim_text,status,source_role,authority_base
               FROM claims WHERE source_message_id=?
               ORDER BY ordinal,created_order""",
            (target_sid,),
        ).fetchall()
        if len(target_claims)!=1:
            raise ValueError("verified_conflict_target_claim_cardinality")
        tc=target_claims[0]
        if (
            str(tc["status"])!="active"
            or str(tc["source_role"])!="user"
            or str(tc["authority_base"])!="user_assertion"
            or str(tc["claim_text"])!=str(target["text"])
        ):
            raise ValueError("verified_conflict_target_not_active_user_state")
        target_claim_id=str(tc["claim_id"])

        src=self._source(row)
        sid=self._r47.source_message_id(src["conversation_id"],src["message_id"])
        existing=self.pipeline.store._source(sid)

        # Exact replay is an idempotent no-op. This check precedes both the
        # target-conflict gate and pending-row admission because our own edge
        # necessarily makes the target conflicted after the first commit.
        # admission so restart/retry does not require fabricating a new mutation.
        if existing is not None:
            claims=self.pipeline.store.db.execute(
                """SELECT claim_id,relation_kind,status,claim_text
                   FROM claims WHERE source_message_id=?
                   ORDER BY ordinal,created_order""",
                (sid,),
            ).fetchall()
            edges=self.pipeline.store.db.execute(
                """SELECT child_claim_id,parent_claim_id,relation
                   FROM claim_relations WHERE child_claim_id IN
                   (SELECT claim_id FROM claims WHERE source_message_id=?)""",
                (sid,),
            ).fetchall()
            if not (
                str(existing["lifecycle"])=="active"
                and len(claims)==1
                and str(claims[0]["relation_kind"])=="CONFLICT"
                and str(claims[0]["status"])=="active"
                and str(claims[0]["claim_text"])==str(row["text"])
                and any(
                    str(e["relation"])=="CONFLICTS"
                    and str(e["parent_claim_id"])==target_claim_id
                    for e in edges
                )
            ):
                raise ValueError("verified_conflict_existing_source_mismatch")
            return {
                "status":"already_present",
                "memory_id":mid,
                "target_memory_id":target_mid,
                "target_claim_id":target_claim_id,
                "ingest":{"status":"already_present","source_message_id":sid,
                          "claim_ids":[str(claims[0]["claim_id"])]},
            }

        if self._active_incident_conflict(target_claim_id):
            raise ValueError("verified_conflict_target_already_conflicted")

        changed_ids=[int(x["memory_id"]) for x in self._changed_rows()]
        if changed_ids != [mid]:
            raise ValueError("verified_conflict_requires_single_pending_memory")

        candidate={
            "claim_text":str(row["text"]),
            "evidence_quote":str(row["text"]),
            "relation":"CONFLICT",
            "targets":[target_claim_id],
        }
        self.pipeline._bind_source(src)
        rr=self.pipeline.store.ingest(
            src["conversation_id"],src["message_id"],src["message_seq"],
            src["source_role"],src["text"],src["effective_at"],[candidate],
        )
        self.pipeline.seen_external[src["source_id"]]={
            "source_id":src["source_id"],"source_role":"user",
            "effective_at":int(src["effective_at"]),
        }
        self._index_upsert(row,src["source_id"],sid,True)
        self._checkpoint()
        return {
            "status":"committed",
            "memory_id":mid,
            "target_memory_id":target_mid,
            "target_claim_id":target_claim_id,
            "ingest":rr,
        }

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
        exact_ids = set()
        output_limit = max(1, min(20, int(limit)))
        if len(rows) > output_limit:
            candidate_ids = [int(row["memory_id"]) for row in rows]
            marks = ",".join("?" for _ in candidate_ids)
            exact_ids = {
                int(row["memory_id"])
                for row in self.identity_store.conn.execute(
                    f"""SELECT memory_id FROM memories
                        WHERE status='active' AND memory_id IN ({marks})
                          AND trim(text)=trim(?) COLLATE NOCASE""",
                    candidate_ids + [str(query)],
                )
            }

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
        if exact_ids:
            ranked.sort(key=lambda x: x[1] not in exact_ids)
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

    def _get_v1_retrieval_adapter(self):
        if self._v1_retrieval_adapter is None:
            self._v1_retrieval_adapter=FrozenV1RetrievalAdapter(self.component_root)
        return self._v1_retrieval_adapter

    def recall_v1(self, query: str, limit: int = 7) -> list[dict]:
        """Frozen V1 ranking over authority-filtered state with exact freshness fences."""
        db=self.pipeline.store.db
        adapter=self._get_v1_retrieval_adapter()
        for _attempt in range(self.MAX_LINEARIZATION_RETRIES):
            self.linearization_attempts += 1
            if db.in_transaction:
                self.linearization_fail_closed += 1
                return []
            try:
                adapter.ensure_cache(self)
                db.execute("BEGIN IMMEDIATE")
                rows=adapter.rank_locked(
                    self,query,limit=max(1,min(20,int(limit)))
                )
                if not db.in_transaction:
                    self.linearization_retries += 1
                    adapter.invalidate()
                    continue
                db.commit()
                return rows
            except ProductRetrievalFreshnessChanged:
                if db.in_transaction:
                    db.rollback()
                adapter.invalidate()
                self.linearization_retries += 1
                continue
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

    def status(self) -> dict:
        out=super().status()
        out["v1_retrieval_component"]=WINNER_COMPONENT_ID
        out["v1_retrieval_cached"]=bool(
            self._v1_retrieval_adapter is not None
            and self._v1_retrieval_adapter.state is not None
        )
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


    def _recall_conflict_filtered(self, query: str, limit: int = 7) -> list[dict]:
        """Read-only typed CONFLICT view over the same bounded FTS candidate pool."""
        self.sync()
        qk=sorted(base._keywords(query))
        if not qk:
            return []

        def quote_fts(token: str) -> str:
            return '"' + str(token).replace('"', '""') + '"'

        match=" OR ".join(quote_fts(x) for x in qk[:256])
        candidate_cap=max(64,min(256,int(limit)*24))
        rows=self.index.execute(
            """SELECT product_memory_fts.memory_id AS memory_id,
                      product_memory_fts.terms AS terms,
                      product_memory_meta.priority AS priority
               FROM product_memory_fts
               JOIN product_memory_meta
                 ON product_memory_meta.memory_id=CAST(product_memory_fts.memory_id AS INTEGER)
               WHERE product_memory_fts MATCH ?
                 AND product_memory_meta.status='active'
               ORDER BY bm25(product_memory_fts)
               LIMIT ?""",
            (match,candidate_cap),
        ).fetchall()

        query_terms=set(qk)
        ranked=[]
        for row in rows:
            mid=int(row["memory_id"])
            overlap=len(query_terms & set(str(row["terms"]).split()))
            if overlap<=0:
                continue
            priority=int(row["priority"] or 3)
            score=overlap*12+priority*2+min(mid,1_000_000)/1_000_000
            ranked.append((score,mid,priority))
        ranked.sort(key=lambda x:(-x[0],-x[1]))
        if not ranked:
            return []

        ids=[mid for _,mid,_ in ranked]
        marks=",".join("?" for _ in ids)
        authoritative={
            int(row["memory_id"]):dict(row)
            for row in self.identity_store.conn.execute(
                f"""SELECT memory_id,category,text,priority,status
                    FROM memories
                    WHERE status='active' AND memory_id IN ({marks})""",ids
            )
        }

        sid_by_mid={
            mid:self._r47.source_message_id(
                "xiaoyu-product-confirmed-memory",f"memory-{mid}"
            )
            for mid in ids
        }
        sids=list(sid_by_mid.values())
        smarks=",".join("?" for _ in sids)
        rr=self.pipeline.store.db.execute(
            f"""SELECT s.source_message_id,s.lifecycle,
                       c.claim_id,c.claim_text,c.source_role,c.authority_base,
                       c.relation_kind,c.status
                FROM source_messages s
                LEFT JOIN claims c ON c.source_message_id=s.source_message_id
                WHERE s.source_message_id IN ({smarks})
                ORDER BY s.source_message_id,c.ordinal,c.created_order""",
            sids,
        ).fetchall()
        by_sid={sid:[] for sid in sids}
        lifecycle={}
        for row in rr:
            sid=str(row["source_message_id"])
            lifecycle[sid]=str(row["lifecycle"])
            if row["claim_id"] is not None:
                by_sid.setdefault(sid,[]).append(dict(row))

        claim_to_mid={}
        mid_to_claim={}
        score_by_mid={mid:score for score,mid,_ in ranked}
        priority_by_mid={mid:priority for _,mid,priority in ranked}
        for mid in ids:
            m=authoritative.get(mid)
            sid=sid_by_mid[mid]
            claims=by_sid.get(sid,[])
            if m is None or lifecycle.get(sid)!="active" or len(claims)!=1:
                continue
            c=claims[0]
            if (
                str(c["source_role"])!="user"
                or str(c["authority_base"])!="user_assertion"
                or str(c["relation_kind"]) not in ("NEW","CONFLICT")
                or str(c["status"])!="active"
                or str(c["claim_text"])!=str(m["text"])
            ):
                continue
            cid=str(c["claim_id"])
            if not self._active_incident_conflict(cid):
                continue
            claim_to_mid[cid]=mid
            mid_to_claim[mid]=cid

        if not claim_to_mid:
            return []

        components=[]
        seen_claims=set()
        reachable_claims=set(claim_to_mid)
        for cid,mid in list(claim_to_mid.items()):
            if cid in seen_claims:
                continue
            full=set(self.pipeline.store._active_conflict_component(cid))
            seen_claims |= full
            if len(full)<2 or not full.issubset(reachable_claims):
                continue
            mids=[claim_to_mid[x] for x in full]
            mids.sort(key=lambda m:(-score_by_mid[m],-m))
            components.append((max(score_by_mid[m] for m in mids),mids,sorted(full)))
        components.sort(key=lambda x:(-x[0],[-m for m in x[1]]))

        cap=max(1,min(20,int(limit)))
        out=[]
        for _score,mids,claim_ids in components:
            if len(out)+len(mids)>cap:
                continue
            for mid in mids:
                m=authoritative[mid]
                out.append({
                    "memory_id":mid,
                    "category":str(m["category"]),
                    "text":str(m["text"]),
                    "priority":int(m.get("priority") or priority_by_mid[mid]),
                    "authority":"user_conflict",
                    "source_id":self._external_id(mid),
                    "claim_id":mid_to_claim[mid],
                    "conflict_component_claim_ids":claim_ids,
                    "retrieval":"product_conflict+sqlite_fts5_zh_bigram_v2",
                })
        return out

    def recall_typed(self, query: str, mode: str = "CURRENT", limit: int = 7) -> list[dict]:
        """Caller-owned typed read view. Mode inference is deliberately out of scope."""
        mode=str(mode or "").upper()
        if mode=="CURRENT":
            return self.recall(query,limit=limit)
        if mode!="CONFLICT":
            return []

        db=self.pipeline.store.db
        for _attempt in range(self.MAX_LINEARIZATION_RETRIES):
            self.linearization_attempts += 1
            if db.in_transaction:
                self.linearization_fail_closed += 1
                return []
            try:
                db.execute("BEGIN IMMEDIATE")
                rows=self._recall_conflict_filtered(query,limit=limit)
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
    # RC8M1 structured ingress spine

    # RC8M1 structured ingress spine
    INGRESS_MAX_SEGMENTS=16
    INGRESS_MAX_PROPOSALS_PER_SEGMENT=8
    INGRESS_MAX_STRUCTURAL_CANDIDATES=4
    INGRESS_MAX_LEXICAL_CANDIDATES=3

    @staticmethod
    def _ingress_stable_hash(value) -> str:
        raw=json.dumps(
            value,ensure_ascii=False,sort_keys=True,separators=(",",":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _ingress_event(self, kind: str, operation_key: str):
        row=self.identity_store.conn.execute(
            """SELECT event_id,extra FROM events
               WHERE kind=? AND actor='system' AND content=?
               ORDER BY event_id DESC LIMIT 1""",
            (str(kind),str(operation_key)),
        ).fetchone()
        return row

    @staticmethod
    def _ingress_extra(row) -> dict:
        if row is None:
            return {}
        try:
            value=json.loads(str(row["extra"] or "{}"))
        except Exception:
            return {}
        return value if isinstance(value,dict) else {}

    def _ingress_validate_source_event(self, source_event: int):
        row=self.identity_store.conn.execute(
            "SELECT event_id,kind,actor,content FROM events WHERE event_id=?",
            (int(source_event),),
        ).fetchone()
        if row is None:
            raise ValueError("structured_ingress_source_event_missing")
        if str(row["actor"])!="user" or str(row["kind"])!="conversation.user":
            raise ValueError("structured_ingress_requires_conversation_user_source")
        return row

    def _ingress_active_user_row(self, memory_id: int):
        row=self.identity_store.conn.execute(
            """SELECT memory_id,category,text,source_event,priority,status,change_seq
               FROM memories WHERE memory_id=?""",
            (int(memory_id),),
        ).fetchone()
        if row is None or str(row["status"])!="active":
            return None
        ev=self.identity_store.conn.execute(
            "SELECT kind,actor FROM events WHERE event_id=?",
            (row["source_event"],),
        ).fetchone()
        if not (
            ev
            and str(ev["actor"])=="user"
            and str(ev["kind"]) in base.USER_MEMORY_SOURCE_KINDS
        ):
            return None
        return dict(row)

    @staticmethod
    def _ingress_snapshot(row: dict) -> dict:
        return {
            "memory_id":int(row["memory_id"]),
            "change_seq":int(row["change_seq"]),
            "category":str(row["category"]),
            "text":str(row["text"]),
        }

    def _ingress_candidate_rows(self, segment: dict, proposal: dict) -> tuple[list[dict],dict]:
        refs=segment.get("refs") or {}
        if not isinstance(refs,dict):
            raise ValueError("structured_ingress_refs_must_be_object")
        allowed={"reply_memory_ids","focus_memory_ids","term_memory_ids"}
        if set(refs)-allowed:
            raise ValueError("structured_ingress_unknown_ref_field")

        ordered=[]
        raw_count=0
        # Exact source position first, then scoped-term sidecar, then transient focus.
        for key in ("reply_memory_ids","term_memory_ids","focus_memory_ids"):
            vals=refs.get(key) or []
            if not isinstance(vals,list):
                raise ValueError("structured_ingress_ref_list_required")
            raw_count += len(vals)
            for value in vals:
                try:
                    mid=int(value)
                except Exception as err:
                    raise ValueError("structured_ingress_ref_id_invalid") from err
                if mid not in ordered:
                    ordered.append(mid)

        structural_present=raw_count>0
        rows=[]
        if structural_present:
            for mid in ordered:
                row=self._ingress_active_user_row(mid)
                if row is None:
                    continue
                rows.append(row)
                if len(rows)>=self.INGRESS_MAX_STRUCTURAL_CANDIDATES:
                    break
            return rows,{
                "mode":"structural",
                "structural_present":True,
                "input_ref_count":raw_count,
                "truncated":len(ordered)>self.INGRESS_MAX_STRUCTURAL_CANDIDATES,
            }

        evidence=str(proposal.get("evidence_quote") or segment.get("text") or "").strip()
        recalled=self.recall(evidence,limit=self.INGRESS_MAX_LEXICAL_CANDIDATES)
        for item in recalled:
            row=self._ingress_active_user_row(int(item["memory_id"]))
            if row is not None:
                rows.append(row)
        return rows,{
            "mode":"lexical_fallback",
            "structural_present":False,
            "input_ref_count":0,
            "truncated":False,
        }

    def _ingress_operation_key(
        self, request_id: str, source_event: int, segment: dict,
        proposal_index: int, proposal: dict,
    ) -> str:
        material={
            "request_id":str(request_id),
            "source_event":int(source_event),
            "sid":str(segment["sid"]),
            "principal":str(segment["principal"]),
            "segment_text":str(segment["text"]),
            "refs":segment.get("refs") or {},
            "proposal_index":int(proposal_index),
            "proposal":proposal,
        }
        return self._ingress_stable_hash(material)

    def _ingress_applied_replay(self, operation_key: str):
        row=self._ingress_event("memory.ingress.applied",operation_key)
        if row is None:
            return None
        extra=self._ingress_extra(row)
        return {
            "status":"ALREADY_APPLIED",
            "operation_key":operation_key,
            "result":extra.get("result"),
        }

    def _ingress_record_applied(self, operation_key: str, result: dict):
        existing=self._ingress_event("memory.ingress.applied",operation_key)
        if existing is None:
            self.identity_store.record(
                "memory.ingress.applied","system",operation_key,
                {"result":result},
            )

    def _ingress_assert(
        self, operation_key: str, source_event: int, proposal: dict,
    ) -> dict:
        replay=self._ingress_applied_replay(operation_key)
        if replay is not None:
            return replay
        text=str(proposal.get("claim_text") or "").strip()
        quote=str(proposal.get("evidence_quote") or "").strip()
        if not text or not quote:
            raise ValueError("structured_ingress_assert_requires_claim_and_evidence")
        category=str(proposal.get("category") or "shared")
        if category not in ("shared","preference","relationship"):
            raise ValueError("structured_ingress_category_invalid")

        prior=self.identity_store.conn.execute(
            """SELECT memory_id,status FROM memories
               WHERE source_event=? AND category=? AND text=?
               ORDER BY memory_id LIMIT 1""",
            (int(source_event),category,text),
        ).fetchone()
        if prior is not None:
            result={
                "mutation":"ASSERT",
                "memory_id":int(prior["memory_id"]),
                "memory_status":str(prior["status"]),
                "source_event":int(source_event),
                "deduplicated":True,
            }
            self._ingress_record_applied(operation_key,result)
            return {"status":"ALREADY_PRESENT","operation_key":operation_key,"result":result}

        mid=self.identity_store.add_memory(
            text,category=category,priority=3,source_event=int(source_event)
        )
        self.sync()
        result={
            "mutation":"ASSERT",
            "memory_id":int(mid),
            "memory_status":"active",
            "source_event":int(source_event),
            "deduplicated":False,
        }
        self._ingress_record_applied(operation_key,result)
        return {"status":"APPLIED","operation_key":operation_key,"result":result}

    def _ingress_make_pending(
        self, operation_key: str, request_id: str, source_event: int,
        segment: dict, proposal_index: int, proposal: dict,
    ) -> dict:
        replay=self._ingress_applied_replay(operation_key)
        if replay is not None:
            return replay

        old=self._ingress_event("memory.ingress.pending",operation_key)
        if old is not None:
            pending=self._ingress_extra(old).get("pending")
            if isinstance(pending,dict):
                count=len(pending.get("candidates") or [])
                return {
                    "status":"PENDING_REPLAY",
                    "operation_key":operation_key,
                    "pending":pending,
                    "candidate_count":count,
                }

        rows,meta=self._ingress_candidate_rows(segment,proposal)
        if not rows:
            return {
                "status":"HOLD_NO_TARGET",
                "operation_key":operation_key,
                "candidate_count":0,
                "candidate_mode":meta["mode"],
                "structural_present":meta["structural_present"],
            }

        op=str(proposal["op"]).upper()
        payload={
            "version":1,
            "operation_key":operation_key,
            "request_id":str(request_id),
            "source_event":int(source_event),
            "sid":str(segment["sid"]),
            "proposal_index":int(proposal_index),
            "op":op,
            "new_text":(
                str(proposal.get("new_text") or "").strip()
                if op=="CORRECT" else None
            ),
            "evidence_quote":str(proposal.get("evidence_quote") or "").strip(),
            "candidate_mode":meta["mode"],
            "candidates":[self._ingress_snapshot(r) for r in rows],
        }
        payload["token"]=self._ingress_stable_hash(payload)
        self.identity_store.record(
            "memory.ingress.pending","system",operation_key,
            {"pending":payload},
        )
        count=len(payload["candidates"])
        return {
            "status":"NEEDS_CONFIRMATION" if count==1 else "NEEDS_CLARIFICATION",
            "operation_key":operation_key,
            "pending":payload,
            "candidate_count":count,
            "candidate_mode":meta["mode"],
            "candidates":[
                {
                    "memory_id":x["memory_id"],
                    "category":x["category"],
                    "text":x["text"],
                }
                for x in payload["candidates"]
            ],
        }

    def ingest_structured(self, envelope: dict) -> dict:
        """Compose caller-owned segmentation and refs with deterministic memory mutation."""
        if not isinstance(envelope,dict):
            raise ValueError("structured_ingress_envelope_must_be_object")
        allowed={"request_id","source_event","segments"}
        if set(envelope)-allowed:
            raise ValueError("structured_ingress_unknown_envelope_field")
        request_id=str(envelope.get("request_id") or "").strip()
        if not request_id or len(request_id)>200:
            raise ValueError("structured_ingress_request_id_invalid")
        source_event=int(envelope.get("source_event"))
        source=self._ingress_validate_source_event(source_event)
        source_text=str(source["content"])

        segments=envelope.get("segments")
        if not isinstance(segments,list) or not segments:
            raise ValueError("structured_ingress_segments_required")
        if len(segments)>self.INGRESS_MAX_SEGMENTS:
            raise ValueError("structured_ingress_too_many_segments")

        results=[]
        seen_sid=set()
        for segment in segments:
            if not isinstance(segment,dict):
                raise ValueError("structured_ingress_segment_must_be_object")
            allowed_seg={"sid","principal","text","refs","proposals"}
            if set(segment)-allowed_seg:
                raise ValueError("structured_ingress_unknown_segment_field")
            sid=str(segment.get("sid") or "").strip()
            if not sid or sid in seen_sid:
                raise ValueError("structured_ingress_segment_id_invalid")
            seen_sid.add(sid)
            principal=str(segment.get("principal") or "").strip()
            text=str(segment.get("text") or "")
            if not text or text not in source_text:
                raise ValueError("structured_ingress_segment_not_in_source")
            proposals=segment.get("proposals") or []
            if not isinstance(proposals,list):
                raise ValueError("structured_ingress_proposals_must_be_list")
            if len(proposals)>self.INGRESS_MAX_PROPOSALS_PER_SEGMENT:
                raise ValueError("structured_ingress_too_many_proposals")

            if principal!="user_self":
                results.append({
                    "sid":sid,
                    "principal":principal,
                    "status":"BLOCKED_NON_USER_PRINCIPAL",
                    "proposal_count":len(proposals),
                })
                continue

            seg_results=[]
            for i,proposal in enumerate(proposals):
                if not isinstance(proposal,dict):
                    raise ValueError("structured_ingress_proposal_must_be_object")
                allowed_prop={"op","claim_text","new_text","evidence_quote","category"}
                if set(proposal)-allowed_prop:
                    raise ValueError("structured_ingress_unknown_or_target_owned_proposal_field")
                op=str(proposal.get("op") or "").upper()
                if op not in ("ASSERT","CORRECT","RETRACT"):
                    raise ValueError("structured_ingress_op_unsupported")
                quote=str(proposal.get("evidence_quote") or "").strip()
                if not quote or quote not in text:
                    raise ValueError("structured_ingress_evidence_not_in_segment")
                if op=="CORRECT":
                    new_text=str(proposal.get("new_text") or "").strip()
                    if not (2<=len(new_text)<=1500):
                        raise ValueError("structured_ingress_new_text_invalid")
                operation_key=self._ingress_operation_key(
                    request_id,source_event,segment,i,proposal
                )
                if op=="ASSERT":
                    item=self._ingress_assert(operation_key,source_event,proposal)
                else:
                    item=self._ingress_make_pending(
                        operation_key,request_id,source_event,segment,i,proposal
                    )
                item["proposal_index"]=i
                item["op"]=op
                seg_results.append(item)
            results.append({
                "sid":sid,
                "principal":principal,
                "status":"PROCESSED",
                "proposals":seg_results,
            })
        return {
            "request_id":request_id,
            "source_event":source_event,
            "segments":results,
        }

    def _ingress_validate_pending(self, pending: dict) -> dict:
        if not isinstance(pending,dict):
            raise ValueError("structured_ingress_pending_must_be_object")
        payload=dict(pending)
        token=str(payload.pop("token",""))
        if not token or token!=self._ingress_stable_hash(payload):
            raise ValueError("structured_ingress_pending_token_invalid")
        payload["token"]=token
        if int(payload.get("version",0))!=1:
            raise ValueError("structured_ingress_pending_version_invalid")
        if str(payload.get("op")) not in ("CORRECT","RETRACT"):
            raise ValueError("structured_ingress_pending_op_invalid")
        cands=payload.get("candidates")
        if not isinstance(cands,list) or not cands or len(cands)>self.INGRESS_MAX_STRUCTURAL_CANDIDATES:
            raise ValueError("structured_ingress_pending_candidates_invalid")

        operation_key=str(payload.get("operation_key") or "")
        durable=self._ingress_event("memory.ingress.pending",operation_key)
        if durable is None:
            raise ValueError("structured_ingress_pending_not_authorized")
        durable_extra=self._ingress_extra(durable)
        durable_pending=durable_extra.get("pending")
        if not isinstance(durable_pending,dict):
            raise ValueError("structured_ingress_pending_authorization_invalid")
        if durable_pending != payload:
            raise ValueError("structured_ingress_pending_authorization_mismatch")
        return payload

    def _ingress_mutation_intent_payload(self, payload: dict, selected: int) -> dict:
        selected=int(selected)
        snap=next(
            (x for x in payload["candidates"] if int(x["memory_id"])==selected),
            None,
        )
        if snap is None:
            raise ValueError("structured_ingress_selected_snapshot_missing")
        out={
            "op":str(payload["op"]),
            "target_memory_id":selected,
            "target_change_seq":int(snap["change_seq"]),
        }
        if str(payload["op"])=="CORRECT":
            out["new_text"]=str(payload.get("new_text") or "")
        return out

    def _ingress_record_mutation_intent(
        self, operation_key: str, payload: dict, selected: int,
    ) -> dict:
        expected=self._ingress_mutation_intent_payload(payload,selected)
        existing=self._ingress_event("memory.ingress.mutation_intent",operation_key)
        if existing is not None:
            if self._ingress_extra(existing)!=expected:
                raise ValueError("structured_ingress_mutation_intent_mismatch")
            raise ValueError("structured_ingress_mutation_intent_unexpected_reentry")
        # Deliberately use the current IdentityStore transaction without its
        # public record() context manager. The following correct/retract call
        # commits this marker atomically with the authoritative mutation.
        self.identity_store._insert_event(
            "memory.ingress.mutation_intent","system",operation_key,expected
        )
        return expected

    def _ingress_exact_recovery(self, payload: dict, selected: int):
        operation_key=str(payload["operation_key"])
        intent=self._ingress_event("memory.ingress.mutation_intent",operation_key)
        if intent is None:
            return None
        if self._ingress_extra(intent)!=self._ingress_mutation_intent_payload(payload,selected):
            return None
        op=str(payload["op"])
        if op=="CORRECT":
            row=self.identity_store.conn.execute(
                """SELECT m.memory_id,m.status
                   FROM events e
                   JOIN memories m ON m.source_event=e.event_id
                   WHERE e.kind='memory.corrected' AND e.actor='user'
                     AND e.content=?
                     AND CAST(json_extract(e.extra,'$.supersedes_memory_id') AS INTEGER)=?
                   ORDER BY m.memory_id DESC LIMIT 1""",
                (str(payload.get("new_text") or ""),int(selected)),
            ).fetchone()
            if row is not None:
                return {
                    "mutation":"CORRECT",
                    "target_memory_id":int(selected),
                    "new_memory_id":int(row["memory_id"]),
                    "new_memory_status":str(row["status"]),
                    "recovered":True,
                }
        elif op=="RETRACT":
            row=self.identity_store.conn.execute(
                """SELECT event_id FROM events
                   WHERE kind='memory.retracted' AND actor='user' AND content=?
                   ORDER BY event_id DESC LIMIT 1""",
                (str(int(selected)),),
            ).fetchone()
            mem=self.identity_store.conn.execute(
                "SELECT status FROM memories WHERE memory_id=?",(int(selected),)
            ).fetchone()
            if row is not None and mem is not None and str(mem["status"])=="retracted":
                return {
                    "mutation":"RETRACT",
                    "target_memory_id":int(selected),
                    "recovered":True,
                }
        return None

    def confirm_structured(self, pending: dict, selected_memory_id: int | None = None) -> dict:
        """Apply one user-confirmed target-bound correction/retraction transaction."""
        conn=self.identity_store.conn
        if conn.in_transaction:
            raise ValueError("structured_ingress_confirm_requires_clean_transaction")
        conn.execute("BEGIN IMMEDIATE")
        try:
            payload=self._ingress_validate_pending(pending)
            operation_key=str(payload["operation_key"])
            replay=self._ingress_applied_replay(operation_key)
            if replay is not None:
                return replay

            candidates=list(payload["candidates"])
            ids=[int(x["memory_id"]) for x in candidates]
            if len(ids)>1 and selected_memory_id is None:
                return {
                    "status":"NEEDS_CLARIFICATION",
                    "operation_key":operation_key,
                    "candidate_count":len(ids),
                }
            selected=int(ids[0] if selected_memory_id is None else selected_memory_id)
            if selected not in ids:
                return {"status":"INVALID_SELECTION","operation_key":operation_key}

            # Durable authorization, complete candidate snapshot and authoritative
            # mutation share one SQLite writer serialization window.
            current={}
            for snap in candidates:
                mid=int(snap["memory_id"])
                row=conn.execute(
                    """SELECT memory_id,category,text,source_event,status,change_seq
                       FROM memories WHERE memory_id=?""",
                    (mid,),
                ).fetchone()
                current[mid]=row

            all_same=True
            for snap in candidates:
                mid=int(snap["memory_id"]);row=current[mid]
                if (
                    row is None
                    or str(row["status"])!="active"
                    or int(row["change_seq"])!=int(snap["change_seq"])
                ):
                    all_same=False
                    break

            if not all_same:
                recovered=self._ingress_exact_recovery(payload,selected)
                if recovered is not None:
                    conn.commit()
                    try:
                        self.sync()
                    finally:
                        self._ingress_record_applied(operation_key,recovered)
                    return {
                        "status":"ALREADY_APPLIED",
                        "operation_key":operation_key,
                        "result":recovered,
                    }
                return {"status":"STALE","operation_key":operation_key}

            for mid in ids:
                if self._ingress_active_user_row(mid) is None:
                    return {"status":"STALE","operation_key":operation_key}

            op=str(payload["op"])
            self._ingress_record_mutation_intent(operation_key,payload,selected)
            if op=="CORRECT":
                new_id=self.identity_store.correct_memory(
                    selected,str(payload["new_text"])
                )
                self.sync()
                result={
                    "mutation":"CORRECT",
                    "target_memory_id":selected,
                    "new_memory_id":int(new_id),
                    "lineage":{"supersedes_memory_id":selected},
                    "recovered":False,
                }
            else:
                ok=self.identity_store.retract_memory(selected)
                if not ok:
                    return {"status":"STALE","operation_key":operation_key}
                self.sync()
                result={
                    "mutation":"RETRACT",
                    "target_memory_id":selected,
                    "recovered":False,
                }
            self._ingress_record_applied(operation_key,result)
            return {"status":"APPLIED","operation_key":operation_key,"result":result}
        finally:
            if conn.in_transaction:
                conn.rollback()
