#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R52 reusable composition v8: minimal runtime authority/retrieval repair over v7.

No storage/confirmation semantics change. This module reuses exact v7 composition,
reference-v7 raw-source retrieval, and v7 QA sufficiency. It adds only:
1) raw source + adjacent-turn retrieval parity with the reference candidate;
2) final ordinary-user-fact authority gate: conversation_history alone cannot
   establish a user fact, while explicit assistant-action questions remain allowed.
"""
from __future__ import annotations
import r52_composition_candidate_v7 as base
import r52_candidate_v7 as ref
import r52_qa_sufficiency_v7 as qa

stable=base.stable
public_canary_receipt=base.public_canary_receipt

class R52Composition(base.R52Composition):
    def retrieve(self,query,limit=7):
        rows=[]
        seen=set()
        def add(item):
            key=(item.get("text"),item.get("authority"),item.get("source_id"))
            if key in seen:return
            seen.add(key);rows.append(item)

        for x in super().retrieve(query,limit=max(limit,7)):
            add(dict(x))

        by_sid={x["source_message_id"]:x for x in self.store.source_history()}
        by_conv_seq={(str(x["conversation_id"]),int(x["message_seq"])):x
                     for x in self.store.source_history()}

        def add_src(src,channel):
            if not src:return
            auth="conversation_history" if src["source_role"]=="assistant" else "user_source_history"
            add({"text":src["source_text"],"authority":auth,
                 "source_id":self._external_sid(src["source_message_id"]),
                 "channel":channel,"source_role":src["source_role"],
                 "effective_at":int(src["effective_at"])})

        for hit in ref._raw_source_hits(self.store,query,max(limit*3,12)):
            src=by_sid.get(hit["source_message_id"])
            add_src(src,"raw_source_hit")
            if src:
                conv=str(src["conversation_id"]);seq=int(src["message_seq"])
                add_src(by_conv_seq.get((conv,seq-1)),"adjacent_turn")
                add_src(by_conv_seq.get((conv,seq+1)),"adjacent_turn")

        rank={"user_state":0,"user_conflict":1,"user_history":2,"user_source_history":3,
              "derived_history":4,"conversation_history":5}
        def relevance(x):
            qt=set(ref._query_tokens(query))
            tt=set(ref._query_tokens(str(x.get("text") or "")))
            return len(qt&tt)
        rows.sort(key=lambda x:(rank.get(str(x.get("authority") or ""),9),
                                -relevance(x),str(x.get("source_id") or ""),
                                str(x.get("text") or "")))
        return rows[:limit]

    def answer(self,question):
        rr=self.retrieve(question,limit=7)
        if not qa._assistant_action_question(question):
            admitted=[r for r in rr if str(r.get("authority") or "")!="conversation_history"]
        else:
            admitted=rr
        supported=qa.select_supported(question,admitted)
        if not supported:
            return None,True,rr
        return supported[0]["text"],False,rr
