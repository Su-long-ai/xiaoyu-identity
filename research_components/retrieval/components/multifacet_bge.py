# -*- coding: utf-8 -*-
from __future__ import annotations
import collections
import re
import numpy as np
from research_components.retrieval.components.hybrid_bge_bm25_rrf import LocalBGE

RRF_K = 60
MAX_FACETS = 4
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
SPLIT_RE = re.compile(
    r"\s*(?:[,;]|\band\b|\bor\b|\bbut\b|\bwhile\b|\bafter\b|\bbefore\b|\bbecause\b|\bwhen\b)\s*",
    re.I,
)
GENERIC_PREFIX_RE = re.compile(
    r"^(?:(?:what|when|where|who|which|how|why|did|does|do|has|have|had|"
    r"was|were|is|are|can|could|would|should)\b[\s,:-]*)+",
    re.I,
)
STOP = {
    "the","a","an","is","was","were","are","be","to","of","on","in","at","and",
    "or","what","when","where","who","which","how","why","did","does","do","has",
    "have","had","her","his","their","she","he","they","it","for","with","from",
    "as","by","about","into","that","this","these","those","during"
}

def _content_tokens(s):
    return [
        x.casefold() for x in TOKEN_RE.findall(str(s))
        if len(x) > 1 and x.casefold() not in STOP
    ]

def facet_queries(question):
    q = " ".join(str(question).split()).strip()
    if not q:
        return []
    out = [q]
    for part in SPLIT_RE.split(q):
        part = GENERIC_PREFIX_RE.sub("", part).strip(" ?.!:-")
        if len(_content_tokens(part)) < 3:
            continue
        if all(part.casefold() != x.casefold() for x in out):
            out.append(part)
        if len(out) >= MAX_FACETS:
            break
    return out

class MultiFacetComponent:
    component_id = "multifacet_bge_rrf_v1"

    def __init__(self):
        self.model = LocalBGE()

    def prepare(self, documents):
        texts = [f"{d.get('speaker','')}: {d.get('text','')}" for d in documents]
        emb = self.model.encode(texts, batch_size=64, max_length=256, query=False)
        return {"documents": [dict(d) for d in documents], "embeddings": emb}

    def rank(self, query, *, state, limit=20, metadata=None):
        documents = state["documents"]
        facets = facet_queries(query)
        if not documents or not facets:
            return []
        qemb = self.model.encode(facets, batch_size=16, max_length=128, query=True)
        demb = np.asarray(state["embeddings"], dtype=np.float32)
        score = collections.Counter()
        for q in qemb:
            order = np.argsort(-(demb@q), kind="stable")
            for rank,i in enumerate(order[:100].tolist(),1):
                score[int(i)] += 1.0/(RRF_K+rank)
        order = [
            i for i,_ in sorted(
                score.items(),
                key=lambda kv:(-kv[1], str(documents[kv[0]]["id"]))
            )[:int(limit)]
        ]
        return [documents[i]["id"] for i in order]

def create_component():
    return MultiFacetComponent()
