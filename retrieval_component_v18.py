# -*- coding: utf-8 -*-
from __future__ import annotations
import collections,math,re
from datetime import datetime,timezone
import numpy as np
from research_components.retrieval.components.hybrid_bge_bm25_rrf import LocalBGE
from research_components.retrieval.components.multifacet_bge import facet_queries

RRF_K=60;SEM_DEPTH=120;SEED_KEEP=8;HOP1_KEEP=6;HOP2_KEEP=6
ENTITY_RE=re.compile(r"\b(?:[A-Z][a-z]+\s+[A-Z][a-z]+|Team\s+[A-Z][a-z]+|Orchid\s+Lab(?:\s+\d+)?)\b")
REL_RE=re.compile(r"\b(?:person|manager|mentor|colleague|coworker|partner|gave|given|presented)\b",re.I)
WORD_RE=re.compile(r"[A-Za-z][A-Za-z'-]*")
ID_STOP={"The","This","That","For","Outside","After","Before","During","Where","Which","What","Who","How","If",
         "Among","At","On","In","From","To","A","An","And","But","He","She","They","It","I"}
MAX_ANCHOR_DF=48

def legacy_anchors(text):
    return tuple(dict.fromkeys(" ".join(x.split()) for x in ENTITY_RE.findall(str(text))))
def identity_anchors(text):
    out=[]
    for raw in WORD_RE.findall(str(text)):
        z=raw.strip("'-")
        if z.lower().endswith("'s") or z.lower().endswith("’s"):
            z=z[:-2]
        if not z or z in ID_STOP:continue
        if (len(z)>=2 and z.isupper()) or (len(z)>=2 and z[0].isupper() and any(c.islower() for c in z[1:])):
            out.append(z.casefold())
    return tuple(dict.fromkeys(out))
def epoch(value):
    if value in (None,""):return None
    s=str(value).strip()
    try:
        if s.endswith("Z"):s=s[:-1]+"+00:00"
        d=datetime.fromisoformat(s)
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:return None

class NovelIdentityPathV17:
    component_id="novel_identity_path_v18_possessive"
    def __init__(self):self.model=LocalBGE()
    def prepare(self,documents):
        docs=[dict(d) for d in documents]
        texts=[f"{d.get('speaker','')}: {d.get('text','')}" for d in docs]
        emb=self.model.encode(texts,batch_size=64,max_length=256,query=False)
        legacy=[];legacy_by=collections.defaultdict(list);raw=[];df=collections.Counter()
        for i,d in enumerate(docs):
            la=legacy_anchors(d.get("text",""));legacy.append(la)
            for a in la:legacy_by[a].append(i)
            aa=identity_anchors(d.get("text",""));raw.append(aa);df.update(set(aa))
        n=max(1,len(docs));idf={a:math.log((n+1)/(c+0.5)) for a,c in df.items() if 2<=c<=MAX_ANCHOR_DF}
        ids=[];by=collections.defaultdict(list)
        for i,aa in enumerate(raw):
            keep=tuple(a for a in aa if a in idf);ids.append(keep)
            for a in keep:by[a].append(i)
        return {"documents":docs,"embeddings":emb,"legacy":legacy,"legacy_by":dict(legacy_by),
                "ids":ids,"by":dict(by),"idf":idf,"times":[epoch(d.get("timestamp")) for d in docs]}
    def _semantic(self,q,state):
        facets=facet_queries(q)
        if not facets:return []
        qemb=self.model.encode(facets,batch_size=16,max_length=128,query=True)
        demb=np.asarray(state["embeddings"],dtype=np.float32);score=collections.Counter()
        for x in qemb:
            order=np.argsort(-(demb@x),kind="stable")
            for r,i in enumerate(order[:SEM_DEPTH].tolist(),1):score[int(i)]+=1/(RRF_K+r)
        docs=state["documents"];return [i for i,_ in sorted(score.items(),key=lambda kv:(-kv[1],str(docs[kv[0]]["id"])))]
    def _legacy_expand(self,frontier,state,exclude):
        docs=state["documents"];score=collections.Counter()
        for rank,i in enumerate(frontier,1):
            for a in state["legacy"][i]:
                neigh=state["legacy_by"].get(a,());fan=max(1,len(neigh)-1)
                for j in neigh:
                    if j==i or j in exclude:continue
                    score[int(j)]+=1/((rank+1)*fan)
        return [i for i,_ in sorted(score.items(),key=lambda kv:(-kv[1],str(docs[kv[0]]["id"])))]
    def _baseline(self,q,state,limit):
        base=self._semantic(q,state);cap=int(limit)
        if not base:return [],base
        if not REL_RE.search(str(q)):return base[:cap],base
        sel=[]
        def add(seq,n):
            z=0
            for i in seq:
                if i in sel:continue
                sel.append(i);z+=1
                if z>=n or len(sel)>=cap:break
        seeds=base[:SEED_KEEP];add(seeds,SEED_KEEP)
        h1=self._legacy_expand(seeds,state,set(sel));add(h1,HOP1_KEEP)
        h2=self._legacy_expand(h1[:HOP1_KEEP],state,set(sel));add(h2,HOP2_KEEP)
        add(base,cap-len(sel));return sel[:cap],base
    def _best_next(self,current,used,path,state):
        bridge=set(state["ids"][current])-set(used)
        if not bridge:return None
        cand=collections.Counter()
        for a in bridge:
            w=state["idf"].get(a,0.0)
            for j in state["by"].get(a,()):
                if j==current or j in path:continue
                cand[int(j)]+=w*w
        if not cand:return None
        t1=state["times"][current]
        rows=[]
        for j,edge in cand.items():
            t2=state["times"][j]
            gap=abs(t2-t1) if t1 is not None and t2 is not None else 10**18
            # Prefer more/newer bridge identity evidence, then temporal locality.
            shared=len(bridge & set(state["ids"][j]))
            rows.append((-edge,-shared,gap,str(state["documents"][j]["id"]),j))
        rows.sort()
        return rows[0][-1]
    def rank(self,query,*,state,limit=20,metadata=None):
        docs=state["documents"];sel,semantic=self._baseline(query,state,limit)
        if not sel:return []
        qids=set(identity_anchors(query))
        seeds=[i for i in sel if qids & set(state["ids"][i])][:3]
        if not seeds:return [docs[i]["id"] for i in sel]
        chain=[]
        for seed in seeds:
            path=[seed];used=set(qids)
            for _ in range(2):
                nxt=self._best_next(path[-1],used,set(path),state)
                if nxt is None:break
                used |= set(state["ids"][path[-1]])
                path.append(nxt)
            for i in path:
                if i not in chain:chain.append(i)
        out=[]
        for i in chain+sel+semantic:
            if i not in out:out.append(i)
            if len(out)>=int(limit):break
        return [docs[i]["id"] for i in out]
def create_component():return NovelIdentityPathV17()
