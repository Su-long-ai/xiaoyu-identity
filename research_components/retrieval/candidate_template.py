# -*- coding: utf-8 -*-
"""Copy this file into your ACTIVE research workspace and replace only the ranking logic.

Fast-lane contract:
- input documents are already authority/lifecycle filtered by ProductMemoryBridge;
- do not read benchmark gold, answers, case IDs, or external-200 diagnostics;
- return only IDs that already exist in the supplied documents;
- final context cap is enforced by the shared runner;
- do not modify write-side memory or answerer behavior.
"""
from __future__ import annotations

class CandidateComponent:
    component_id = "replace_me"

    def prepare(self, documents):
        # Precompute any reusable local state here.
        return {"documents": [dict(d) for d in documents]}

    def rank(self, query, *, state, limit=20, metadata=None):
        documents = state["documents"]
        # Replace this baseline with the research idea.
        words = {x.casefold() for x in str(query).split() if len(x) > 2}
        scored = []
        for i,d in enumerate(documents):
            text = str(d.get("text","")).casefold()
            score = sum(w in text for w in words)
            scored.append((score, i, str(d["id"])))
        scored.sort(key=lambda x:(-x[0], x[1], x[2]))
        return [documents[i]["id"] for _,i,_ in scored[:int(limit)]]

def create_component():
    return CandidateComponent()
