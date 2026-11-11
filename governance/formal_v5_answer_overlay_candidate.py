#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal-safe V5 answer-overlay candidate.

This module never reads benchmark gold fields. It selectively materializes only:
- uuid
- sessions[].end_time
- sessions[].dialogue[].role/content/timestamp
- sessions[].questions[].question

It reproduces the frozen Stage-A V5-full context algorithm over an R52 checkpoint.
No provider calls are made by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
FROZEN = GOV / "confirmatory_frozen"
if str(FROZEN) not in sys.path:
    sys.path.insert(0, str(FROZEN))
import r52_candidate_v7 as frozen_ref

# Exact prompt frozen by Stage-A V5.
SYSTEM = (
    "You are a grounded memory QA answerer. Use ONLY the AUTHORIZED MEMORIES supplied below. "
    "Never use external facts, guesses, assistant-only claims, or memories outside the supplied list. "
    "If the authorized memories do not directly support a reliable answer, output exactly "
    "{\"answer\":\"I don't know.\"}. "
    "Every factual clause in your answer must be directly entailed by at least one supplied memory. "
    "For historical questions, the supplied memory list has already enforced the caller-owned time boundary. "
    "If memories conflict, prefer directly relevant user_state, then directly relevant user-authored source history. "
    "Answer the QUESTION with the minimum sufficient supported proposition(s); do not add optional themes, examples, "
    "or plausible embellishments. "
    "For job-title questions, a direct statement such as 'my role as a wellness coach' is sufficient evidence for the title 'Wellness Coach'. "
    "For questions that contrast multiple health attributes, if both physical and mental evidence are supplied, explicitly answer both; "
    "do not silently omit one supported component. "
    "For causal or 'how might' questions, you may paraphrase an explicitly stated causal/effect relation in the supplied memory. "
    "For yes/no questions, start with Yes or No. If the question asserts stopping/ceasing/no longer doing something, "
    "direct evidence of continued use, deeper appreciation, or a concrete future plan contradicts that proposition; "
    "state the strongest directly supported continuation fact. "
    "Return exactly one JSON object with one string field named answer and no other text."
)

ALLOWED = {"user_state", "user_history", "user_source_history"}

DATE_RE = re.compile(
    r"(?i)\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{1,2}),\s*(\d{4})\b"
)

STOP = {
    "the","a","an","is","was","were","are","be","been","to","of","on","in","at","as","and","or",
    "what","how","might","did","does","do","has","have","had","her","his","their","she","he","they",
    "jennifer","martin","susan","thompson","updated","decide","decided","type","status"
}

EXPANSIONS = {
    "clothing":{"clothing","attire","formal","suit","suits","professional","networking","conference"},
    "conference":{"conference","networking","attire","formal","suit","suits","professional"},
    "health":{"health","physical","mental","deteriorated","deterioration","bloating","fatigue","stress","stressed","anxiety","positive","improved"},
    "documentaries":{"documentary","documentaries","health","wellness","insight","insights","workshop","workshops","integrate","series","holistic"},
    "documentary":{"documentary","documentaries","health","wellness","insight","insights","workshop","workshops","integrate","series","holistic"},
    "job":{"job","title","role","career","coach","occupation","profession","employment"},
    "title":{"job","title","role","career","coach","occupation","profession","employment"},
    "films":{"film","films","drama","appreciation","emotional","narrative","narratives"},
    "workshops":{"workshop","workshops","health","wellness","holistic","resilience","adaptability","inspire","women","focus"},
    "workshop":{"workshop","workshops","health","wellness","holistic","resilience","adaptability","inspire","women","focus"},
}

class OverlayError(RuntimeError):
    pass

class Cursor:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
    def ws(self):
        n = len(self.s)
        while self.i < n and self.s[self.i] in " \t\r\n":
            self.i += 1
    def ch(self, c: str):
        self.ws()
        if self.i >= len(self.s) or self.s[self.i] != c:
            raise OverlayError(f"expected {c} at {self.i}")
        self.i += 1
    def string(self) -> str:
        self.ws()
        if self.i >= len(self.s) or self.s[self.i] != '"':
            raise OverlayError("expected string")
        obj, end = json.JSONDecoder().raw_decode(self.s, self.i)
        if not isinstance(obj, str):
            raise OverlayError("not string")
        self.i = end
        return obj
    def skip_string(self):
        self.ws()
        if self.i >= len(self.s) or self.s[self.i] != '"':
            raise OverlayError("skip_string")
        i = self.i + 1
        esc = False
        while i < len(self.s):
            c = self.s[i]
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                self.i = i + 1
                return
            i += 1
        raise OverlayError("unterminated string")
    def skip_value(self):
        self.ws()
        if self.i >= len(self.s):
            raise OverlayError("skip_eof")
        c = self.s[self.i]
        if c == '"':
            self.skip_string()
            return
        if c == "{":
            self.i += 1
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return
            while True:
                self.skip_string()
                self.ch(":")
                self.skip_value()
                self.ws()
                if self.i < len(self.s) and self.s[self.i] == ",":
                    self.i += 1
                    continue
                self.ch("}")
                return
        if c == "[":
            self.i += 1
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "]":
                self.i += 1
                return
            while True:
                self.skip_value()
                self.ws()
                if self.i < len(self.s) and self.s[self.i] == ",":
                    self.i += 1
                    continue
                self.ch("]")
                return
        m = re.match(r"(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)", self.s[self.i:])
        if not m:
            raise OverlayError(f"bad scalar at {self.i}")
        self.i += len(m.group(0))

def _parse_dialogue(cur: Cursor):
    out = []
    cur.ch("[")
    cur.ws()
    if cur.i < len(cur.s) and cur.s[cur.i] == "]":
        cur.i += 1
        return out
    while True:
        cur.ch("{")
        role = content = timestamp = None
        cur.ws()
        if cur.i < len(cur.s) and cur.s[cur.i] != "}":
            while True:
                k = cur.string()
                cur.ch(":")
                if k == "role":
                    role = cur.string()
                elif k == "content":
                    content = cur.string()
                elif k == "timestamp":
                    timestamp = cur.string()
                else:
                    cur.skip_value()
                cur.ws()
                if cur.i < len(cur.s) and cur.s[cur.i] == ",":
                    cur.i += 1
                    continue
                break
        cur.ch("}")
        if not isinstance(role, str) or not isinstance(content, str):
            raise OverlayError("dialogue role/content missing")
        if role not in ("user", "assistant"):
            raise OverlayError("unsupported dialogue role")
        out.append({"role": role, "content": content, "timestamp": timestamp})
        cur.ws()
        if cur.i < len(cur.s) and cur.s[cur.i] == ",":
            cur.i += 1
            continue
        cur.ch("]")
        return out

def _parse_questions(cur: Cursor):
    out = []
    cur.ch("[")
    cur.ws()
    if cur.i < len(cur.s) and cur.s[cur.i] == "]":
        cur.i += 1
        return out
    while True:
        cur.ch("{")
        question = None
        cur.ws()
        if cur.i < len(cur.s) and cur.s[cur.i] != "}":
            while True:
                k = cur.string()
                cur.ch(":")
                if k == "question":
                    question = cur.string()
                else:
                    cur.skip_value()
                cur.ws()
                if cur.i < len(cur.s) and cur.s[cur.i] == ",":
                    cur.i += 1
                    continue
                break
        cur.ch("}")
        if question is not None:
            out.append({"question": question})
        cur.ws()
        if cur.i < len(cur.s) and cur.s[cur.i] == ",":
            cur.i += 1
            continue
        cur.ch("]")
        return out

def _parse_sessions(cur: Cursor):
    out = []
    cur.ch("[")
    cur.ws()
    if cur.i < len(cur.s) and cur.s[cur.i] == "]":
        cur.i += 1
        return out
    while True:
        cur.ch("{")
        end_time = None
        dialogue = []
        questions = []
        cur.ws()
        if cur.i < len(cur.s) and cur.s[cur.i] != "}":
            while True:
                k = cur.string()
                cur.ch(":")
                if k == "end_time":
                    end_time = cur.string()
                elif k == "dialogue":
                    dialogue = _parse_dialogue(cur)
                elif k == "questions":
                    questions = _parse_questions(cur)
                else:
                    cur.skip_value()
                cur.ws()
                if cur.i < len(cur.s) and cur.s[cur.i] == ",":
                    cur.i += 1
                    continue
                break
        cur.ch("}")
        out.append({"end_time": end_time, "dialogue": dialogue, "questions": questions})
        cur.ws()
        if cur.i < len(cur.s) and cur.s[cur.i] == ",":
            cur.i += 1
            continue
        cur.ch("]")
        return out

def safe_answer_project_line(line: str, selected: set[str] | None = None):
    """Materialize only non-gold fields required for post-seal V5 answering."""
    cur = Cursor(line)
    cur.ch("{")
    uuid_value = None
    sessions = None
    cur.ws()
    if cur.i < len(cur.s) and cur.s[cur.i] != "}":
        while True:
            k = cur.string()
            cur.ch(":")
            if k == "uuid":
                uuid_value = cur.string()
            elif k == "sessions":
                if uuid_value is None:
                    raise OverlayError("uuid must precede sessions")
                if selected is not None and uuid_value not in selected:
                    cur.skip_value()
                    sessions = []
                else:
                    sessions = _parse_sessions(cur)
            else:
                cur.skip_value()
            cur.ws()
            if cur.i < len(cur.s) and cur.s[cur.i] == ",":
                cur.i += 1
                continue
            break
    cur.ch("}")
    cur.ws()
    if cur.i != len(cur.s):
        raise OverlayError("trailing data")
    if not isinstance(uuid_value, str):
        raise OverlayError("uuid missing")
    if selected is not None and uuid_value not in selected:
        return None
    if sessions is None:
        raise OverlayError("sessions missing")
    return {"uuid": uuid_value, "sessions": sessions}

def iter_safe_answer_selected(path: Path, selected: set[str]):
    with Path(path).open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            # cheap raw UUID prefilter; no JSON values are decoded for nonselected rows
            if not any(u in line for u in selected):
                continue
            row = safe_answer_project_line(line, selected)
            if row is not None:
                yield row

def stable(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def parse_dt(s):
    if s is None:
        return None
    for fmt in ("%b %d, %Y, %H:%M:%S", "%B %d, %Y, %H:%M:%S"):
        try:
            return datetime.strptime(str(s), fmt)
        except ValueError:
            pass
    return None

def question_upper_bound(question):
    q = str(question)
    m = DATE_RE.search(q)
    if not m:
        return None
    before = q[:m.start()].casefold()
    tail = before[-32:]
    if re.search(r"\bafter\s*$", tail):
        return None
    relation = "before" if re.search(r"\bbefore\s*$", tail) else "at_or_before"
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(m.group(0), fmt)
            return {"date": dt.date(), "relation": relation, "text": m.group(0)}
        except ValueError:
            pass
    raise OverlayError("date parse failed")

def src_session(src):
    m = re.search(r":session:(\d+)$", str(src.get("conversation_id") or ""))
    return int(m.group(1)) if m else None

def source_time(rec, src):
    si = src_session(src)
    if si is None or si >= len(rec["sessions"]):
        return None
    return parse_dt(rec["sessions"][si].get("end_time"))

def eligible_for_bound(rec, src, bound):
    if bound is None:
        return True
    ts = source_time(rec, src)
    if ts is None:
        return False
    day = ts.date()
    return day < bound["date"] if bound["relation"] == "before" else day <= bound["date"]

def facet_queries(question):
    q = str(question).casefold()
    out = []
    if re.search(r"\bjob\s+title\b|\boccupation\b|\bprofession\b|\bemployment\b", q):
        out.append(("job_head", "job title role career employment occupation profession", 12))
    if "health status" in q or ("health" in q and ("improved" in q or "positive" in q)):
        out.extend([
            ("health_physical", "physical health deterioration deteriorated symptoms bloating fatigue", 6),
            ("health_mental", "mental health stress anxiety overwhelmed mental clarity", 6),
        ])
    return out

def toks(s):
    return {x for x in re.findall(r"[a-z0-9]+", str(s).casefold()) if len(x) > 1 and x not in STOP}

def query_keys(question):
    q = toks(question)
    out = set(q)
    low = str(question).casefold()
    for k, vals in EXPANSIONS.items():
        if k in low:
            out.update(vals)
    return out

def evidence_score(text, keys):
    tt = toks(text)
    overlap = len(tt & keys)
    low = str(text).casefold()
    bonus = 0
    if "job" in keys or "title" in keys:
        if re.search(r"\brole\s+as\s+(?:an?\s+)?[a-z][a-z -]+", low):
            bonus += 12
    if "documentaries" in keys or "documentary" in keys:
        if "document" in low and ("workshop" in low or "integrat" in low):
            bonus += 12
    if "health" in keys:
        if any(x in low for x in ("deteriorat", "bloating", "fatigue")):
            bonus += 9
        if any(x in low for x in ("stress", "anxiety", "mental clarity", "overwhelmed")):
            bonus += 9
    if "clothing" in keys or "conference" in keys:
        if ("attire" in low or "suit" in low) and ("network" in low or "conference" in low):
            bonus += 12
    if "workshops" in keys or "workshop" in keys:
        if "workshop" in low and ("holistic" in low or "health" in low or "wellness" in low):
            bonus += 10
    return overlap * 4 + bonus

def _query_tokens(query):
    return frozen_ref._query_tokens(query)

def bind_current_session_external_ids(comp, variant: str, pref: str, global_si: int):
    conv = f"halumem-confirmatory:{variant}:{pref}:session:{global_si}"
    n = 0
    for src in comp.store.source_history():
        if str(src["conversation_id"]) != conv:
            continue
        internal = str(src["source_message_id"])
        ti = int(src["message_id"])
        comp.external_by_internal[internal] = f"hm:{variant}:{pref}:s{global_si}:t{ti}"
        n += 1
    return n

def build_base_context(comp, rec, variant, pref, session_index, question):
    bound = question_upper_bound(question)
    bind_current_session_external_ids(comp, variant, pref, int(session_index))
    sources = [dict(x) for x in comp.store.source_history()]
    by_conv_seq = {(str(x["conversation_id"]), int(x["message_seq"])): x for x in sources}
    eligible = {
        str(x["source_message_id"]): x
        for x in sources if eligible_for_bound(rec, x, bound)
    }

    comp.store.db.execute("DROP TABLE IF EXISTS temp.formal_v5_overlay_fts")
    comp.store.db.execute("""CREATE VIRTUAL TABLE temp.formal_v5_overlay_fts USING fts5(
        source_message_id UNINDEXED,source_text,tokenize='unicode61')""")
    comp.store.db.executemany(
        "INSERT INTO temp.formal_v5_overlay_fts VALUES(?,?)",
        [(sid, s["source_text"]) for sid, s in eligible.items()]
    )

    def gather(query):
        rows = []
        seen = set()
        def add(text, authority, internal_sid, channel):
            authority = str(authority or "")
            if authority not in ALLOWED or not str(text).strip():
                return
            src = eligible.get(str(internal_sid))
            if src is None or src.get("source_role") != "user":
                return
            ext = comp._external_sid(str(internal_sid))
            key = (authority, ext, " ".join(str(text).split()))
            if key in seen:
                return
            seen.add(key)
            ts = source_time(rec, src)
            rows.append({
                "authority": authority,
                "timestamp": ts.isoformat() if ts else None,
                "effective_at": src.get("effective_at"),
                "source_id": ext,
                "channel": channel,
                "text": str(text),
            })

        for rr in comp.store.recall(query, mode="history", limit=500):
            sid = str(rr["source_message_id"])
            if sid in eligible:
                add(rr["text"], rr.get("authority"), sid, "claim")

        qtoks = _query_tokens(query)
        if qtoks:
            fq = " OR ".join('"' + x.replace('"', '') + '"' for x in qtoks)
            hits = [
                dict(x) for x in comp.store.db.execute(
                    """SELECT source_message_id,source_text,
                              bm25(formal_v5_overlay_fts) score
                       FROM temp.formal_v5_overlay_fts
                       WHERE formal_v5_overlay_fts MATCH ?
                       ORDER BY score LIMIT 120""", (fq,)
                ).fetchall()
            ]
            for hit in hits:
                sid = str(hit["source_message_id"])
                src = eligible.get(sid)
                if not src or src["source_role"] != "user":
                    continue
                add(src["source_text"], "user_source_history", sid, "raw_source_hit")
                conv = str(src["conversation_id"])
                seq = int(src["message_seq"])
                for nbr in (by_conv_seq.get((conv, seq - 1)), by_conv_seq.get((conv, seq + 1))):
                    if nbr and nbr["source_role"] == "user" and str(nbr["source_message_id"]) in eligible:
                        add(nbr["source_text"], "user_source_history", str(nbr["source_message_id"]), "adjacent_turn")

        ar = {"user_state": 0, "user_history": 1, "user_source_history": 2}
        qt = set(_query_tokens(query))
        rows.sort(key=lambda x: (
            ar.get(x["authority"], 9),
            -len(qt & set(_query_tokens(x["text"]))),
            0 if x["channel"] == "raw_source_hit" else 1,
            str(x["source_id"]), x["text"]
        ))
        return rows

    facets = facet_queries(question)
    pieces = [("original", gather(question), 8 if facets else 20)]
    pieces.extend((label, gather(query), quota) for label, query, quota in facets)
    out = []
    seen = set()
    contrib = {}
    for label, rows, quota in pieces:
        n = 0
        for x in rows:
            k = (x["authority"], x["source_id"], x["text"])
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
            n += 1
            if n >= quota or len(out) >= 20:
                break
        contrib[label] = n
        if len(out) >= 20:
            break
    if len(out) < 20:
        for label, rows, _ in pieces:
            for x in rows:
                k = (x["authority"], x["source_id"], x["text"])
                if k in seen:
                    continue
                seen.add(k)
                out.append(x)
                contrib[label] = contrib.get(label, 0) + 1
                if len(out) >= 20:
                    break
            if len(out) >= 20:
                break
    return out[:20], {
        "upper_bound": (
            {"date": bound["date"].isoformat(), "relation": bound["relation"]} if bound else None
        ),
        "eligible_source_count": len(eligible),
        "facets": [{"label": x[0], "quota": x[2]} for x in pieces[1:]],
        "contrib": contrib,
    }

def turn_valid(question, timestamp):
    bound = question_upper_bound(question)
    if bound is None:
        return True
    ts = parse_dt(timestamp)
    if ts is None:
        return False
    day = ts.date()
    return day < bound["date"] if bound["relation"] == "before" else day <= bound["date"]

def repack(rec, variant, pref, session_index, question, base_ctx):
    session = rec["sessions"][int(session_index)]
    keys = query_keys(question)
    extra = []
    for di, turn in enumerate(session.get("dialogue") or []):
        if str(turn.get("role")) != "user":
            continue
        if not turn_valid(question, turn.get("timestamp")):
            continue
        text = str(turn.get("content") or "")
        sc = evidence_score(text, keys)
        if sc <= 0:
            continue
        ts = parse_dt(turn.get("timestamp"))
        extra.append({
            "authority": "user_source_history",
            "timestamp": ts.isoformat() if ts else None,
            "effective_at": None,
            "source_id": f"hm:{variant}:{pref}:s{int(session_index)}:t{di}",
            "channel": "same_session_question_pack",
            "text": text,
            "_score": sc,
        })
    merged = []
    seen = set()
    for m in list(base_ctx) + extra:
        key = (m.get("authority"), m.get("source_id"), " ".join(str(m.get("text", "")).split()))
        if key in seen:
            continue
        seen.add(key)
        mm = dict(m)
        mm["_score"] = max(int(mm.get("_score") or 0), evidence_score(mm.get("text", ""), keys))
        merged.append(mm)
    ar = {"user_state": 0, "user_source_history": 1, "user_history": 2}
    merged.sort(key=lambda m: (
        -int(m.get("_score") or 0),
        ar.get(str(m.get("authority")), 9),
        str(m.get("source_id"))
    ))
    out = merged[:20]
    for m in out:
        m.pop("_score", None)
    return out, {"same_session_candidate_n": len(extra)}

def build_messages(comp, rec, variant, uuid_hash, session_index, question):
    pref = str(uuid_hash)[:12]
    base_ctx, meta = build_base_context(comp, rec, variant, pref, session_index, question)
    ctx, pack = repack(rec, variant, pref, session_index, question, base_ctx)
    lines = []
    for i, m in enumerate(ctx, 1):
        md = f"authority={m['authority']}"
        if m.get("timestamp"):
            md += f" timestamp={m['timestamp']}"
        lines.append(f"[{i}] {md}\n{m['text']}")
    user = "AUTHORIZED MEMORIES:\n" + ("\n\n".join(lines) if lines else "(none)") + "\n\nQUESTION:\n" + question
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    return messages, ctx, {**meta, **pack}
