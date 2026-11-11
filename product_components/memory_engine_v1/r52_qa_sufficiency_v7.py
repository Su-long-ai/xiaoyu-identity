#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic QA evidence-sufficiency gate for R52 remediation.

Retrieval relevance is necessary but not sufficient for a resolved answer.
This module never reads benchmark IDs/gold and never calls a model.
"""
from __future__ import annotations
import re
from typing import Iterable

STOP={
 "what","which","where","when","who","why","how","did","does","do","is","are","was","were",
 "my","me","i","the","a","an","for","to","of","and","or","in","on","at","with","from",
 "this","that","it","your","you","have","has","had","be","been"
}
UNCERTAINTY=[
 r"\bmaybe\b",r"\bperhaps\b",r"\bpossibly\b",r"\bpossible\b",r"\bpossibility\b",
 r"\bhypothetical\b",r"\bexample\b",r"\bguess(?:ing|ed)?\b",r"\bunsure\b",
 r"\buncertain\b",r"\bunknown\b",r"\bdo not know\b",r"\bdon't know\b",
 r"\bnot sure\b",r"\bnot a decision\b",r"\bnot a choice\b",r"\bnot selected\b",
 r"\bnot chosen\b",r"\bnot decided\b",r"\bhave not selected\b",r"\bhave not chosen\b",
 r"\bhave not decided\b",r"\bhas not selected\b",r"\bhas not chosen\b",
 r"\bnever provided\b",r"\bnot provided\b",r"\bno .{0,40}\b(?:chosen|selected|decided|provided|confirmed)\b",
 r"\bnot .{0,50}\byou (?:chose|selected|decided|picked)\b"
]
KINSHIP={"mother","father","sister","brother","parent","parents","wife","husband","partner",
         "daughter","son","friend","colleague","coworker","boss","child","children"}

COMMITMENT_TOKEN_CANON={
 "reservation":"reserve","reservations":"reserve","reserved":"reserve","reserving":"reserve",
 "selection":"select","selections":"select","selected":"select","selecting":"select",
 "decision":"decide","decisions":"decide","decided":"decide","deciding":"decide",
 "booking":"book","bookings":"book","booked":"book",
 "confirmation":"confirm","confirmations":"confirm","confirmed":"confirm","confirming":"confirm",
 "finalization":"finalize","finalized":"finalize","finalizing":"finalize",
 "settled":"settle","settling":"settle",
 "choice":"choose","choices":"choose","chosen":"choose","choosing":"choose","chose":"choose",
 "picked":"pick","picking":"pick",
 "preference":"prefer","preferences":"prefer","preferred":"prefer","preferring":"prefer",
}

def _tokens(text:str)->set[str]:
    xs=re.findall(r"[a-z0-9]+",str(text).casefold())
    out=set()
    for x in xs:
        if x in COMMITMENT_TOKEN_CANON:
            x=COMMITMENT_TOKEN_CANON[x]
        elif len(x)>4 and x.endswith("ing"): x=x[:-3]
        elif len(x)>3 and x.endswith("ed"): x=x[:-2]
        elif len(x)>3 and x.endswith("s"): x=x[:-1]
        if len(x)>1 and x not in STOP and not x.isdigit():
            out.add(x)
    return out

def _lexical_overlap(question:str,text:str)->int:
    return len(_tokens(question)&_tokens(text))

CHOICE_ACTION_TOKENS={"choose","select","decide","pick","finalize","settle","book","reserve","confirm","set"}
UNRESOLVED_PATTERNS=(
 r"\bshortlist\b",r"\bunder consideration\b",
 r"\b(?:am|are|is|still|currently)\s+weigh(?:ing|ed)?\b",
 r"\b(?:am|are|is|still|currently)\s+compar(?:ing|ed)?\b",
 r"\boptions?\b",r"\bcandidates?\b",
 r"\btoss[- ]?up\b",r"\bdown to\b",r"\bone of\b",r"\btorn between\b",
 r"\bsplit between\b",r"\bboth remain\b",r"\bboth still\b",r"\bboth .{0,30}\bviable\b",
 r"\bstill contenders?\b",r"\bstill in the running\b",r"\bequally acceptable\b",
 r"\bfinalists?\b",r"\b(?:decision|selection|booking|reservation|final call)\s+is\s+still\s+open\b",
 r"\b(?:decision|selection|booking|reservation|final call)\s+(?:comes|will be|is)\s+(?:later|tomorrow|pending)\b",
 r"\b(?:booking|decision|selection|reservation)\s+is\s+still\s+pending\b",
 r"\bhave(?:n't| not)\s+committed\b",r"\bnot committed\b",
 r"\bneither .{0,30}\b(?:chosen|selected|decided|picked|finalized|booked|reserved|confirmed)\b",
 r"\btentative(?:ly)?\b",r"\blean(?:ing)?\b",
 r"\bprefer(?:red|ence)?\b",r"\bfavorite\b",
 r"\b(?:have|has)(?:n't| not)\s+(?:booked|reserved|finalized|settled|confirmed|selected|chosen|decided)\b",
 r"\bnot\s+(?:booked|reserved|finalized|settled|confirmed|selected|chosen|decided)\b",
)

USER_COMMIT_PATTERNS=(
 r"\b(?:i|we)\s+(?:have\s+)?(?:chose|chosen|selected|decided|picked|confirmed|set|finalized|settled(?:\s+on)?|booked|reserved)\b",
 r"\bmy\s+(?:chosen|selected|confirmed|finalized|booked|reserved)\b.{0,50}\bis\b",
 r"\bmy\s+.{0,40}\b(?:choice|selection|decision|booking|reservation)\s+is\b",
)
ASSISTANT_COMMIT_PATTERNS=(
 r"\byou\b.{0,60}\b(?:chose|chosen|selected|decided|picked|set|confirmed|finalized|settled|booked|reserved)\b",
 r"\byour\s+(?:chosen|selected|confirmed|finalized|booked|reserved)\b.{0,50}\bis\b",
 r"\byour\s+.{0,40}\b(?:choice|selection|decision|booking|reservation)\s+is\b",
)

SUBJECT_HEAD_CANON={
    "inn":"hotel","lodge":"hotel","hostel":"hotel",
    "bistro":"venue","cafe":"venue","restaurant":"venue","diner":"venue",
    "dinner":"venue",
}

def _subject_tokens(text:str)->set[str]:
    raw=_tokens(text)-CHOICE_ACTION_TOKENS
    return {SUBJECT_HEAD_CANON.get(x,x) for x in raw}

def _subject_overlap(question:str,text:str)->int:
    q=_subject_tokens(question)
    t=_subject_tokens(text)
    return len(q&t)

def _spans(patterns,text:str):
    out=[]
    for p in patterns:
        out.extend((m.start(),m.end()) for m in re.finditer(p,text))
    return sorted(out)

def _resolved_choice_structure(text:str,authority:str)->tuple[bool,bool]:
    """Return (explicit_commitment, unresolved_without_later_commitment)."""
    low=" ".join(str(text).casefold().replace("’","'").split())
    unresolved=_spans(UNRESOLVED_PATTERNS,low)
    pats=ASSISTANT_COMMIT_PATTERNS if authority=="conversation_history" else USER_COMMIT_PATTERNS
    commits=_spans(pats,low)
    explicit=bool(commits)
    if not unresolved:
        return explicit,False
    last_unresolved=max(x[1] for x in unresolved)
    later=any(start>=last_unresolved for start,_ in commits)
    return explicit,later is False

def _nonassertive(text:str)->bool:
    low=" ".join(str(text).casefold().split())
    return any(re.search(p,low) for p in UNCERTAINTY)

def _assistant_action_question(question:str)->bool:
    q=str(question).casefold()
    return ("assistant" in q or "you recommend" in q or "you suggest" in q) and bool(
        re.search(r"\b(recommend(?:ed|ation)?|suggest(?:ed|ion)?)\b",q))

def _assistant_action_assertion(text:str)->bool:
    low=str(text).casefold()
    return bool(re.search(r"\b(i|we)\s+(?:would\s+)?(?:recommend|recommended|suggest|suggested)\b",low))

def _choice_question(question:str)->bool:
    q=str(question).casefold()
    return bool(re.search(
        r"\b(?:choose|chosen|select(?:ed|ion)?|decide(?:d|decision)?|pick(?:ed)?|"
        r"finaliz(?:e|ed|ation)|settle(?:d)?|book(?:ed|ing)?|reserve(?:d|ation)?|"
        r"confirm(?:ed|ation)?|choice|selection|decision|booking|reservation)\b",
        q,
    ))

def _direct_user_choice(text:str,authority:str)->bool:
    low=" ".join(str(text).casefold().replace("’","'").split())
    explicit,unresolved_without_later=_resolved_choice_structure(low,authority)
    if unresolved_without_later:
        return False

    if authority in ("user_state","user_history","user_source_history"):
        if explicit:
            return True
        # A canonical/current direct state can lose the original choice verb.
        # Accept only a simple single-valued nominal after all unresolved guards.
        if authority in ("user_state","user_source_history") and re.search(r"^my\s+.{1,45}\s+is\s+[^.;]+[.]?$",low):
            return True
        return False
    if authority=="conversation_history":
        return explicit
    return False

def _possessive_subject_mismatch(question:str,text:str)->bool:
    q=str(question).casefold()
    t=str(text).casefold().replace("’","'")
    if " my " not in " "+q+" " and not q.startswith("my "):
        return False
    qtokens=_tokens(q)
    # If the question asks about the user's X, evidence about a relative's X is not support.
    for kin in KINSHIP:
        if re.search(rf"\b(?:my|your)\s+{re.escape(kin)}(?:'s|s')\b",t):
            tail=t[re.search(rf"\b(?:my|your)\s+{re.escape(kin)}(?:'s|s')\b",t).end():]
            if qtokens & _tokens(tail):
                return True
    return False

def evidence_supports(question:str,row:dict)->bool:
    text=str(row.get("text") or "")
    auth=str(row.get("authority") or "")
    if not text.strip():
        return False
    if _choice_question(question):
        if _subject_overlap(question,text)<=0:
            return False
    elif _lexical_overlap(question,text)<=0:
        return False
    if _nonassertive(text):
        return False
    if _possessive_subject_mismatch(question,text):
        return False

    if _assistant_action_question(question):
        return auth=="conversation_history" and _assistant_action_assertion(text)

    if _choice_question(question):
        return _direct_user_choice(text,auth)

    # Semantic current/history claims are already grounded by R47/R49 and are
    # sufficient when they overlap the requested fact and are not uncertain.
    if auth in ("user_state","user_history"):
        return True

    low=text.casefold()
    if auth=="user_source_history":
        # Raw user evidence must itself be an affirmative first-person fact.
        return bool(
            re.search(r"\b(i am|i live|i work|i use|i prefer|i chose|i selected|i decided|i have|my .{1,50} is)\b",low)
        )
    if auth=="conversation_history":
        # Raw assistant history may support explicit assistant assertions about
        # the user, but not examples/guesses (already rejected above).
        return bool(
            re.search(r"\b(your .{1,60} is|you (?:are|live|work|use|prefer|chose|selected|decided|have))\b",low)
            or _assistant_action_assertion(text)
        )
    return False

def select_supported(question:str,rows:Iterable[dict])->list[dict]:
    xs=[r for r in rows if evidence_supports(question,r)]
    if _choice_question(question) and xs:
        # Choice answers must be unique at the highest-trust evidence layer.
        # This prevents a stale raw/history row from beating a current semantic
        # state, and prevents two competing raw/current choices from being
        # resolved by arbitrary retrieval order.
        choice_rank={"user_state":0,"user_history":1,"user_source_history":2,
                     "conversation_history":3,"derived_history":4,"user_conflict":5}
        best=min(choice_rank.get(str(r.get("authority") or ""),9) for r in xs)
        xs=[r for r in xs if choice_rank.get(str(r.get("authority") or ""),9)==best]
        distinct={" ".join(str(r.get("text") or "").casefold().split()) for r in xs}
        if len(distinct)>1:
            return []
        xs.sort(key=lambda r:(-_lexical_overlap(question,str(r.get("text") or "")),
                              str(r.get("source_id") or ""),str(r.get("text") or "")))
        return xs

    rank={"user_state":0,"user_history":1,"conversation_history":2,"user_source_history":3,
          "derived_history":4,"user_conflict":5}
    xs.sort(key=lambda r:(rank.get(str(r.get("authority") or ""),9),
                          -_lexical_overlap(question,str(r.get("text") or "")),
                          str(r.get("source_id") or ""),str(r.get("text") or "")))
    return xs
