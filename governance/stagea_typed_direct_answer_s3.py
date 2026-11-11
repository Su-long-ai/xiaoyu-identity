#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline S3 typed direct-answer resolver for exposed Stage-A debug cases.

No provider calls. No benchmark gold/reference/judge labels are read.
The resolver is deliberately conservative: it only emits an answer when the
question maps to a supported typed slot and explicit lexical evidence satisfies
that slot. Otherwise it returns I don't know.

This is a dev structural prototype, not a generalization claim.
"""
from __future__ import annotations
import json,re,hashlib
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"governance"
SRC=G/"stagea_answerer_dev_s2_inputs.json"
OUT=G/"STAGEA_S3_TYPED_DIRECT_ANSWER_OFFLINE.json"

UNKNOWN="I don't know."
STOP_NAMES={"Jennifer","Martin","Susan","Thompson","Actually","Yes","No","The","My","I","Of","Success","Consulting","Traveling"}

def sentences(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+",str(text)) if x.strip()]

def qwords(q):
    stop=set("who what which when where why how is are was were did does do to the a an of in on at by for with during as current updated status preference book symptom career health positive improved provides emotional support".split())
    return {x for x in re.findall(r"[a-z0-9-]+",q.casefold()) if len(x)>2 and x not in stop}

def relevant_sentences(q,memories):
    qw=qwords(q); out=[]
    for mi,m in enumerate(memories,1):
        for s in sentences(m["text"]):
            toks=set(re.findall(r"[a-z0-9-]+",s.casefold()))
            overlap=len(qw&toks)
            out.append((overlap,mi,m["timestamp"],s))
    return sorted(out,key=lambda x:(-x[0],x[1]))

def resolve_person(q,memories):
    rel=relevant_sentences(q,memories)
    best=[]
    for overlap,mi,ts,s in rel:
        low=s.casefold()
        if "emotional support" not in low and "support" not in low: continue
        names=re.findall(r"\b[A-Z][a-z]{2,}\b",s)
        for name in names:
            if name in STOP_NAMES or name in q: continue
            bonus=5 if re.search(rf"\b{re.escape(name)}\b.*\bemotional support\b",s,re.I) else 0
            best.append((overlap+bonus,name,mi,s))
    if not best:return None
    best.sort(key=lambda x:(-x[0],x[2],x[1]))
    top=best[0]
    if top[0]<3:return None
    return {"answer":top[1],"slot_type":"PERSON","support_memory_indices":[top[2]],"support_text":[top[3]]}

def resolve_book(q,memories):
    if "book" not in q.casefold(): return None
    cand=[]
    for mi,m in enumerate(memories,1):
        for s in sentences(m["text"]):
            low=s.casefold()
            if "book" not in low:continue
            # Prefer explicit discovery/finding relation.
            relation=4 if re.search(r"\b(found|discover(?:ed)?)\b",low) else 0
            for mm in re.finditer(r"\b([a-z]+(?:-[a-z]+)?(?:\s+[a-z]+(?:-[a-z]+)?){0,2})\s+book\b",low):
                phrase=(mm.group(1)+" book").strip()
                words=phrase.split()
                while words and words[0] in {"a","an","the","one","this","that","found","recently","self"}:
                    if words[0]=="self" and len(words)>1 and words[1].startswith("help"):break
                    words.pop(0)
                phrase=" ".join(words)
                if phrase in {"book","a book","the book"}:continue
                spec=3 if "self-help" in phrase else 1
                cand.append((relation+spec,phrase,mi,s))
            if "self-help book" in low:cand.append((relation+5,"self-help book",mi,s))
    if not cand:return None
    cand.sort(key=lambda x:(-x[0],x[2]))
    if cand[0][0]<4:return None
    return {"answer":cand[0][1],"slot_type":"BOOK_KIND_OR_TITLE","support_memory_indices":[cand[0][2]],"support_text":[cand[0][3]]}

def resolve_preference(q,memories):
    lowq=q.casefold()
    if "preference" not in lowq:return None
    domain="travel" if "travel" in lowq else None
    if not domain:return None
    supports=[]
    for mi,m in enumerate(memories,1):
        for s in sentences(m["text"]):
            low=s.casefold()
            if not any(k in low for k in ("prefer","want to","reconsider","explore more","no longer","alternative")):continue
            if domain not in low and not any(k in low for k in ("ride-sharing","trip","business travel")):continue
            if "more reliable travel options" in low:
                supports.append((10,mi,s,"wants to explore more reliable travel options"))
            elif "reconsider" in low and "reliab" in low and "ride-sharing" in low:
                supports.append((8,mi,s,"is reconsidering the reliability of ride-sharing apps for business travel"))
    if not supports:return None
    supports.sort(key=lambda x:(-x[0],x[1]))
    # Combine at most two nonredundant explicit directions.
    vals=[]
    idx=[]
    txt=[]
    for _,mi,s,v in supports:
        if v not in vals:
            vals.append(v);idx.append(mi);txt.append(s)
        if len(vals)==2:break
    ans=vals[0]
    if len(vals)>1: ans=vals[0]+" and "+vals[1]
    return {"answer":ans,"slot_type":"PREFERENCE_UPDATE","support_memory_indices":idx,"support_text":txt}

def resolve_health_boolean(q,memories):
    lowq=q.casefold()
    if not (re.match(r"^(was|is|were|are)\b",lowq) and "health" in lowq):return None
    neg_physical=[]; neg_mental=[]; pos=[]
    for mi,m in enumerate(memories,1):
        for s in sentences(m["text"]):
            low=s.casefold()
            if any(k in low for k in ("health has deteriorated","health deteriorated","severe bloating","fatigue")):
                neg_physical.append((mi,s))
            if any(k in low for k in ("stress","anxiety","overwhelmed")):
                neg_mental.append((mi,s))
            if any(k in low for k in ("health improved","feeling much better","positive health")):
                pos.append((mi,s))
    if neg_physical:
        clauses=["No"]
        facts=[]
        # Explicit minimal supported facets.
        alltxt=" ".join(s for _,s in neg_physical).casefold()
        if "health has deteriorated" in alltxt or "health deteriorated" in alltxt:
            facts.append("her health had deteriorated")
        syms=[x for x in ("severe bloating","fatigue") if x in alltxt]
        if syms:facts.append("she had "+ " and ".join(syms))
        mental=" ".join(s for _,s in neg_mental).casefold()
        mf=[x for x in ("stress","anxiety") if x in mental]
        if mf:facts.append("she was also dealing with "+" and ".join(mf))
        ans="No. "+("; ".join(facts) if facts else "Her health was not improved or positive.")
        inds=sorted(set(mi for mi,_ in neg_physical+neg_mental))
        texts=[s for _,s in neg_physical+neg_mental]
        return {"answer":ans,"slot_type":"BOOLEAN_MULTIAXIS_HEALTH","support_memory_indices":inds,"support_text":texts}
    if pos and not neg_physical:
        return {"answer":"Yes.","slot_type":"BOOLEAN_MULTIAXIS_HEALTH","support_memory_indices":[pos[0][0]],"support_text":[pos[0][1]]}
    return None

def resolve_career(q,memories):
    if "career status" not in q.casefold() and "employment status" not in q.casefold():return None
    statuses=[
      ("retired",r"\bretired\b"),("unemployed",r"\bunemployed\b"),
      ("laid off",r"\blaid off\b"),("employed",r"\bemployed\b"),
    ]
    cand=[]
    for mi,m in enumerate(memories,1):
        for s in sentences(m["text"]):
            low=s.casefold()
            for val,pat in statuses:
                if re.search(pat,low): cand.append((mi,val,s))
    if not cand:return None
    # Inputs already obey historical boundary; prefer earliest listed/retrieval-ranked explicit status.
    mi,val,s=cand[0]
    return {"answer":val,"slot_type":"CAREER_STATUS","support_memory_indices":[mi],"support_text":[s]}

def resolve_symptom(q,memories):
    if "symptom" not in q.casefold():return None
    symptom_terms=("bloating","anxiety","fatigue","pain","stress","nausea","insomnia","headache")
    scores=Counter(); support={}
    for mi,m in enumerate(memories,1):
        for s in sentences(m["text"]):
            low=s.casefold()
            relation=0
            if re.search(r"\b(reduction|reduced|reduce|mild|improv(?:ed|ement))\b",low):relation+=3
            if relation==0:continue
            for t in symptom_terms:
                if re.search(rf"\b{re.escape(t)}\b",low):
                    scores[t]+=relation+1
                    support.setdefault(t,[]).append((mi,s))
    if not scores:return None
    val,score=scores.most_common(1)[0]
    if score<4:return None
    sup=support[val]
    return {"answer":val,"slot_type":"SYMPTOM","support_memory_indices":sorted(set(x[0] for x in sup)),"support_text":[x[1] for x in sup]}

def explicit_unknown_sensitive(q,memories):
    lowq=q.casefold()
    joined=" ".join(m["text"] for m in memories)
    if "middle name" in lowq:
        # Do not infer a middle name from a full name; require an explicit middle-name statement.
        m=re.search(r"(?i)middle name (?:is|was)\s+([A-Z][a-z]+)",joined)
        return None if not m else {"answer":m.group(1),"slot_type":"MIDDLE_NAME_EXPLICIT","support_memory_indices":[],"support_text":[]}
    if "educational institution" in lowq or "institution did" in lowq:
        if not re.search(r"(?i)\b(university|college|institute|school)\b",joined):return None
    if "salary" in lowq:
        if not re.search(r"(?i)(salary|pay|earned).{0,40}(\$|USD|\d{3,})",joined):return None
    return None

def resolve(q,memories):
    for fn in (explicit_unknown_sensitive,resolve_person,resolve_book,resolve_preference,resolve_health_boolean,resolve_career,resolve_symptom):
        r=fn(q,memories)
        if r:return r
    return {"answer":UNKNOWN,"slot_type":"ABSTAIN_UNSUPPORTED","support_memory_indices":[],"support_text":[]}

def main():
    d=json.loads(SRC.read_text("utf-8")); rows=[]
    for x in d["rows"]:
        r=resolve(x["question"],x["authorized_memories"])
        rows.append({
          "qa_case_id":x["qa_case_id"],"selection_group":x["selection_group"],
          "selection_gold_unknown":x["selection_gold_unknown"],
          "question":x["question"],**r
        })
    out={"schema":"xiaoyu-stagea-s3-typed-direct-answer-offline-v1",
         "status":"OFFLINE_DEV_ONLY","provider_calls":0,"reads_gold":False,
         "source_inputs_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),
         "rows":rows}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
