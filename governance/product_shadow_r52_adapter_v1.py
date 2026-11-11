#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XiaoYu product-shadow adapter over exact accepted R52 v8.

Product-only repairs discovered by longitudinal shadow:
1. frozen raw-source retrieval rebuilds a TEMP FTS table per query and leaves a
   transaction open, breaking the next R49 BEGIN IMMEDIATE;
2. ordinary QA can choose one endpoint from unresolved user_conflict;
3. per-query raw-source rebuild scales with total source count.

This adapter leaves confirmatory-frozen bytes unchanged.  It owns a product
source FTS index, updates it at source commit boundaries, and adds a conflict
answer gate.
"""
from __future__ import annotations
import sys
from pathlib import Path

FROZEN=Path(__file__).resolve().parent/"confirmatory_frozen"
if str(FROZEN) not in sys.path:
    sys.path.insert(0,str(FROZEN))

from r52_composition_candidate_v8 import R52Composition as FrozenR52Composition
import r52_candidate_v7 as ref
import r52_qa_sufficiency_v7 as qa
from r47_open_domain_memory_store_frozen import source_message_id

SOURCE_FTS_SCHEMA="""
CREATE VIRTUAL TABLE IF NOT EXISTS product_source_fts USING fts5(
  source_message_id UNINDEXED,
  source_role UNINDEXED,
  source_text,
  tokenize='unicode61'
);
CREATE INDEX IF NOT EXISTS product_idx_source_conv_seq
  ON source_messages(conversation_id,message_seq);
"""

class ProductShadowR52Composition(FrozenR52Composition):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._rebuild_product_source_fts()

    def _rebuild_product_source_fts(self):
        db=self.store.db
        if db.in_transaction:
            raise RuntimeError("product_index_rebuild_requires_clean_transaction")
        with db:
            db.executescript(SOURCE_FTS_SCHEMA)
            db.execute("DELETE FROM product_source_fts")
            db.execute("""INSERT INTO product_source_fts(source_message_id,source_role,source_text)
                          SELECT source_message_id,source_role,source_text FROM source_messages""")

    def _index_sid(self,sid):
        db=self.store.db
        if db.in_transaction:
            raise RuntimeError("product_source_index_requires_clean_transaction")
        row=self.store._source(str(sid))
        if row is None:return
        with db:
            db.execute("DELETE FROM product_source_fts WHERE source_message_id=?",(str(sid),))
            db.execute("INSERT INTO product_source_fts(source_message_id,source_role,source_text) VALUES(?,?,?)",
                       (str(sid),row["source_role"],row["source_text"]))

    def _index_envelope(self,src):
        self._index_sid(source_message_id(src["conversation_id"],src["message_id"]))

    def ingest_source_envelope_only(self,src):
        r=super().ingest_source_envelope_only(src)
        self._index_envelope(src)
        return r

    def ingest_source(self,src,raw_projection=None):
        r=super().ingest_source(src,raw_projection=raw_projection)
        if r.get("kind")=="ingested":
            self._index_envelope(src)
        return r

    def confirm(self,action_id):
        # Capture trusted pending source identity before the exact frozen atomic
        # transition consumes it, then update only the product retrieval index.
        row=self.transition._row(action_id)
        payload=self.transition._verify_row(row) if row else None
        r=super().confirm(action_id)
        if payload:
            sid=source_message_id(payload["conversation_id"],payload["message_id"])
            self._index_sid(sid)
        return r

    def _raw_source_hits(self,query,limit):
        tt=ref._query_tokens(query)
        if not tt:return []
        fq=" OR ".join('"'+x.replace('"','')+'"' for x in tt)
        return [dict(r) for r in self.store.db.execute(
          """SELECT source_message_id,source_role,source_text,
                    bm25(product_source_fts) AS score
             FROM product_source_fts
             WHERE product_source_fts MATCH ?
             ORDER BY score LIMIT ?""",(fq,int(limit))).fetchall()]

    def _source_by_conv_seq(self,conv,seq):
        r=self.store.db.execute(
          """SELECT * FROM source_messages
             WHERE conversation_id=? AND message_seq=? AND lifecycle='active'
             ORDER BY source_message_id LIMIT 1""",(str(conv),int(seq))).fetchone()
        return dict(r) if r else None

    def retrieve(self,query,limit=7):
        db=self.store.db
        if db.in_transaction:
            raise RuntimeError("product_retrieve_requires_clean_transaction_boundary")
        rows=[];seen=set()
        def add(item):
            key=(item.get("text"),item.get("authority"),item.get("source_id"))
            if key in seen:return
            seen.add(key);rows.append(item)

        # Claim FTS path from accepted R47.
        for r in self.store.recall(query,mode="history",limit=max(limit*3,12)):
            ext=self._external_sid(r["source_message_id"])
            add({"text":r["text"],"authority":r["authority"],"source_id":ext,
                 "channel":"claim","effective_at":r.get("effective_at")})

        # Product persistent source FTS; no full source scan and no write-side
        # transaction during retrieval.
        def add_src(src,channel):
            if not src or src.get("lifecycle")!="active":return
            auth="conversation_history" if src["source_role"]=="assistant" else "user_source_history"
            add({"text":src["source_text"],"authority":auth,
                 "source_id":self._external_sid(src["source_message_id"]),
                 "channel":channel,"source_role":src["source_role"],
                 "effective_at":int(src["effective_at"])})

        for hit in self._raw_source_hits(query,max(limit*3,12)):
            src=self.store._source(hit["source_message_id"])
            add_src(src,"raw_source_hit")
            if src and src.get("lifecycle")=="active":
                conv=src["conversation_id"];seq=int(src["message_seq"])
                add_src(self._source_by_conv_seq(conv,seq-1),"adjacent_turn")
                add_src(self._source_by_conv_seq(conv,seq+1),"adjacent_turn")

        rank={"user_state":0,"user_conflict":1,"user_history":2,"user_source_history":3,
              "derived_history":4,"conversation_history":5}
        def relevance(x):
            qt=set(ref._query_tokens(query));tt=set(ref._query_tokens(str(x.get("text") or "")))
            return len(qt&tt)
        rows.sort(key=lambda x:(rank.get(str(x.get("authority") or ""),9),
                                -relevance(x),str(x.get("source_id") or ""),
                                str(x.get("text") or "")))
        if db.in_transaction:
            raise RuntimeError("product_retrieve_leaked_transaction")
        return rows[:limit]

    def answer(self,question):
        rr=self.retrieve(question,limit=7)
        # Any conflict endpoint that independently satisfies the question makes
        # ordinary answer selection unsafe.  This is narrower than blocking on
        # unrelated conflicts elsewhere in memory.
        conflict=[r for r in rr if str(r.get("authority") or "")=="user_conflict"]
        def conflict_relevant(r):
            text=str(r.get("text") or "")
            if not text.strip() or qa._nonassertive(text) or qa._possessive_subject_mismatch(question,text):
                return False
            if qa._choice_question(question):
                return qa._subject_overlap(question,text)>0
            return qa._lexical_overlap(question,text)>0
        if any(conflict_relevant(r) for r in conflict):
            return None,True,rr

        if not qa._assistant_action_question(question):
            admitted=[r for r in rr if str(r.get("authority") or "")!="conversation_history"]
        else:
            admitted=rr
        supported=qa.select_supported(question,admitted)
        if not supported:
            return None,True,rr
        return supported[0]["text"],False,rr

__all__=["ProductShadowR52Composition"]
