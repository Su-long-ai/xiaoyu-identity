# -*- coding: utf-8 -*-
"""XiaoYu candidate-to-product loop, built on the EXISTING task queue.

No agent execution, model requests, protected-set reads, release toggles or QQ sends.
A candidate is not a release: positive local research -> reversible M1 product trial
-> same-RC M2 answer/cost -> independent A1 review -> explicit pilot disposition.
Commands: py -3.11 product_promotion_loop.py sync|status|register|decide
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
import product_promotion_machine as machine

HERE = Path(__file__).resolve().parent
DB = HERE / "TASKS.sqlite3"
ROLES = {"M1": "MAINLINE", "M2": "MAINLINE", "A1": "AUDITOR"}
# Existing validated work. M1-X108 is deliberately kept as a NONPASS baseline.
SEEDS = [
 ("llm-intent-x134", "M3-X134", "LLM memory proposal + structural provenance, conditional SINGLECALL; recover Chinese NO_SAVE/delete generalization", 0, None, None, None, "durable_write", "X078 cached84; X134 structural240; old A1 P0 requires fresh same-RC audit"),
 ("lossless-capsule-x178", "D5-X178", "Read-only source capsule: public 5394 retrieval positive; cached actual answer 0/2 to 2/2", 4, "M1-X111", "M2-X160", "A1-X141", "read_only", "Do not count 5394 retrieval as 5394 improved final answers"),
 ("multiview-x179", "D2-X179", "Authority-bound multi-view source search; paired DeepSeek lexical 1/2 to semantic 2/2", 6, "M1-X112", None, None, "read_only", "M2-X159 and A1-X140 were COMPONENT evidence, not same M1 product SHA"),
 ("two-view-long-x165", "D2-X165", "Long-source two-view page; M2 exact real answer baseline 0/2 to candidate 2/2 with high token cost", 10, "M1-X107", "M2-X154", None, "read_only", "Prefer authorized selected section/span expansion instead of stuffing whole long source"),
 ("convomem-model-session-x175", "D2-X175", "ConvoMem model-led source session: M2-X156 positive tiny real final-answer paired result", 12, None, None, None, "read_only", "Reuse D2-X175 session; validate integration with M1 current RC and same-SHA consumer."),
 ("user-evidence-x096", "M2-X096", "Keep retriever full stream; answer only authenticated non-assistant facts, with contradiction fallback: final11/24->13/24 gain3/loss1 and prompt input -74.2%", 8, "M1-X060", None, None, "read_only", "M1-X063 dual-view compatibility also DONE; M2-X096 is component evidence, not new M1 same-SHA"),
 ("conditional-doc-x070", "M2-X070", "Revive X037 only for document-like scope: new public40 same-answer baseline11->17 gain6/loss0, old104 gain6/loss4", 9, "M1-X042", None, None, "answer", "A1-X069 fresh24 activation 0/24; repair general runtime query/source trigger; no unconditional SAFE-lite"),
 ("hypothesis-stage-x046", "D3-X046", "Hypothesis-first reversible natural preference updates: frozen72 final55->63 gain8/loss0, separate42 35->40 gain5/loss0; 20+14 fewer clarifications", 11, None, None, None, "durable_write", "Proposals stay non-authoritative; real source-bound owner confirmation must remain"),
 ("current-work-x058", "D3-X058", "Authoritative current-work preference projection: paired final-answer0/8->8/8 on targeted failures; controls and stale exclusion held", 12, None, None, None, "read_only", "Need unrelated-query control and product same-SHA final answer, no benchmark category runtime routes"),
 ("speaker-scope-x045", "D4-X045", "Multi-party source attribution: exact17/78->72/78, zero forbidden writes/64, legitimate14/14, 5 scoring-span mismatches and one real alias miss", 14, None, None, None, "durable_write", "STRICT NONPASS does not warrant discarding separable principal/subject/scope fields; no auto commit without provenance"),
 ("pareto-top7-x118", "D2-X118", "Top7 evidence Pareto: public full5394 +78/-1 vs base, same net with 50% fewer losses than X117", 15, None, None, None, "read_only", "Only retrieval evidence proven; request limited final answer sample; preserve source eligibility"),
 ("false-idk-verifier-x082", "M3-X082", "Conditional verifier for evidence-complete IDK: public29 10->21 gain12/loss1; disjoint24 1->3 gain2/loss0", 16, None, None, None, "answer", "Only trigger after IDK with adequate authorized evidence, cost/p95 concern; avoid extra calls on all answers"),
 ("source-attribution-x065", "D3-X065", "Independent model-led source-attribution for write proposals: combined40 16->40 gain24/loss0; 0 unsafe state across targeted cases", 17, None, None, None, "durable_write", "Reuse with M3-X134 rather than duplicate safety architecture; extra model 2.3-3.7s so parallel/conditional"),
 ("utility-tail-x101", "D2-X101", "Top20 evidence tail budget: full5394 net+30 complete vs V18, reduce known evidence-eviction false IDK", 20, None, None, None, "read_only", "Previously M2-X104 cost-free checks; new M1 same-RC effect missing"),
 ("on-demand-html-x158", "D2-X158", "Specialized long-HTML BM25: targeted authorized 27/29 source rescue; on-demand only due 758 irrelevant cards if static", 22, None, None, None, "read_only", "May overlap already integrated D2-X162/M1-X105; check exact semantics before any extra M1 patch"),
 ("permission-expiry-oneshot-x071", "D3-X071", "Composed one-shot+expiry semantic state: 40/40 vs best single prior +20/loss0, restart40/40", 23, None, None, None, "durable_write", "Do not enable external actions or grants; reuse policy backend if permission features become launch-scope"),
 ("collision-idempotence-x080", "D3-X080", "Same source-event ID with conflicting timestamp/actor/content must not launder provenance: combined40 6->40", 24, None, None, None, "durable_write", "Small deterministic exact-identity primitive; product source-bound boundary if currently missing"),
 ("deferred-retract-x131", "D1-X131", "Unresolved explicit RETRACT enters bounded deferred parser instead of silent discard: independent held45/45 vs44/45", 26, None, None, None, "durable_write", "No immediate mutation on unresolved target, 0 false retract; confirm final state and answer"),
 ("tiny-router-x120", "D6-X120", "Tiny depth3 decision tree saved 14.01/16.50/14.14% in three walk-forward blocks; failed 75% RF retention by 1.57pp", 28, None, None, None, "cost", "Classic over-strict threshold; real provider savings unverified, compare with X119 and current caching"),
 ("prefix-cache-x114", "D6-X114", "Prior-first full parser serialization raises adjacent LCP>=1024 from0/249 to184/249; no semantic field changes", 30, None, None, None, "cost", "Idealized caching bound only, no observed provider cache savings; selected/pruned path does NOT benefit"),
 ("third-unseen-pair-x112", "D5-X112", "Adds unseen third pair to rescue zero-evidence packet 9->15, but fixed Top16 complete drops net34; conditional allocator only", 37, None, None, None, "read_only", "DO NOT promote global fixed third pair. Compare run-time query-score chosen breadth/depth within fixed budget."),
 ("safelite-scoped-x037", "M3-X037", "GroundRAG SAFE-lite base2/11 to7/11 gain5/loss0 dev; independent A1 found cross-person attribution errors", 50, None, None, None, "answer", "Only typed arithmetic/grounded premise correction substeps under source-bound controls; original all-purpose adapter must remain OFF"),
 ("batch-ingress-x122", "D1-X122", "Semantic segmentation and shadow batch write cost candidate", 13, "M1-X103", None, None, "durable_write", "Must preserve correction/delete freshness; M1-X103 was shadow/default OFF"),
 ("lifecycle-x108-nonpass", "M1-X108", "Current rules ingress: known public19 passed but new A1 8/24 with 12 durable P0", 90, "M1-X108", "M2-X157", "A1-X136", "durable_write", "HOLD_P0: old phrase-bound classifier; do not re-enable or reuse A1 hidden examples"),
]

def connect(path=DB):
    c=sqlite3.connect(str(path),timeout=20,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    return c

def init(c):
    c.execute("""CREATE TABLE IF NOT EXISTS product_candidates (
        id TEXT PRIMARY KEY, source_task TEXT NOT NULL, source_sha TEXT,
        value TEXT NOT NULL, priority INTEGER NOT NULL, integration_task TEXT,
        answer_task TEXT, audit_task TEXT, risk TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '', decision TEXT NOT NULL DEFAULT 'UNDECIDED',
        decision_note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
        updated_at REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS product_candidate_support (
        candidate_id TEXT NOT NULL, source_task TEXT NOT NULL,
        source_sha TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY(candidate_id,source_task))""")
    c.execute("""CREATE TABLE IF NOT EXISTS product_bundle_assignments (
        candidate_id TEXT PRIMARY KEY, bundle_task TEXT NOT NULL,
        bundle_family TEXT NOT NULL, created_at REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS product_research_intake_checkpoint (
        name TEXT PRIMARY KEY, last_updated REAL NOT NULL,
        last_id TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS product_successor_handoffs (
        parent_id TEXT NOT NULL, m1_task TEXT NOT NULL,
        reason TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY(parent_id,m1_task))""")
    machine.init(c)

def source_evidence(c,task_id):
    row=c.execute("SELECT status,artifact FROM tasks WHERE id=?",(task_id,)).fetchone()
    if row is None or row[0]!="DONE" or not row[1]:
        return None
    p=Path(row[1])
    if not p.is_file() or p.stat().st_size==0:
        return None
    # Exact file bytes are SHA-anchored. Do not inspect model data or sealed gold.
    return hashlib.sha256(p.read_bytes()).hexdigest()

def seed(c):
    init(c)
    now=time.time()
    for cid,source,value,priority,m1,m2,a1,risk,note in SEEDS:
        c.execute("""INSERT OR IGNORE INTO product_candidates
          (id,source_task,source_sha,value,priority,integration_task,answer_task,
           audit_task,risk,note,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          (cid,source,source_evidence(c,source),value,priority,m1,m2,a1,
           risk,note,now,now))
    c.execute("""UPDATE product_candidates SET source_sha=?,updated_at=?
      WHERE id='llm-intent-x134' AND source_sha IS NULL""",
      (source_evidence(c,"M3-X134"),now))
    # Preserve known BAD original implementation as a negative control;
    # the separate LLM-intent candidate owns its repair, not a duplicate branch.
    c.execute("""UPDATE product_candidates SET decision='HOLD_P0',updated_at=?
      WHERE id='lifecycle-x108-nonpass' AND decision='UNDECIDED'""",(now,))

def measured_research_value(outcome):
    """Candidate radar: positive *measured* value, including conditional Pareto.

    Broad intake is REVIEW_VALUE (not a product pass) unless a risk is
    explicitly classified. Real persistent privacy P0 is never relaxed.
    """
    head=str(outcome or "")[:4500]
    if re.search(r"\b(?:PASS_GAIN|PRODUCT_CANDIDATE|PROMOTION_READY|PARETO_GAIN|COST_GAIN)\b",head,re.I):
        return True
    if re.search(r"\+[1-9]\d*\s*/\s*-?\d+|\b(?:GAIN|GAINS)\s*[1-9]\d*\b|\bNET\s*\+\s*[1-9]\d*\b",head,re.I):
        return True
    for match in re.finditer(r"(\d{1,4})\s*/\s*(\d{1,4})\s*(?:->|→|到)\s*(\d{1,4})\s*/\s*(\d{1,4})",head):
        if match.group(2)==match.group(4) and int(match.group(3))>int(match.group(1)):
            return True
    if re.search(r"(?:节省|降低|减少|saved?|reduc(?:e|ed)|saving).*?\b\d+(?:\.\d+)?%.*?(?:token|cost|latency|context|api|request|费用|上下文|调用|字节)",head,re.I|re.S):
        return True
    return False


def scoped_risk_hint(title):
    """Only infer an isolated trial's scope for unmistakably named research.

    Not an audit conclusion: product RC must still verify all source authority.
    Ambiguous work remains in REVIEW_VALUE rather than being silently dropped.
    """
    name=str(title or "").lower()
    # Research-to-product rescue recognizes bounded read-only candidates,
    # not task-only confirmations or state-mutating operations.
    if re.search(r"(?:\b(?:test|re-test|validation|confirmation|fixtures|dev\d+)\b|"
                 r"\bintegrate\b|\b(?:write|mutation|commit|permission|grant|revoke|"
                 r"ingress|delete|correct|retract|no.save|owner.fact|cancellation|"
                 r"cancel|expiry|consume)\b)",name) and not re.search(
                 r"\bzero[-_ ]write\b",name):
        return "unknown"
    if re.search(r"(?:\b(?:readctx|retriev(?:al|er)|read_ref|source.search|bm25|"
                 r"rerank|search results?|semantic source|source expansion|"
                 r"source paging|multi[-_ ]?probe|query|top(?:7|20)|"
                 r"hyde|embedding|sibling expansion|anchor.rescue|rank)\b"
                 r"|rrf|quoted[-_ ]span|document[-_ ]anchor)",name,re.I):
        return "read_only"
    if re.search(r"\b(?:cache optimization|parser cost|token cost|billing reduction|latency saving)\b",name):
        return "cost"
    return "unknown"


def research_mixed_review(outcome):
    """Keep rejected/failed-but-interesting results review-only, not discarded.

    Negated safety statements such as NO_DURABLE_P0 and P0=0 are not failures.
    """
    head=str(outcome or "")[:800].upper()
    head=re.sub(r"NO_(?:DURABLE|MATERIAL|PRIVACY)_P0|(?:MATERIAL_)?P0\s*[=:]\s*0\b",
                "NO_SAFETY_ISSUE",head)
    return bool(re.search(r"(?:^|[_\W])(?:STOP|REJECT|NONPROMOTE|FAIL|P0|UNSAFE|LEAK)(?:$|[_\W])",head))


def register_task(c,task_id,value=None,priority=40,risk="unknown",review_only=False):
    """Idempotent DONE-task intake for explicit handoffs and measured PASS_GAIN."""
    init(c)
    if review_only:
        risk="unknown"
    sha=source_evidence(c,task_id)
    if not sha:
        return {"status":"WAIT_PRODUCER_EVIDENCE","source":task_id}
    t=c.execute("SELECT track,title FROM tasks WHERE id=?",(task_id,)).fetchone()
    if not t or t[0]=="A1":
        return {"status":"NOT_RESEARCH_PRODUCER","source":task_id}
    # Deduplicate different candidate IDs pointing to the same exact source.
    # A seed or earlier explicit registration already owns product handoff.
    existing=c.execute("""SELECT id,source_sha,risk FROM product_candidates
       WHERE source_task=? ORDER BY CASE WHEN id LIKE 'auto-%' THEN 1 ELSE 0 END,id LIMIT 1""",
       (task_id,)).fetchone()
    if existing:
        if existing["source_sha"] and existing["source_sha"]!=sha:
            return {"status":"SOURCE_SHA_CHANGED_REVIEW","candidate":existing["id"],"source_sha":sha}
        if not existing["source_sha"]:
            c.execute("UPDATE product_candidates SET source_sha=?,updated_at=? WHERE id=?",
                      (sha,time.time(),existing["id"]))
        if review_only and existing["id"].startswith("auto-"):
            c.execute("""UPDATE product_candidates SET risk='unknown',
               note=note||?,updated_at=? WHERE id=? AND note NOT LIKE '%LEGACY_MIXED_VERDICT_REVIEW_ONLY%'""",
               (" | LEGACY_MIXED_VERDICT_REVIEW_ONLY: no automatic scoped promotion",
                time.time(),existing["id"]))
        elif risk!="unknown" and existing["risk"]=="unknown":
            c.execute("UPDATE product_candidates SET risk=?,priority=?,updated_at=? WHERE id=?",
                      (risk,int(priority),time.time(),existing["id"]))
        return {"status":"ALREADY_REGISTERED_SOURCE","candidate":existing["id"],"source_sha":sha}
    # M1 is allowed only through an explicit register, never automatic
    # fast.py DONE discovery; source SHA still required.
    ident="auto-"+task_id.lower()
    now=time.time()
    c.execute("""INSERT OR IGNORE INTO product_candidates
       (id,source_task,source_sha,value,priority,risk,note,created_at,updated_at)
       VALUES (?,?,?,?,?,?,?,?,?)""",
      (ident,task_id,sha,(value or t[1])[:400],int(priority),risk,
       "Automatic research gain intake; retrieval/state-only effect is not an answer gain." +
       (" | LEGACY_MIXED_VERDICT_REVIEW_ONLY: no automatic scoped promotion"
        if review_only else ""),
       now,now))
    if risk!="unknown":
        c.execute("""UPDATE product_candidates SET risk=?,priority=?,
           updated_at=? WHERE id=? AND risk='unknown' AND source_sha=?""",
           (risk,int(priority),now,ident,sha))
    return {"status":"REGISTERED_OR_ALREADY_PRESENT","candidate":ident,"source_sha":sha}

def link_support(c,candidate,source_task,reason):
    """Attach independent research evidence to an existing product family.

    This never claims that the linked mechanism is already in the frozen RC.
    It prevents another isolated full-runtime build of the same mechanism.
    """
    init(c)
    candidate_row=c.execute("SELECT id FROM product_candidates WHERE id=?",(candidate,)).fetchone()
    source_row=c.execute("SELECT track FROM tasks WHERE id=?",(source_task,)).fetchone()
    sha=source_evidence(c,source_task)
    if not candidate_row or not source_row or source_row[0] not in {"D1","D2","D3","D4","D5","D6","M2","M3"} or not sha:
        raise ValueError("Need registered product candidate and DONE public research evidence")
    if not reason or len(reason.strip())<14:
        raise ValueError("Specify reuse mechanism and product failure addressed")
    previous=c.execute("SELECT source_sha FROM product_candidate_support WHERE candidate_id=? AND source_task=?",
                       (candidate,source_task)).fetchone()
    if previous and previous[0]!=sha:
        return {"status":"SOURCE_SHA_CHANGED_REVIEW","candidate":candidate,"source_task":source_task}
    c.execute("""INSERT OR IGNORE INTO product_candidate_support
        (candidate_id,source_task,source_sha,reason,created_at) VALUES(?,?,?,?,?)""",
        (candidate,source_task,sha,reason.strip(),time.time()))
    # Reuse the already queued M1/M2/A1 work. Pending consumers must know
    # this research exists WITHOUT claiming that the frozen RC absorbed it.
    details=c.execute("""SELECT integration_task,answer_task,audit_task FROM product_candidates
                         WHERE id=?""",(candidate,)).fetchone()
    pending_titles=(f"PRODUCT REPAIR: {candidate}",f"PRODUCT VALUE REPAIR: {candidate}",
                    f"PRODUCT RUNTIME: {candidate}")
    linked_tasks=[]
    for tid,track,acceptance in c.execute("""SELECT id,track,acceptance FROM tasks
           WHERE status='PENDING' AND (
             id IN (?,?,?) OR (track='M1' AND title IN (?,?,?)))""",
           (*details,*pending_titles)):
        marker=f"[REUSE_EVIDENCE:{source_task}:{sha}]"
        if marker not in acceptance:
            c.execute("UPDATE tasks SET acceptance=acceptance||?,updated_at=? WHERE id=?",
                      (f"\n{marker} {reason.strip()} This is prior research support only; "
                       "do not count it as enabled in the frozen product RC unless "
                       "the exact bundled bytes and a same-RC product result prove it.",
                       time.time(),tid))
        linked_tasks.append({"task":tid,"track":track})
    return {"status":"LINKED_OR_ALREADY_PRESENT","candidate":candidate,
            "source_task":source_task,"source_sha":sha,"updated_pending_tasks":linked_tasks,
            "updated_pending_m1":[x["task"] for x in linked_tasks if x["track"]=="M1"]}


def support_list(c,candidate):
    return [{"source_task":r[0],"source_sha":r[1],"reason":r[2],
             "current_sha_matches":source_evidence(c,r[0])==r[1]}
            for r in c.execute("""SELECT source_task,source_sha,reason FROM product_candidate_support
                                   WHERE candidate_id=? ORDER BY source_task""",(candidate,))]


def support_handoff(c,candidate):
    items=support_list(c,candidate)
    if not items:
        return ""
    return (" Research support to CONSIDER, not yet in product RC: "+
            " | ".join(f"{x['source_task']} evidence_sha={x['source_sha']}; {x['reason']}"
                     for x in items if x["current_sha_matches"]) +
            " Reuse existing components and compare minimal actual effect; do not duplicate architecture.")


def answer_disposition(row):
    """Use published M2 product verdict; a completed test is not a gain."""
    if not row or row.get("status")!="DONE" or not row.get("artifact"):
        return "NOT_REVIEWED"
    p=Path(row["artifact"])
    if not p.is_file():
        return "NOT_REVIEWED"
    body=p.read_text("utf-8",errors="replace")[:9500].upper()
    # An answer gain from forced routing is not a product gain when the
    # actual autonomous route chooses the wrong option or skips retrieval.
    if re.search(r"(?:^|[_\W])(?:PRODUCT_NONPASS|PRODUCT_NONPROMOTE|NONPROMOTE_TRIGGER_COVERAGE)(?:$|[_\W])",body):
        return "NONPROMOTE_WITH_VALUE"
    return "MEASURED_OR_UNCLASSIFIED"


def task(c,tid):
    if not tid: return None
    r=c.execute("SELECT status,artifact,blocked_reason FROM tasks WHERE id=?",(tid,)).fetchone()
    return {"status":r[0],"artifact":r[1],"blocked_reason":r[2]} if r else {"status":"NOT_QUEUED","artifact":None,"blocked_reason":None}

def audit_disposition(row):
    """Distinguish material enabled-path P0 from ordinary capability NONPASS.

    Only published verdict summaries are read; sealed A1 material is never used.
    Ambiguous verdicts remain review-only and cannot imply release approval.
    """
    if not row or row.get("status")!="DONE" or not row.get("artifact"):
        return "NOT_REVIEWED"
    p=Path(row["artifact"])
    if not p.is_file():
        return "NOT_REVIEWED"
    head=p.read_text("utf-8",errors="replace")[:3000].upper()
    verdict=next((line.strip() for line in head.splitlines()[:12]
                  if re.search(r"\b(?:OUTCOME|VERDICT|DECISION)\s*:",line)),head[:350])
    # Read the declared verdict first. A positive audit may discuss the old
    # P0 it repaired, and a NONPASS can explicitly mean *capability* loss
    # with no actual P0. Do not decide from incidental words in that prose.
    token=re.search(r"(?:OUTCOME|VERDICT|DECISION)\s*:\s*([A-Z0-9_]+)",verdict)
    fallback=re.match(r"[A-Z0-9_]+",verdict)
    code=token.group(1) if token else (fallback.group(0) if fallback else "")
    # Explicit positive findings override even a contradictory PASS label.
    if re.search(r"(?:^|[_\W])(?:MATERIAL_)?P0\s*[=:]\s*[1-9]"
                 r"|\bP0\s+(?:PERSIST|REMAIN|STILL)\b",verdict):
        return "MATERIAL_P0"
    if code.startswith("PASS"):
        return "PASS"
    if code.startswith(("NONPASS","REJECT","FAIL")):
        if re.search(r"NO_(?:DURABLE|MATERIAL|PRIVACY|AUTHORITY|ADMISSIBILITY)_P0"
                     r"|NO_P0(?:_|$)|P0_(?:CLOSED|RESOLVED|FIXED)",code):
            return "NONP0_LIMITATION"
        if re.search(r"(?:MATERIAL|DURABLE|PRIVACY|AUTHORITY|ADMISSIBILITY)"
                     r"(?:_[A-Z0-9]+){0,3}_P0(?=$|[_\W])"
                     r"|(?:MATERIAL|DURABLE|PRIVACY|AUTHORITY|ADMISSIBILITY)"
                     r"(?:\s+\w+){0,2}\s+P0(?:\b|$)",verdict):
            return "MATERIAL_P0"
        return "NONP0_UNCLASSIFIED"
    return "NOT_REVIEWED"


def audit_nonpass(row):
    """Backward-compatible predicate: only confirmed material P0 blocks."""
    return audit_disposition(row)=="MATERIAL_P0"

def stage(c,x):
    source=source_evidence(c,x["source_task"])
    m1=task(c,x["integration_task"])
    m2=task(c,x["answer_task"])
    a1=task(c,x["audit_task"])
    if x["decision"]=="HOLD_P0" or (a1 and audit_nonpass(a1)):
        return "HOLD_P0_NEW_CANDIDATE_OR_REPAIR_REQUIRED"
    if x["decision"]=="HOLD_VALUE":
        return "HOLD_VALUE_REVISIT_ON_NEW_EVIDENCE"
    if not source:return "WAIT_SOURCE_EVIDENCE"
    if x["source_sha"] and source!=x["source_sha"]:return "SOURCE_SHA_CHANGED_REVIEW"
    if x["risk"]=="unknown":return "REVIEW_VALUE_CLASSIFICATION_BEFORE_TRIAL"
    if not m1:
        if "BUNDLE_REMAINDER:" in x["note"]:
            return "READY_M1_TRIAL"
        shared_bundle=c.execute(
            "SELECT bundle_task FROM product_bundle_assignments WHERE candidate_id=?",
            (x["id"],)).fetchone()
        if shared_bundle:
            job=c.execute("SELECT status FROM tasks WHERE id=?",(shared_bundle[0],)).fetchone()
            if job and job[0] in ("PENDING","ACTIVE"):
                return "M1_"+job[0]+"_BUNDLED"
            return "M1_BUNDLE_DONE_NEEDS_VERDICT" if job and job[0]=="DONE" else "REVIEW_BUNDLE_TASK"
        # A research source already attached to a real product family should
        # not spawn a second full runtime merely because its own candidate
        # was registered later. Retain provenance and await the parent's NEW RC.
        if x["id"].startswith("auto-") and c.execute(
            """SELECT 1 FROM product_candidate_support s
               JOIN product_candidates p ON p.id=s.candidate_id
               JOIN tasks m1 ON m1.id=p.integration_task
               WHERE s.source_task=? AND s.candidate_id<>?
                     AND m1.status IN ('ACTIVE','PENDING','DONE') LIMIT 1""",
               (x["source_task"],x["id"])).fetchone():
            return "SHARED_FAMILY_WAIT_NEW_RC"
        return "READY_M1_TRIAL"
    if m1["status"]=="BLOCKED":return "BLOCKED_M1_REPAIR"
    if m1["status"]!="DONE":return "M1_"+m1["status"]
    if not m1["artifact"] or not Path(m1["artifact"]).is_file():return "WAIT_M1_ARTIFACT"
    if not m2:return "READY_M2_SAME_RC"
    if m2["status"]=="BLOCKED" and any(term in (m2.get("blocked_reason") or "").lower()
                  for term in ("shadow_only","shadow-only","no product runtime","no answer entrypoint")):
        return "NEED_M1_REAL_RUNTIME_NOT_SHADOW"
    if m2["status"]!="DONE":return "M2_"+m2["status"]
    if not m2["artifact"] or not Path(m2["artifact"]).is_file():return "WAIT_M2_ARTIFACT"
    if not a1:return "READY_A1_SAME_RC"
    if a1["status"]!="DONE":return "A1_"+a1["status"]
    if not a1["artifact"] or not Path(a1["artifact"]).is_file():return "WAIT_A1_ARTIFACT"
    review=audit_disposition(a1)
    # Old capability NONPASS is not an absolute veto on a newer,
    # same-input, same-RC positive aggregate receipt.
    if review=="NONP0_LIMITATION" and not machine.positive(c,x["id"]):
        return "REPAIR_M1_NONP0_GENERALIZATION"
    if review=="NONP0_UNCLASSIFIED":
        return "REVIEW_A1_UNCLASSIFIED_NONPASS"
    if answer_disposition(m2)=="NONPROMOTE_WITH_VALUE" and not machine.positive(c,x["id"]):
        return "REPAIR_M1_PRODUCT_ANSWER"
    return machine.stage(c,x)

def bundle_family(c,x):
    """Small number of owner-aligned product work packages, not per-candidate engines."""
    stage_name=stage(c,x)
    if stage_name=="REVIEW_VALUE_CLASSIFICATION_BEFORE_TRIAL":
        return "evidence-triage"
    if stage_name!="READY_M1_TRIAL":
        return None
    title_row=c.execute("SELECT title FROM tasks WHERE id=?",(x["source_task"],)).fetchone()
    name=((title_row[0] if title_row else "")+" "+x["id"]).lower()
    if x["risk"]=="durable_write":
        return "memory-state"
    if x["risk"]=="answer":
        return "answer-guard"
    if x["risk"]=="cost":
        return "cost-efficiency"
    if re.search(r"document|html|file|page|doc[-_]|文档|文件",name):
        return "document-source"
    return "retrieval-source"


def bundle_coverage(c,infos):
    """Every candidate has owner/action; bundle tickets are *not* integration proof."""
    grouped={}
    for x in infos:
        family=bundle_family(c,x) if not x["integration_task"] else None
        if family:
            grouped.setdefault(family,[]).append(x)
    pending_ids={x["id"] for x in infos if not x["integration_task"]}
    ticket_rows={
        r["candidate_id"]:(r["bundle_task"],r["bundle_family"])
        for r in c.execute("SELECT candidate_id,bundle_task,bundle_family FROM product_bundle_assignments")
        if r["candidate_id"] in pending_ids
    }
    bundle_list=[]
    by_id={}
    for family,items in grouped.items():
        items.sort(key=lambda x:(x["priority"],x["id"]))
        for i in range(0,len(items),4):
            part=items[i:i+4]
            # Ticketed members may be in a different, earlier batch;
            # preserve their exact ticket rather than relying on current order.
            unclaimed=[x for x in part if x["id"] not in ticket_rows]
            if unclaimed:
                key=f"M1:{family}:{unclaimed[0]['id']}"
                bundle_list.append({"package":key,"owner":"M1","family":family,
                                    "candidates":[x["id"] for x in unclaimed],
                                    "priority":min(x["priority"] for x in unclaimed),
                                    "dispatch_state":"PLANNED_NOT_QUEUED","task":None})
                for x in unclaimed:by_id[x["id"]]=(key,None,"PLANNED_NOT_QUEUED")
    existing={}
    for cid,(tid,family) in ticket_rows.items():
        status=c.execute("SELECT status FROM tasks WHERE id=?",(tid,)).fetchone()
        state=("DONE_NEEDS_CANDIDATE_VERDICT" if status and status[0]=="DONE"
               else status[0] if status else "MISSING_TASK")
        existing.setdefault(tid,{"package":f"M1:{family}:{tid}","owner":"M1",
                                "family":family,"candidates":[],"priority":None,
                                "dispatch_state":state,"task":tid})["candidates"].append(cid)
        by_id[cid]=(f"M1:{family}:{tid}",tid,state)
    bundle_list.extend(existing.values())
    for x in infos:
        stage_name=x["stage"]
        if x["id"] in by_id:
            key,tid,state=by_id[x["id"]]
            x["assignment"]={"owner":"M1","work_package":key,"task":tid,
                  "dispatch_state":state,"next_action":(
                     "Record actual included candidate IDs and manifest SHA or explicit exclusion; otherwise no integration credit"
                     if state=="DONE_NEEDS_CANDIDATE_VERDICT" else
                     "Integrate explicitly selected candidates into ONE default-OFF RC; freeze SHA and request M2+A1"
                     if stage_name=="READY_M1_TRIAL" or stage_name.startswith("M1_") else
                     "Classify measured value, overlap, cost and actual P0; do not enable by default")}
            continue
        if stage_name=="SHARED_FAMILY_WAIT_NEW_RC":
            family=x["reused_by_product_families"][0] if x["reused_by_product_families"] else {}
            x["assignment"]={"owner":"M1","work_package":"SHARED:"+str(family.get("candidate","unassigned")),
                             "task":None,"dispatch_state":"SHARED_PARENT",
                             "next_action":"Verify research in the parent product family's NEW RC; do not duplicate its engine"}
            continue
        roles={"M1":"M1","M2":"M2","A1":"A1","LEAD_REVIEW":"LEAD"}
        owner=roles.get(x["next_owner"],"LEAD")
        linked=[]
        for field in ("integration_task","answer_task","audit_task"):
            tid=x[field]
            if not tid:continue
            row=c.execute("SELECT status FROM tasks WHERE id=?",(tid,)).fetchone()
            if row and row[0] in ("ACTIVE","PENDING"):linked.append((field,tid,row[0]))
        expected=("answer_task" if stage_name.startswith(("M2_","READY_M2"))
                  else "audit_task" if stage_name.startswith(("A1_","READY_A1"))
                  else "integration_task" if stage_name.startswith(("M1_","READY_M1"))
                  else None)
        active=next((entry for entry in linked if entry[0]==expected),None) if expected else None
        if not active and linked:
            active=linked[0]
        # Repair jobs produce a NEW candidate, so they are intentionally not
        # stored in the rejected parent's integration_task column.
        if not active:
            for next_job in x.get("successor_handoffs",[]):
                if next_job["status"] in ("ACTIVE","PENDING"):
                    active=("successor",next_job["task"],next_job["status"])
                    break
        if not active and stage_name.startswith(("HOLD_P0","REPAIR_M1","NEED_M1_REAL_RUNTIME")):
            for prefix in ("PRODUCT REPAIR","PRODUCT VALUE REPAIR","PRODUCT RUNTIME"):
                row=c.execute("""SELECT id,status FROM tasks WHERE track='M1'
                         AND title=? AND status IN ('ACTIVE','PENDING')
                         ORDER BY updated_at DESC LIMIT 1""",
                         (f"{prefix}: {x['id']}",)).fetchone()
                if row:
                    active=("repair",row[0],row[1])
                    break
        if stage_name.startswith("HOLD_P0"):
            action="Repair in a new RC; retain old A1 P0 and forbid old SHA default-on"
            if x["decision"]=="HOLD_P0":owner="LEAD"
        elif stage_name.startswith("REPAIR_M1"):action="Repair exact product trigger/generalization; new RC and same-SHA M2+A1"
        elif stage_name=="NEED_M1_REAL_RUNTIME_NOT_SHADOW":action="Replace shadow-only integration with one runnable default-OFF RC"
        elif stage_name.startswith("REVIEW_EXACT_SHA"):action="LEAD decide limited trial or hold using SAME-RC final answer and A1 evidence"
        elif stage_name.startswith("HOLD_VALUE"):action="Keep historical candidate; revisit only on new source-disjoint value evidence"
        elif stage_name.startswith(("READY_M1","M1_")):action="M1 integrate selected mechanism into one default-OFF RC, freeze SHA, then M2+A1"
        elif stage_name=="READY_M2_SAME_RC" or stage_name.startswith("M2_"):action="M2 check real model-led final answer, cost and regressions at exact frozen SHA"
        elif stage_name=="READY_A1_SAME_RC" or stage_name.startswith("A1_"):action="A1 audit enabled source/state safety at exact frozen SHA"
        else:action="Review source evidence or existing task status before product activation"
        x["assignment"]={"owner":owner,"work_package":"EXISTING:"+x["id"],
                          "task":active[1] if active else None,
                          "parallel_tasks":[{"role":entry[0],"task":entry[1],"status":entry[2]} for entry in linked],
                          "dispatch_state":active[2] if active else ("DEFERRED" if stage_name.startswith("HOLD_VALUE") else "DECISION_OR_QUEUE"),
                          "next_action":action}
    return bundle_list


def enqueue_bundles(c,candidates):
    """One bounded M1 ticket per 2-4 candidate package; never claim integrated."""
    covered={r[0] for r in c.execute("SELECT candidate_id FROM product_bundle_assignments")}
    groups={}
    for x in candidates:
        if x["id"] in covered or x["integration_task"]:continue
        family=bundle_family(c,x)
        if family:
            groups.setdefault(family,[]).append(x)
    result=[]
    for family,items in sorted(groups.items(),key=lambda kv:min(x["priority"] for x in kv[1])):
        items.sort(key=lambda x:(x["priority"],x["id"]))
        # Singletons retain the existing direct M1 handoff.
        if len(items)<2:continue
        members=items[:4]
        names=[x["id"] for x in members]
        needs_review=family=="evidence-triage"
        goal=(f"Package {family} candidates: "+", ".join(
            f"{x['id']} [{x['source_task']}, SHA {x['source_sha']}]" for x in members)+
            ". Work on ONE shared existing product runtime; evaluate overlap and "
            "actual enabled-path gain/loss, answer quality, token cost and safety. " +
            ("Classify each mechanism's positive/negative evidence and choose what is "
             "worth trial; do NOT integrate any mechanism without explicit source qualification. "
             if needs_review else
             "Integrate only the selected incremental components into a reversible default-OFF RC. ")+
            "Submit a result.md with NEW_RC_MANIFEST_SHA256=<real 64-character hash> and "
            "BUNDLE_INTEGRATED_CANDIDATES: comma-separated exact IDs for only those actually "
            "implemented and verified, or explicitly state NOT_INTEGRATED with reasons. "
            "An M1 DONE without these markers is NOT product integration. Preserve "
            "owner/privacy P0 and do not call paid models without approved scope.")
        title=f"PRODUCT BUNDLE: {family} / {names[0]}"
        tid=queue_task(c,"M1",title,goal,"Product candidate bundle: "+", ".join(names),
                       max(1,min(x["priority"] for x in members)+5))
        if not tid:continue
        for x in members:
            c.execute("""INSERT OR IGNORE INTO product_bundle_assignments
                    (candidate_id,bundle_task,bundle_family,created_at) VALUES(?,?,?,?)""",
                    (x["id"],tid,family,time.time()))
        result.append({"work_package":family,"task":tid,"track":"M1","candidates":names,
                       "kind":"TRIAGE" if needs_review else "PRODUCT_TRIAL"})
    return result


def adopt_finished_bundles(c):
    """Only explicitly certified members move to M2/A1. No bulk DONE shortcut."""
    adopted=[]
    q=c.execute("""SELECT DISTINCT b.bundle_task,t.artifact,t.status
        FROM product_bundle_assignments b JOIN tasks t ON t.id=b.bundle_task
        WHERE t.status='DONE'""")
    for tid,artifact,_ in q:
        if not artifact or not Path(artifact).is_file():continue
        content=Path(artifact).read_text("utf-8",errors="replace")[:10000]
        match=re.search(r"(?im)^\s*(?:-\s*)?BUNDLE_INTEGRATED_CANDIDATES\s*:\s*(.+)$",content)
        manifest=re.search(r"(?im)\bNEW_RC_MANIFEST_SHA256\s*[:=]\s*([a-f0-9]{64})\b",content)
        if not match or not manifest:continue
        # A failure, security hold or ambiguous outcome cannot be adopted
        # even if a stale integration marker is still present in the file.
        verdict=re.search(r"(?im)^\s*(?:-\s*)?(?:Outcome|Verdict):\s*(.+)$",content)
        if not verdict or not re.match(r"PASS(?:_|\b)",verdict.group(1),re.I) or research_mixed_review(verdict.group(1)):
            continue
        ids=[x.strip() for x in match.group(1).split(",")]
        allowed={x[0] for x in c.execute("SELECT candidate_id FROM product_bundle_assignments WHERE bundle_task=?",(tid,))}
        for cid in ids:
            if cid not in allowed:continue
            row=c.execute("SELECT integration_task FROM product_candidates WHERE id=?",(cid,)).fetchone()
            if not row or row[0]:continue
            c.execute("""UPDATE product_candidates SET integration_task=?,
                          note=note||?,updated_at=? WHERE id=?""",
                      (tid,f" | Bundled M1 verified via frozen RC {manifest.group(1)}",
                       time.time(),cid))
            adopted.append({"candidate":cid,"m1":tid,"new_rc_manifest":manifest.group(1)})
        # A partial PASS is not a permanent home for the excluded members.
        # Unselected candidates return to the bounded M1 queue; they keep
        # source evidence and must earn their own real RC.
        for cid in allowed-set(ids):
            row=c.execute("SELECT integration_task,note FROM product_candidates WHERE id=?",(cid,)).fetchone()
            if not row or row[0]:continue
            c.execute("DELETE FROM product_bundle_assignments WHERE candidate_id=? AND bundle_task=?",
                      (cid,tid))
            marker=f"BUNDLE_REMAINDER:{tid}"
            if marker not in row[1]:
                c.execute("""UPDATE product_candidates SET note=note||?,updated_at=? WHERE id=?""",
                          (f" | {marker} omitted from accepted M1 source; requeue for separate bounded trial",
                           time.time(),cid))
    return adopted


def snapshot(c):
    init(c)
    xs=[]
    cursor=c.execute("SELECT * FROM product_candidates ORDER BY priority,id")
    fields=[col[0] for col in cursor.description]
    for raw in cursor:
        x=dict(zip(fields,raw))
        info={k:x[k] for k in ("id","source_task","source_sha","priority","risk","value","integration_task","answer_task","audit_task","decision")}
        info["stage"]=stage(c,x)
        info["note"]=x["note"]
        info["successor_handoffs"]=successor_status(c,x["id"])
        info["reused_by_product_families"]=[
            {"candidate":r[0],"m1_task":r[1]} for r in c.execute(
                """SELECT s.candidate_id,p.integration_task
                   FROM product_candidate_support s
                   JOIN product_candidates p ON p.id=s.candidate_id
                   WHERE s.source_task=? AND s.candidate_id<>?
                   ORDER BY p.priority,s.candidate_id""",
                (x["source_task"],x["id"]))]
        info["support_evidence"]=support_list(c,x["id"])
        info["support_needing_m1_verification"]=bool(info["support_evidence"] and
            (not x["integration_task"] or
             (task(c,x["integration_task"]) or {}).get("status")=="DONE"))
        info["audit_disposition"]=audit_disposition(task(c,x["audit_task"]))
        info["answer_disposition"]=answer_disposition(task(c,x["answer_task"]))
        receipt=machine.current(c,x["id"])
        info["machine_benefit_verdict"]=(receipt.get("verdict") if receipt else "WAIT_RECEIPT")
        info["machine_benefit_net_final"]=(receipt.get("net_final_correct") if receipt else None)
        info["machine_final_answer_gate_pass"]=(receipt.get("final_answer_gate_pass") if receipt else None)
        info["machine_next_research_action"]=(receipt.get("next_research_action") if receipt else None)
        info["overall_capability_claim_eligible"]=(receipt.get("overall_capability_claim_eligible") if receipt else False)
        info["next_owner"]=("M1" if info["stage"].startswith(("READY_M1","M1_","NEED_M1","HOLD_P0","REPAIR_M1"))
                            else "M2" if info["stage"].startswith(("READY_M2","M2_"))
                            else "A1" if info["stage"].startswith(("READY_A1","A1_"))
                            else "M2" if info["stage"].startswith(("WAIT_MACHINE_PORTFOLIO","MACHINE_"))
                            else "LEAD_REVIEW" if info["stage"].startswith(("REVIEW_","HOLD_VALUE","WAIT_EXACT_SHA"))
                            else "SOURCE_REVIEW")
        m1=task(c,x["integration_task"])
        info["default_off_trial_available"]=bool(
            m1 and m1["status"]=="DONE" and m1["artifact"]
            and Path(m1["artifact"]).is_file() and not info["stage"].startswith("HOLD_P0")
        )
        xs.append(info)
    bundles=bundle_coverage(c,xs)
    for x in xs:
        x["next_owner"]=x["assignment"]["owner"]
    assignment_report={
        "covered":sum(bool(x.get("assignment",{}).get("owner") and
                            x["assignment"].get("next_action")) for x in xs),
        "total":len(xs),
        "uncovered":[x["id"] for x in xs if not x.get("assignment",{}).get("owner")],
        "planned_packages":sum(b["task"] is None for b in bundles),
        "ticketed_packages":sum(b["task"] is not None for b in bundles),
        "in_active_or_pending_package":sum(b["dispatch_state"] in ("ACTIVE","PENDING") for b in bundles),
        "note":"Plans assign responsibility; only PENDING/ACTIVE tasks are dispatched. A DONE bundle without per-candidate proof is not integrated."
    }
    blocked=[x for x in xs if x["stage"].startswith(("HOLD_P0","HOLD_MACHINE","BLOCKED_"))]
    open_= [x for x in xs if x["decision"]=="UNDECIDED" and not x["stage"].startswith(("WAIT_SOURCE","HOLD_"))]
    from collections import Counter
    stages=dict(Counter(x["stage"] for x in xs))
    adoption={
        "registered_research_candidates":len(xs),
        "m1_done_with_artifact":0,
        "m2_done_with_artifact":0,
        "a1_done_with_artifact":0,
        "m2_and_a1_reports_present":0,
        "default_off_trial_decision":sum(x["decision"]=="TRIAL_OFF" for x in xs),
        "default_on_product":0,  # this ledger has no deployment power
        "need_m1_product_work":sum(x["stage"].startswith(("READY_M1","M1_","REPAIR_M1","NEED_M1")) for x in xs),
        "need_value_classification":stages.get("REVIEW_VALUE_CLASSIFICATION_BEFORE_TRIAL",0),
        "research_reused_in_shared_product_family":stages.get("SHARED_FAMILY_WAIT_NEW_RC",0),
        "research_support_links":sum(len(x["support_evidence"]) for x in xs),
        "support_not_proven_in_m1_rc":sum(len(x["support_evidence"]) for x in xs
                                        if x["support_needing_m1_verification"]),
    }
    for x in xs:
        def delivered(tid):
            evidence=task(c,tid)
            return bool(evidence and evidence["status"]=="DONE" and evidence["artifact"]
                        and Path(evidence["artifact"]).is_file())
        m1_done=delivered(x["integration_task"])
        m2_done=delivered(x["answer_task"])
        a1_done=delivered(x["audit_task"])
        adoption["m1_done_with_artifact"]+=int(m1_done)
        adoption["m2_done_with_artifact"]+=int(m2_done)
        adoption["a1_done_with_artifact"]+=int(a1_done)
        adoption["m2_and_a1_reports_present"]+=int(m2_done and a1_done)
    gains_path=HERE/"results"/"product_promotion"/"RESEARCH_GAINS_INDEX_20261106.json"
    unmapped=[]
    if gains_path.is_file():
        registered={x["source_task"] for x in xs}
        for signal in json.loads(gains_path.read_text(encoding="utf-8")):
            if signal["id"] not in registered:
                unmapped.append({"source_task":signal["id"],"title":signal["title"][:120]})
    rescue_path=HERE/"results"/"product_promotion"/"REJECTED_WITH_VALUE_SIGNALS_20261106.json"
    suspect_rescue=json.loads(rescue_path.read_text(encoding="utf-8")) if rescue_path.is_file() else []
    return {"schema":"xiaoyu-product-promotion-loop-v1",
            "enforced_machine_gate":machine.summary(c),
            "product_default_on_changed":False,
            "historical_mixed_gain_review_signals":len(suspect_rescue),
            "historical_mixed_gain_examples":[{"source_task":x["id"],"title":x["title"][:95]}
                                             for x in suspect_rescue[:8]],
            "candidates":xs,"open_count":len(open_),
            "stage_counts":stages,
            "product_absorption_funnel":adoption,
            "assignment_coverage":assignment_report,
            "work_packages":bundles,
            "research_gain_signals_untriaged":len(unmapped),
            "research_gain_examples_untriaged":unmapped[:12],
            "held_p0_count":len(blocked),
            "next_product_actions":[{"candidate":x["id"],"stage":x["stage"]} for x in open_[:8]],
            "note":"Task DONE is evidence, not a release. ACTIVE is a claim, not a background worker. Same-RC M2/A1 evidence and explicit pilot decision are required."}

def queue_task(c,track,title,goal,source,priority):
    """One bounded ticket in the existing task board; preserve all ACTIVE owners."""
    if c.execute("SELECT 1 FROM tasks WHERE track=? AND title=? LIMIT 1",(track,title)).fetchone():
        return None
    # Keep a small bounded pipeline buffer. The old single-PENDING rule
    # starved product absorption behind unrelated tasks. Never steal ACTIVE.
    # Bounded independent-audit buffer must not starve 3 already integrated
    # default-OFF product RCs behind unrelated A1 tasks; active owners untouched.
    capacity={"M1":5,"M2":4,"A1":5}[track]
    existing=c.execute("SELECT count(*) FROM tasks WHERE track=? AND status='PENDING'",(track,)).fetchone()[0]
    if existing>=capacity:
        return None
    import re as _re
    ids=[int(m.group(1)) for (ident,) in c.execute("SELECT id FROM tasks WHERE id LIKE ?",(track+"-X%",))
         if (m:=_re.fullmatch(_re.escape(track)+r"-X(\d+)",ident))]
    tid=f"{track}-X{max(ids,default=0)+1:03d}"
    c.execute("""INSERT INTO tasks
     (id,role,track,priority,title,acceptance,inputs,status,updated_at)
     VALUES(?,?,?,?,?,?,?,'PENDING',?)""",
     (tid,ROLES[track],track,priority,title,goal,source,time.time()))
    return tid

def coalesce_pending_m1(c,primary_task,absorbed_task,reason):
    """Merge two *unclaimed* same-runtime M1 patches into one exact RC.

    The two source candidate IDs stay distinct; bundle admission later
    requires explicit per-member proof. Never change an ACTIVE owner.
    """
    if len(reason.strip())<20:
        raise ValueError("Specify shared runtime and independent validation")
    init(c)
    if primary_task==absorbed_task:
        raise ValueError("Cannot coalesce a task into itself")
    primary=c.execute("SELECT status,owner,acceptance FROM tasks WHERE id=? AND track='M1'",
                      (primary_task,)).fetchone()
    absorbed=c.execute("SELECT status,owner,acceptance FROM tasks WHERE id=? AND track='M1'",
                       (absorbed_task,)).fetchone()
    if not primary or not absorbed or primary[0]!="PENDING" or absorbed[0]!="PENDING" or primary[1] or absorbed[1]:
        raise ValueError("Only two unclaimed M1 PENDING tickets can be coalesced")
    c.execute("BEGIN IMMEDIATE")
    try:
        members=[r[0] for r in c.execute("SELECT id FROM product_candidates WHERE integration_task IN (?,?)",
                                        (primary_task,absorbed_task))]
        if len(members)<2:
            raise ValueError("Both tasks must represent distinct registered candidate members")
        marker=f"[COALESCED_M1:{absorbed_task}]"
        if marker not in primary[2]:
            c.execute("UPDATE tasks SET acceptance=acceptance||?,updated_at=? WHERE id=?",
                      (f"\n{marker} Combine sources for {', '.join(members)} on ONE "
                       f"reversible default-OFF RC. {reason.strip()} "
                       f"Original {absorbed_task} acceptance: {absorbed[2]} "
                       "Declare actual included members with "
                       "'BUNDLE_INTEGRATED_CANDIDATES: ...' and real "
                       "'NEW_RC_MANIFEST_SHA256=<sha64>' in result.md. "
                       "Each candidate still requires its own real-answer M2 "
                       "and source/safety A1 checks; do not claim a member that "
                       "was not actually enabled and tested.",
                       time.time(),primary_task))
        c.execute("""UPDATE tasks SET status='SUPERSEDED',owner=NULL,
                     blocked_reason=?,updated_at=? WHERE id=? AND status='PENDING'""",
                  (f"COALESCED_TO:{primary_task} {reason.strip()}",time.time(),absorbed_task))
        for cid in members:
            c.execute("""INSERT OR IGNORE INTO product_bundle_assignments
                      (candidate_id,bundle_task,bundle_family,created_at)
                      VALUES(?,?,?,?)""",(cid,primary_task,"memory-answer",time.time()))
        c.execute("""UPDATE product_candidates SET integration_task=NULL,
                     note=note||?,updated_at=?
                     WHERE id IN ({})""".format(",".join("?" for _ in members)),
                  (f" | Combined on M1 {primary_task} (pending per-member RC proof)",
                   time.time(),*members))
        for parent_id,why in c.execute(
             "SELECT parent_id,reason FROM product_successor_handoffs WHERE m1_task=?",
             (absorbed_task,)).fetchall():
            c.execute("""INSERT OR IGNORE INTO product_successor_handoffs
                    (parent_id,m1_task,reason,created_at) VALUES(?,?,?,?)""",
                    (parent_id,primary_task,why,time.time()))
        c.execute("DELETE FROM product_successor_handoffs WHERE m1_task=?",(absorbed_task,))
        c.commit()
    except Exception:
        c.rollback()
        raise
    return {"primary_task":primary_task,"superseded_task":absorbed_task,
            "bundle_members":members,"state":"PENDING_ONE_SHARED_RC"}


def link_successor(c,parent_id,m1_task,reason):
    """Reuse an already assigned M1 patch as the parent candidate's next RC.

    Existing ACTIVE owners and artifacts are untouched. This is a handoff,
    not a claim that the patch already works in the product.
    """
    init(c)
    if len(reason.strip())<15:
        raise ValueError("Describe the specific product failure and reuse route")
    parent=c.execute("SELECT id FROM product_candidates WHERE id=?",(parent_id,)).fetchone()
    m1=c.execute("SELECT track,status,acceptance FROM tasks WHERE id=?",(m1_task,)).fetchone()
    if not parent or not m1 or m1[0]!="M1" or m1[1] not in ("PENDING","ACTIVE","DONE"):
        raise ValueError("Requires existing candidate and real M1 task")
    c.execute("""INSERT OR IGNORE INTO product_successor_handoffs
       (parent_id,m1_task,reason,created_at) VALUES(?,?,?,?)""",
       (parent_id,m1_task,reason.strip(),time.time()))
    # A pending task may receive precise completion instructions safely.
    if m1[1]=="PENDING":
        marker=f"[PRODUCT_SUCCESSOR:{parent_id}]"
        if marker not in m1[2]:
            c.execute("""UPDATE tasks SET acceptance=acceptance||?,updated_at=?
                       WHERE id=? AND status='PENDING'""",
                      (f"\n{marker} Reuse the existing RC; {reason.strip()}. To "
                       "hand this patch to the SAME-RC M2/A1 fastlane, output "
                       "'- Outcome: PASS_GAIN' and the real "
                       "'NEW_RC_MANIFEST_SHA256=<64 hex>' and "
                       "'PRODUCT_SUCCESSORS_VERIFIED: <parent-id(s)>' in result.md. "
                       "Only list a parent that was actually enabled and "
                       "validated in the new RC. If product effect is uncertain, report the actual "
                       "limitation; do not claim PASS or reuse old P0 SHA.",
                       time.time(),m1_task))
    return {"parent":parent_id,"m1_task":m1_task,"status":m1[1]}


def successor_status(c,parent_id):
    return [{"task":r[0],"status":r[1],"reason":r[2]} for r in c.execute(
        """SELECT s.m1_task,t.status,s.reason FROM product_successor_handoffs s
           JOIN tasks t ON t.id=s.m1_task WHERE s.parent_id=?
           ORDER BY s.created_at""",(parent_id,))]


def adopt_finished_successors(c):
    """One positive NEW RC per source task, no second M1 merge or audit overwrite."""
    created=[]
    for parent_id,m1_task in c.execute(
        "SELECT parent_id,m1_task FROM product_successor_handoffs ORDER BY created_at"):
        parent=c.execute("SELECT priority,risk FROM product_candidates WHERE id=?",
                         (parent_id,)).fetchone()
        job=c.execute("SELECT status,artifact FROM tasks WHERE id=?",(m1_task,)).fetchone()
        if not parent or not job or job[0]!="DONE" or not job[1] or not Path(job[1]).is_file():
            continue
        child_id="successor-"+parent_id+"-"+m1_task.lower()
        if c.execute("SELECT 1 FROM product_candidates WHERE id=?",(child_id,)).fetchone():
            continue
        result=Path(job[1]).read_text("utf-8",errors="replace")[:9500]
        outcome=re.search(r"(?im)^\s*(?:-\s*)?(?:Outcome|Verdict):\s*(.+)$",result)
        manifest=re.search(r"(?im)\bNEW_RC_MANIFEST_SHA256\s*[:=]\s*([a-f0-9]{64})\b",result)
        verified=re.search(r"(?im)^\s*(?:-\s*)?PRODUCT_SUCCESSORS_VERIFIED\s*:\s*(.+)$",result)
        actual={x.strip() for x in verified.group(1).split(",")} if verified else set()
        if (not outcome or not re.match(r"PASS(?:_|\b)",outcome.group(1),re.I)
            or research_mixed_review(outcome.group(1)) or not manifest
            or parent_id not in actual):
            continue
        evidence_sha=source_evidence(c,m1_task)
        if not evidence_sha:continue
        now=time.time()
        c.execute("""INSERT INTO product_candidates
             (id,source_task,source_sha,value,priority,integration_task,risk,note,created_at,updated_at)
             VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (child_id,m1_task,evidence_sha,
             f"Existing M1 patch {m1_task} extends {parent_id} in RC {manifest.group(1)}",
             int(parent[0]),m1_task,parent[1],
             f"New RC from linked existing task. Original parent {parent_id} retains its prior answer and A1 verdict.",
             now,now))
        c.execute("""INSERT OR IGNORE INTO product_candidate_support
                 (candidate_id,source_task,source_sha,reason,created_at)
                 SELECT ?,source_task,source_sha,reason,?
                 FROM product_candidate_support WHERE candidate_id=?""",
                 (child_id,now,parent_id))
        created.append({"parent":parent_id,"candidate":child_id,
                        "m1_task":m1_task,"sha":manifest.group(1)})
    return created


def adopt_finished_repairs(c):
    """After a genuine NEW M1 RC is frozen, hand it to M2 automatically.

    The failed parent keeps its old A1/M2 verdict. Only a new independently
    scored child RC can eventually reach A1, never an audit overwrite.
    """
    created=[]
    for item in c.execute("""SELECT id,title,artifact FROM tasks WHERE track='M1'
           AND status='DONE' AND (title LIKE 'PRODUCT REPAIR: %'
                            OR title LIKE 'PRODUCT VALUE REPAIR: %')"""):
        task_id,title,artifact=item
        parent_id=title.split(": ",1)[-1].strip()
        parent=c.execute("SELECT priority,risk FROM product_candidates WHERE id=?",
                         (parent_id,)).fetchone()
        new_id="repaired-"+task_id.lower()
        if not parent or c.execute("SELECT 1 FROM product_candidates WHERE id=?",(new_id,)).fetchone():
            continue
        p=Path(artifact) if artifact else None
        if not p or not p.is_file():continue
        body=p.read_text("utf-8",errors="replace")[:8000]
        approved=re.search(r"(?im)^\s*(?:-\s*)?(?:Outcome|Verdict):\s*(?:PASS_GAIN|PASS_REPAIRED_RC|PRODUCT_RC)\b",body)
        manifest=re.search(r"(?im)\bNEW_RC_MANIFEST_SHA256\s*[:=]\s*([a-f0-9]{64})\b",body)
        if not approved or not manifest:continue
        sha=source_evidence(c,task_id)
        if not sha:continue
        now=time.time()
        c.execute("""INSERT INTO product_candidates
          (id,source_task,source_sha,value,priority,integration_task,risk,note,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (new_id,task_id,sha,f"Repaired {parent_id} in new frozen RC {manifest.group(1)}",
           int(parent[0]),task_id,parent[1],
           f"Replaces only failed parent {parent_id}; requires new same-RC M2 and independent A1",
           now,now))
        # Preserve linked research evidence in the replacement candidate;
        # linking is not proof that M1 actually used the component.
        c.execute("""INSERT OR IGNORE INTO product_candidate_support
              (candidate_id,source_task,source_sha,reason,created_at)
              SELECT ?,source_task,source_sha,reason,?
              FROM product_candidate_support WHERE candidate_id=?""",
              (new_id,now,parent_id))
        created.append({"candidate":new_id,"source":task_id,"parent":parent_id,
                        "track":"M2","state":"READY_M2_SAME_RC"})
    return created


def backfill_recent_gain(c,limit=2,scan=3000):
    """Catch DONE research using the legacy direct SQLite writer.

    Keep the intake bounded: mixed negative/positive verdicts go to
    REVIEW_VALUE, never straight to integration. No provider or A1 access.
    """
    init(c)
    already={r[0] for r in c.execute("SELECT source_task FROM product_candidates")}
    recently=list(c.execute("""SELECT id,track,title,artifact FROM tasks
        WHERE status='DONE' AND track IN ('D1','D2','D3','D4','D5','D6','M2','M3')
        ORDER BY updated_at DESC,id DESC LIMIT ?""",(scan,)))
    intake=[]
    for task_id,track,title,artifact in recently:
        if len(intake)>=limit:break
        if task_id in already or not artifact:continue
        # Product consumers validate existing candidates and must not become
        # new research mechanisms just for completing an evaluation.
        if track=="M2" and re.search(r"(?i)\b(?:PRODUCT ANSWER|ANSWER CHECK|PRODUCT AUDIT)\b",title):
            continue
        file=Path(artifact)
        if not file.is_file():continue
        content=file.read_text("utf-8",errors="replace")[:3600]
        match=re.search(r"(?im)^\s*(?:[-*]\s*)?(?:Outcome|Verdict|Decision)\s*:\s*(.+)$",content)
        if not match:continue
        headline=match.group(1)[:700]
        if not measured_research_value(headline):continue
        # STOP/REJECT + partial gain is a historical rescue signal, not a
        # new default trial. It remains available in the independent reject
        # index and can be explicitly registered/link-supported after review.
        # Otherwise legacy backfill would flood M1 with superseded ablations.
        if research_mixed_review(headline):continue
        risk=scoped_risk_hint(title)
        result=register_task(c,task_id,headline,priority=45,risk=risk)
        if result["status"] in ("REGISTERED_OR_ALREADY_PRESENT","ALREADY_REGISTERED_SOURCE"):
            intake.append({"source_task":task_id,"candidate":result["candidate"],
                           "triage_risk":risk,"result":"REVIEW_VALUE" if risk=="unknown" else "SCOPED_TRIAL"})
            already.add(task_id)
    return intake


def incremental_research_intake(c,limit=2,scan=3000):
    """Only newly DONE research is auto-ingested; history stays in rescue index.

    An initial cursor starts at the current last DONE result, not years of
    prior ablations. Do not lose rows when more than 'limit' finish together.
    """
    init(c)
    checkpoint=c.execute("SELECT last_updated,last_id FROM product_research_intake_checkpoint WHERE name='done'").fetchone()
    if checkpoint is None:
        last=c.execute("""SELECT updated_at,id FROM tasks
                 WHERE status='DONE' AND track IN ('D1','D2','D3','D4','D5','D6','M2','M3')
                 ORDER BY updated_at DESC,id DESC LIMIT 1""").fetchone()
        c.execute("""INSERT INTO product_research_intake_checkpoint(name,last_updated,last_id)
             VALUES('done',?,?)""",
             (last[0] if last else 0,last[1] if last else ""))
        return []
    pos,ident=checkpoint
    rows=list(c.execute("""SELECT id,track,title,artifact,updated_at FROM tasks
              WHERE status='DONE' AND track IN ('D1','D2','D3','D4','D5','D6','M2','M3')
              AND (updated_at>? OR (updated_at=? AND id>?))
              ORDER BY updated_at ASC,id ASC LIMIT ?""",(pos,pos,ident,scan)))
    already={r[0] for r in c.execute("SELECT source_task FROM product_candidates")}
    intake=[]
    for tid,track,title,artifact,updated in rows:
        pos,ident=updated,tid
        if tid not in already and artifact and Path(artifact).is_file():
            # M2 evaluating a product candidate is not a new research source.
            if not (track=="M2" and re.search(r"(?i)\b(?:PRODUCT ANSWER|ANSWER CHECK|PRODUCT AUDIT)\b",title)):
                body=Path(artifact).read_text("utf-8",errors="replace")[:3600]
                result=re.search(r"(?im)^\s*(?:[-*]\s*)?(?:Outcome|Verdict|Decision)\s*:\s*(.+)$",body)
                headline=result.group(1)[:700] if result else ""
                if measured_research_value(headline) and not research_mixed_review(headline):
                    risk=scoped_risk_hint(title)
                    r=register_task(c,tid,headline,priority=45,risk=risk)
                    if r["status"]=="REGISTERED_OR_ALREADY_PRESENT":
                        intake.append({"candidate":r["candidate"],"source_task":tid,"triage_risk":risk})
                        already.add(tid)
        if len(intake)>=limit:break
    if rows:
        c.execute("""UPDATE product_research_intake_checkpoint
             SET last_updated=?,last_id=? WHERE name='done'""",(pos,ident))
    return intake


def sync(c, *, enqueue=True):
    seed(c)
    created=[]
    c.execute("BEGIN IMMEDIATE")
    try:
        discovered=[]
        bundled_promotions=[]
        successor_promotions=[]
        history_rescue=machine.rescue(c,limit_new=4) if enqueue else {}
        if enqueue:
            created.extend(adopt_finished_repairs(c))
            successor_promotions=adopt_finished_successors(c)
            bundled_promotions=adopt_finished_bundles(c)
            discovered=incremental_research_intake(c)
        cursor=c.execute("SELECT * FROM product_candidates ORDER BY priority,id")
        fields=[col[0] for col in cursor.description]
        candidates=[dict(zip(fields,raw)) for raw in cursor]
        # Exact scoped read/cost wins need not wait forever for a manual risk
        # label. Other unknowns remain review-only; no default-ON action here.
        for x in candidates:
            if x["risk"]!="unknown" or "LEGACY_MIXED_VERDICT_REVIEW_ONLY" in x["note"]:continue
            task_row=c.execute("SELECT title FROM tasks WHERE id=?",(x["source_task"],)).fetchone()
            inferred=scoped_risk_hint(task_row[0] if task_row else "")
            if inferred=="unknown":continue
            c.execute("""UPDATE product_candidates SET risk=?,note=note||?,updated_at=?
                WHERE id=? AND risk='unknown'""",
                (inferred," | inferred scoped trial only; M1 must validate actual read/write surface",
                 time.time(),x["id"]))
            x["risk"]=inferred
        # M1 work is grouped by shared runtime family. Preserve old direct
        # handoffs for a true singleton and already-ticketed candidates.
        member_counts={}
        covered={r[0] for r in c.execute("SELECT candidate_id FROM product_bundle_assignments")}
        for x in candidates:
            if x["id"] in covered or x["integration_task"]:continue
            f=bundle_family(c,x)
            if f:member_counts[f]=member_counts.get(f,0)+1
        for x in candidates:
            state=stage(c,x)
            if not enqueue:continue
            # A1 can review the same immutable enabled M1 RC in parallel with
            # M2's real final-answer check. Neither lane depends on the
            # other's outcome, and neither is a release approval.
            m1_ready=task(c,x["integration_task"])
            if (not x["audit_task"] and x["risk"]!="unknown"
                and state not in ("NEED_M1_REAL_RUNTIME_NOT_SHADOW",)
                and not state.startswith(("HOLD_P0","BLOCKED_","SOURCE_SHA_CHANGED"))
                and m1_ready and m1_ready["status"]=="DONE"
                and m1_ready["artifact"] and Path(m1_ready["artifact"]).is_file()):
                tid=queue_task(c,"A1",f"PRODUCT AUDIT: {x['id']}",
                    f"Independently audit actual enabled-path of the ONE frozen M1 RC "
                    f"{x['integration_task']} for {x['id']} with exact manifest SHA, "
                    "principal/source/admissibility/NO_SAVE/delete/restart/rollback "
                    "where in scope. M2 final answers may run in parallel, but "
                    "do not rely on M2 Gold/results or turn this into default ON. "
                    "Distinguish durable material P0 from ordinary capability loss.",
                    f"Parallel audit of M1 {x['integration_task']}",max(1,int(x["priority"])+5))
                if tid:
                    c.execute("UPDATE product_candidates SET audit_task=?,updated_at=? WHERE id=?",
                              (tid,time.time(),x["id"]))
                    x["audit_task"]=tid
                    created.append({"candidate":x["id"],"task":tid,"track":"A1",
                                    "parallel_with_M2":True})
            if state.startswith("HOLD_P0") and x["decision"]!="HOLD_P0" and x["audit_task"] and x["integration_task"]:
                # Never relabel a rejected SHA as safe: create a separate M1
                # repair job, yielding a NEW frozen candidate, not overwriting A1.
                title=f"PRODUCT REPAIR: {x['id']}"
                goal=(f"A1 task {x['audit_task']} found real enabled-path P0 in product "
                      f"M1 task {x['integration_task']}. Preserve old NONPASS and positive "
                      "answer gain; repair source lifecycle/NO_SAVE/revocation, canonical "
                      "source_id-content hash, principal/scope and rollback on one NEW "
                      "default-OFF RC SHA. Do not reuse protected A1 input, do not "
                      "re-enable the old implementation; register repaired M1 DONE artifact "
                      "as a NEW product candidate for same-SHA M2/A1 follow-up." +
                      support_handoff(c,x["id"]))
                tid=queue_task(c,"M1",title,goal,f"Audit repair from {x['audit_task']}",max(1,int(x["priority"])+5))
                if tid:created.append({"candidate":x["id"],"repair_task":tid,"track":"M1","old_a1_nonpass_retained":True})
                continue
            if state.startswith("REPAIR_M1_"):
                # An already-running M1 patch in this family must not cause
                # a second full integration ticket. Wait for its frozen RC.
                if c.execute("""SELECT 1 FROM product_successor_handoffs s
                     JOIN tasks t ON t.id=s.m1_task
                     WHERE s.parent_id=? AND t.status IN ('PENDING','ACTIVE','DONE')
                     LIMIT 1""",(x["id"],)).fetchone():
                    continue
                # Preserve the measured component gain and original M2/A1
                # verdict. A new exact product SHA must prove real behavior.
                title=f"PRODUCT VALUE REPAIR: {x['id']}"
                goal=(f"Source {x['source_task']} was useful, but actual product M2 "
                      f"{x['answer_task']} or A1 {x['audit_task']} reported a non-P0 "
                      "coverage/trigger/answer limitation. Reuse the existing single "
                      "runtime; fix only the concrete evidence-selected retrieval, "
                      "activation, or cost defect. Verify real autonomous product "
                      "answers, no material source/identity P0, rollback and fresh "
                      "non-leaked source-disjoint public controls. Freeze a NEW RC "
                      "manifest SHA and register it as a NEW candidate; never "
                      "overwrite old M2/A1 verdicts. No new paid API without scope." +
                      support_handoff(c,x["id"]))
                tid=queue_task(c,"M1",title,goal,f"Product non-P0 repair: {x['id']}",
                               max(1,int(x["priority"])+5))
                if tid:created.append({"candidate":x["id"],"repair_task":tid,
                                       "track":"M1","old_m2_a1_evidence_retained":True})
                continue
            if state=="NEED_M1_REAL_RUNTIME_NOT_SHADOW":
                # A DONE shadow contract is not a runnable answer product.
                # Do not rewrite or un-block the M2 evidence; build a NEW RC.
                title=f"PRODUCT RUNTIME: {x['id']}"
                goal=(f"Existing M1 {x['integration_task']} was shadow-only; M2 {x['answer_task']} "
                      "correctly blocked same-RC final-answer test. Compose an actual runnable "
                      "default-OFF memory/state/search/answer RC using existing integration, "
                      "freeze a new SHA, prove cold restart and rollback. No new provider spend. "
                      "After DONE trigger new M2 answer and A1 review, preserving old M2 blocker.")
                tid=queue_task(c,"M1",title,goal,
                               f"Blocked shadow M2: {x['answer_task']}",max(1,int(x["priority"])+5))
                if tid:
                    c.execute("""UPDATE product_candidates SET integration_task=?,answer_task=NULL,
                       audit_task=NULL,note=note||?,updated_at=? WHERE id=?""",
                      (tid,f" | Original blocked M2={x['answer_task']}; shadow-only not runnable",time.time(),x["id"]))
                    created.append({"candidate":x["id"],"task":tid,"track":"M1",
                                    "old_shadow_block_preserved":True})
                continue
            if state=="WAIT_MACHINE_PORTFOLIO_RECEIPT":
                tid=queue_task(c,"M2",f"PRODUCT PORTFOLIO RECEIPT: {x['id']}",
                  f"Run product_benefit_gate.py for {x['id']}. Freeze exact M1 RC, "
                  "and attach FRESH/DISJOINT same-input paired REAL final-answer results. "
                  "Record every ordinary loss with candidate_failure_stage="
                  "retrieval_miss/evidence_incomplete/reasoning_error/output_incomplete/"
                  "source_conflict. Retrieval/state/cost proxy gains cannot substitute "
                  "for net_final_correct > 0. Targeted pilot needs >=12 fresh pairs; "
                  "broad pilot >=24; overall capability claims require >=100 broad pairs "
                  "plus independent/deterministic judging. Include route activation, "
                  "cost/latency, P0 lifecycle and exact same-SHA A1 evidence. Use attach-e2e.",
                  f"Machine product gate: {x['id']}",max(1,int(x["priority"])+5))
                if tid:created.append({"candidate":x["id"],"task":tid,"track":"M2",
                                      "kind":"portfolio_receipt"})
                continue
            if state.startswith(("HOLD_","BLOCKED_","REVIEW_VALUE")):
                continue
            track=None
            if state=="READY_M1_TRIAL":track="M1"
            elif state=="READY_M2_SAME_RC":track="M2"
            elif state=="READY_A1_SAME_RC":track="A1"
            if track is None:continue
            if (track=="M1" and
                (x["id"] in covered or member_counts.get(bundle_family(c,x),0)>=2)):
                # enqueue_bundles below dispatches ONE task for several
                # compatible candidates; none inherits M1 DONE automatically.
                continue
            # A research positive only triggers a reversible experiment, not default release.
            prefix={"M1":"PRODUCT TRIAL","M2":"PRODUCT ANSWER","A1":"PRODUCT AUDIT"}[track]
            title=f"{prefix}: {x['id']}"
            if track=="M1":
                reuse=c.execute("""SELECT s.candidate_id,p.integration_task
                      FROM product_candidate_support s
                      JOIN product_candidates p ON p.id=s.candidate_id
                      WHERE s.source_task=? AND s.candidate_id<>?
                      ORDER BY p.priority,s.candidate_id LIMIT 1""",
                      (x["source_task"],x["id"])).fetchone()
                reuse_note=(f" This source already supports product family {reuse[0]} "
                    f"(prior M1={reuse[1]}): patch/extend that single runnable RC instead "
                    "of building an independent memory/search platform; freeze a NEW SHA "
                    "and compare product answers, cost and state." if reuse else "")
                intent_note=(" For this LLM intent route, reuse X078 answer+proposal, "
                    "M3-X134 source-bound provenance and deterministic lifecycle state; "
                    "do not replace real authorization with prompt text."
                    if x["id"]=="llm-intent-x134" else "")
                goal=(f"Consume DONE source {x['source_task']} exact evidence SHA {source_evidence(c,x['source_task'])}. "
                    "Reuse existing implementation, produce ONE default-OFF runnable RC "
                    "with startup, cold restart and rollback. M1 is sole merger; preserve "
                    "authenticated owner preferences and correction."+
                    reuse_note+intent_note+
                    " Document changed paths, new manifest SHA, local source-disjoint "
                    "checks and true enabled-path effect. Never claim a research-only gain "
                    "as an integrated final-answer improvement."+
                    support_handoff(c,x["id"]))
                field="integration_task"
            elif track=="M2":
                goal=(f"Consume product candidate {x['id']} from M1 task {x['integration_task']}; "
                 "verify SAME exact RC SHA, public raw-to-final answers, gain/loss, legal state, "
                 "tokens, incremental actual/proxy CNY and latency. Reuse exact caches and smallest "
                 "material panel. Do not confuse retrieval coverage with final-answer score, "
                 "and do not make unauthorized new paid requests."+
                 support_handoff(c,x["id"]))
                field="answer_task"
            else:
                goal=(f"Independently inspect ONLY candidate {x['id']} and M1 task {x['integration_task']} "
                 "same exact frozen RC SHA. Audit enabled paths for owner/principal, third-party, "
                 "durable NO_SAVE, natural delete/retract, correction, cold restart and rollback "
                 "where in scope. Report genuine durable P0 versus ordinary answer loss separately. "
                 "Do not expose sealed gold or block unrelated default-OFF trial."+
                 support_handoff(c,x["id"]))
                field="audit_task"
            tid=queue_task(c,track,title,goal,f"Promotion source: {x['source_task']}",max(1,int(x["priority"])+5))
            if tid:
                c.execute(f"UPDATE product_candidates SET {field}=?,updated_at=? WHERE id=?",
                          (tid,time.time(),x["id"]))
                created.append({"candidate":x["id"],"task":tid,"track":track})
        if enqueue:
            created.extend(enqueue_bundles(c,candidates))
        c.commit()
    except Exception:
        c.rollback()
        raise
    report=snapshot(c)
    report["new_task_tickets"]=created
    report["new_research_intake"]=discovered
    report["verified_bundle_promotions"]=bundled_promotions
    report["verified_successor_promotions"]=successor_promotions
    report["historical_rescue_this_sync"]=history_rescue
    return report

def decide(c,candidate,decision,note):
    if decision not in ("TRIAL_OFF","PILOT_REVIEW","HOLD_P0","HOLD_VALUE"):
        raise ValueError("No automatic public release is supported")
    if len(note.strip())<12:raise ValueError("Provide source-based reason")
    init(c)
    cursor=c.execute("SELECT * FROM product_candidates WHERE id=?",(candidate,))
    raw=cursor.fetchone()
    if raw is None:raise ValueError("Unknown candidate")
    row=dict(zip([col[0] for col in cursor.description],raw))
    if decision=="PILOT_REVIEW":
        state=stage(c,row)
        if state!="MACHINE_PARETO_PILOT_REVIEW_READY":
            raise ValueError("Pilot review blocked until real product final-answer Pareto benefit and same-SHA M1/M2/A1 proof: "+state)
    if decision=="TRIAL_OFF":
        state=stage(c,row)
        m1=task(c,row["integration_task"])
        if state.startswith(("HOLD_P0","BLOCKED_","WAIT_SOURCE","SOURCE_SHA_CHANGED","NEED_M1_REAL_RUNTIME")) or (
             not m1 or m1["status"]!="DONE" or not m1["artifact"] or not Path(m1["artifact"]).is_file()):
            raise ValueError("Only a real M1 frozen RC (without known material P0) can have a default-OFF trial disposition")
    c.execute("UPDATE product_candidates SET decision=?,decision_note=?,updated_at=? WHERE id=?",
              (decision,note,time.time(),candidate))
    receipt=machine.current(c,candidate)
    return {"candidate":candidate,"decision":decision,"note":note,
            "machine_gate":receipt.get("verdict") if receipt else "NO_RECEIPT",
            "default_on_changed":False,"qq_send_changed":False,
            "automatic_release":False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="action",required=True)
    sub.add_parser("sync");sub.add_parser("status")
    hh=sub.add_parser("rescue-historical")
    hh.add_argument("--limit-new",type=int,default=24)
    aa=sub.add_parser("attach-e2e")
    aa.add_argument("--candidate",required=True)
    aa.add_argument("--receipt",required=True)
    rr=sub.add_parser("register")
    rr.add_argument("--source",required=True)
    rr.add_argument("--value",required=True)
    rr.add_argument("--risk",default="unknown",choices=["unknown","read_only","durable_write","answer","cost"])
    rr.add_argument("--priority",type=int,default=40)
    ll=sub.add_parser("link-support")
    ll.add_argument("--candidate",required=True)
    ll.add_argument("--source",required=True)
    ll.add_argument("--reason",required=True)
    ss=sub.add_parser("link-successor")
    ss.add_argument("--candidate",required=True)
    ss.add_argument("--m1-task",required=True)
    ss.add_argument("--reason",required=True)
    dd=sub.add_parser("decide")
    dd.add_argument("--candidate",required=True)
    dd.add_argument("--decision",required=True,choices=["TRIAL_OFF","PILOT_REVIEW","HOLD_P0","HOLD_VALUE"])
    dd.add_argument("--reason",required=True)
    args=p.parse_args()
    with connect() as c:
        seed(c)
        if args.action=="sync":result=sync(c)
        elif args.action=="status":result=snapshot(c)
        elif args.action=="rescue-historical":
            c.execute("BEGIN IMMEDIATE")
            try:
                result=machine.rescue(c,limit_new=max(0,min(args.limit_new,64)))
                c.commit()
            except Exception:
                c.rollback()
                raise
        elif args.action=="attach-e2e":result=machine.record(
            c,args.candidate,args.receipt)
        elif args.action=="register":
            result=register_task(c,args.source,args.value,args.priority,args.risk)
        elif args.action=="link-support":
            result=link_support(c,args.candidate,args.source,args.reason)
        elif args.action=="link-successor":
            result=link_successor(c,args.candidate,args.m1_task,args.reason)
        else:result=decide(c,args.candidate,args.decision,args.reason)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
