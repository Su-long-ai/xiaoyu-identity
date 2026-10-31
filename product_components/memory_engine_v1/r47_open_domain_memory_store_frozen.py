#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R47 research candidate: source-bound open-domain claim/update store.

No finite slot vocabulary. Semantic extraction/target discovery is outside this
module: caller passes validated atomic claim candidates and explicit target IDs.
This layer owns stable source identity, authority, update/conflict relations,
provenance, lifecycle propagation, SQLite persistence and FTS5 retrieval.
"""
from __future__ import annotations
import hashlib,json,re,sqlite3
from pathlib import Path

def sha_obj(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def sha_text(x):
    return hashlib.sha256(str(x).encode()).hexdigest()
def source_message_id(conversation_id,message_id):
    return sha_obj({"conversation_id":str(conversation_id),"message_id":str(message_id)})
def jdump(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def jload(x):return json.loads(x)

SCHEMA="""
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS source_messages(
  source_message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  message_seq INTEGER NOT NULL,
  source_role TEXT NOT NULL,
  source_text TEXT NOT NULL,
  source_text_hash TEXT NOT NULL,
  effective_at INTEGER NOT NULL,
  projection_hash TEXT NOT NULL,
  lifecycle TEXT NOT NULL DEFAULT 'active',
  UNIQUE(conversation_id,message_id)
);
CREATE TABLE IF NOT EXISTS claims(
  claim_id TEXT PRIMARY KEY,
  source_message_id TEXT REFERENCES source_messages(source_message_id),
  derivation_key TEXT,
  ordinal INTEGER NOT NULL,
  claim_text TEXT NOT NULL,
  claim_text_hash TEXT NOT NULL,
  evidence_quote TEXT,
  source_anchor INTEGER,
  source_role TEXT NOT NULL,
  authority_base TEXT NOT NULL,
  relation_kind TEXT NOT NULL,
  effective_at INTEGER NOT NULL,
  status TEXT NOT NULL,
  created_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_relations(
  child_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
  parent_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
  relation TEXT NOT NULL,
  PRIMARY KEY(child_claim_id,parent_claim_id,relation)
);
CREATE TABLE IF NOT EXISTS source_conflicts(
  source_message_id TEXT NOT NULL,
  conflict_kind TEXT NOT NULL,
  observed_hash TEXT NOT NULL,
  PRIMARY KEY(source_message_id,conflict_kind,observed_hash)
);
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
  claim_id UNINDEXED,
  claim_text,
  tokenize='unicode61'
);
CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source_message_id);
CREATE INDEX IF NOT EXISTS idx_claims_status_role ON claims(status,source_role,effective_at);
CREATE INDEX IF NOT EXISTS idx_rel_parent ON claim_relations(parent_claim_id,relation);
"""

class OpenDomainMemoryStore:
    def __init__(self,path):
        self.path=Path(path)
        self.db=sqlite3.connect(self.path)
        self.db.row_factory=sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):self.db.close()

    @staticmethod
    def _unique_anchor(text,quote):
        if not isinstance(quote,str) or not quote:raise ValueError("bad_evidence_quote")
        starts=[];p=text.find(quote)
        while p>=0:
            starts.append(p);p=text.find(quote,p+1)
        if len(starts)!=1:raise ValueError("evidence_quote_not_unique_exact_span")
        return starts[0]

    def _canonical_candidates(self,text,candidates):
        if not isinstance(candidates,list):raise ValueError("claims_not_list")
        out=[]
        for c in candidates:
            if not isinstance(c,dict):raise ValueError("claim_not_object")
            ct=c.get("claim_text");q=c.get("evidence_quote");rel=str(c.get("relation") or "NEW").upper()
            targets=c.get("targets") or []
            if not isinstance(ct,str) or not ct.strip():raise ValueError("bad_claim_text")
            if rel not in ("NEW","SUPERSEDE","CONFLICT","RETRACT"):raise ValueError("bad_relation")
            if not isinstance(targets,list) or any(not isinstance(x,str) or not x for x in targets):
                raise ValueError("bad_targets")
            if rel=="NEW" and targets:raise ValueError("new_has_targets")
            if rel!="NEW" and not targets:raise ValueError("relation_requires_target")
            anchor=self._unique_anchor(text,q)
            out.append({"claim_text":ct.strip(),"evidence_quote":q,"source_anchor":anchor,
                        "relation":rel,"targets":sorted(set(targets))})
        # Projection-set identity is order-independent; stable ordinal follows canonical source anchor.
        out.sort(key=lambda x:(x["source_anchor"],x["relation"],x["claim_text"],x["targets"]))
        return out

    def _claim(self,cid):
        r=self.db.execute("SELECT * FROM claims WHERE claim_id=?",(cid,)).fetchone()
        return dict(r) if r else None

    def _source(self,sid):
        r=self.db.execute("SELECT * FROM source_messages WHERE source_message_id=?",(sid,)).fetchone()
        return dict(r) if r else None

    def _next_order(self):
        return int(self.db.execute("SELECT COALESCE(MAX(created_order),0)+1 FROM claims").fetchone()[0])

    def _quarantine_claim_and_descendants(self,claim_ids):
        todo=list(claim_ids);seen=set()
        while todo:
            cid=todo.pop()
            if cid in seen:continue
            seen.add(cid)
            self.db.execute("UPDATE claims SET status='quarantined' WHERE claim_id=?",(cid,))
            children=[r[0] for r in self.db.execute(
              "SELECT child_claim_id FROM claim_relations WHERE parent_claim_id=? AND relation='DERIVED_FROM'",(cid,))]
            todo.extend(children)
        return seen

    def _quarantine_descendants(self,parent_claim_ids):
        """Quarantine derived descendants without rewriting parent lifecycle."""
        todo=[]
        for pid in parent_claim_ids:
            todo.extend(r[0] for r in self.db.execute(
              "SELECT child_claim_id FROM claim_relations WHERE parent_claim_id=? AND relation='DERIVED_FROM'",(pid,)))
        return self._quarantine_claim_and_descendants(todo)

    def _quarantine_source(self,sid,kind,observed_hash):
        self.db.execute("UPDATE source_messages SET lifecycle='quarantined' WHERE source_message_id=?",(sid,))
        self.db.execute("INSERT OR IGNORE INTO source_conflicts VALUES(?,?,?)",(sid,kind,observed_hash))
        claims=[r[0] for r in self.db.execute("SELECT claim_id FROM claims WHERE source_message_id=?",(sid,))]
        self._quarantine_claim_and_descendants(claims)

    def _validate_targets(self,role,relation,targets,effective_at):
        rows=[]
        for cid in targets:
            r=self._claim(cid)
            if r is None:raise ValueError("target_missing")
            if r["status"]!="active":raise ValueError("target_not_active")
            if r["source_role"]!=role:raise ValueError("cross_role_authority_relation")
            if int(r["effective_at"])>int(effective_at):raise ValueError("backdated_relation")
            rows.append(r)
        if relation in ("SUPERSEDE","RETRACT","CONFLICT") and not rows:
            raise ValueError("relation_requires_active_target")
        return rows

    def _active_conflict_component(self,claim_id):
        """Return the active same-role CONFLICTS component containing claim_id."""
        root=self._claim(claim_id)
        if root is None or root["status"]!="active":
            return {claim_id}
        role=root["source_role"]
        seen=set();todo=[claim_id]
        while todo:
            cur=todo.pop()
            if cur in seen:continue
            row=self._claim(cur)
            if row is None or row["status"]!="active" or row["source_role"]!=role:
                continue
            seen.add(cur)
            links=self.db.execute(
                """SELECT child_claim_id,parent_claim_id FROM claim_relations
                   WHERE relation='CONFLICTS'
                     AND (child_claim_id=? OR parent_claim_id=?)""",
                (cur,cur)).fetchall()
            for edge in links:
                other=(edge["parent_claim_id"]
                       if edge["child_claim_id"]==cur else edge["child_claim_id"])
                if other not in seen:
                    o=self._claim(other)
                    if o and o["status"]=="active" and o["source_role"]==role:
                        todo.append(other)
        return seen or {claim_id}

    def _validate_batch_relations(self,canonical):
        """Fail closed on ambiguous destructive transitions before any mutation.

        One active target may be consumed by at most one SUPERSEDE/RETRACT
        candidate in a source batch. An unresolved active conflict component is
        a resolution unit: destructive relations touching one endpoint must
        include every active endpoint in that component.
        """
        owner={}
        destructive=("SUPERSEDE","RETRACT")
        for idx,c in enumerate(canonical):
            if c["relation"] not in destructive:
                continue
            for target in c["targets"]:
                if target in owner:
                    raise ValueError("overlapping_target_mutation")
                owner[target]=idx

        for c in canonical:
            if c["relation"] not in destructive:
                continue
            targets=set(c["targets"])
            required=set()
            for target in targets:
                required.update(self._active_conflict_component(target))
            if not required.issubset(targets):
                raise ValueError("partial_conflict_resolution")

    def ingest(self,conversation_id,message_id,message_seq,role,text,effective_at,candidates):
        role=str(role)
        if role not in ("user","assistant"):raise ValueError("bad_source_role")
        if not isinstance(text,str) or not text:raise ValueError("bad_source_text")
        sid=source_message_id(conversation_id,message_id)
        seq=int(message_seq);t=int(effective_at)
        canonical=self._canonical_candidates(text,candidates)
        projection_hash=sha_obj(canonical)
        text_hash=sha_text(text)
        old=self._source(sid)

        # R19-compatible source identity: source ID ignores semantic payload.
        if old is not None:
            same_meta=(old["conversation_id"]==str(conversation_id) and
                       old["message_id"]==str(message_id) and int(old["message_seq"])==seq and
                       old["source_role"]==role and old["source_text_hash"]==text_hash and
                       int(old["effective_at"])==t)
            if old["lifecycle"]=="quarantined":
                return {"status":"source_quarantined","source_message_id":sid,"claim_ids":[]}
            if not same_meta:
                with self.db:
                    self._quarantine_source(sid,"source_metadata_conflict",sha_obj(
                      {"seq":seq,"role":role,"text_hash":text_hash,"effective_at":t}))
                return {"status":"source_metadata_conflict","source_message_id":sid,"claim_ids":[]}
            if old["projection_hash"]!=projection_hash:
                with self.db:
                    self._quarantine_source(sid,"source_projection_conflict",projection_hash)
                return {"status":"source_projection_conflict","source_message_id":sid,"claim_ids":[]}
            ids=[r[0] for r in self.db.execute(
              "SELECT claim_id FROM claims WHERE source_message_id=? ORDER BY ordinal",(sid,))]
            return {"status":"duplicate","source_message_id":sid,"claim_ids":ids}

        # Validate every target before mutating anything.
        target_rows={}
        for c in canonical:
            target_rows[id(c)]=self._validate_targets(role,c["relation"],c["targets"],t)
        self._validate_batch_relations(canonical)

        claim_ids=[sha_obj({"source_message_id":sid,"ordinal":i}) for i in range(len(canonical))]
        order=self._next_order()
        with self.db:
            self.db.execute("""INSERT INTO source_messages
              (source_message_id,conversation_id,message_id,message_seq,source_role,source_text,
               source_text_hash,effective_at,projection_hash,lifecycle)
              VALUES(?,?,?,?,?,?,?,?,?,'active')""",
              (sid,str(conversation_id),str(message_id),seq,role,text,text_hash,t,projection_hash))

            # Apply relation effects before inserting new claim rows, preserving source/history.
            for c in canonical:
                if c["relation"]=="SUPERSEDE":
                    for target in c["targets"]:
                        self.db.execute("UPDATE claims SET status='superseded' WHERE claim_id=?",(target,))
                    self._quarantine_descendants(c["targets"])
                elif c["relation"]=="RETRACT":
                    for target in c["targets"]:
                        self.db.execute("UPDATE claims SET status='retracted' WHERE claim_id=?",(target,))
                    self._quarantine_descendants(c["targets"])

            for i,(cid,c) in enumerate(zip(claim_ids,canonical)):
                base=("user_assertion" if role=="user" else "assistant_history")
                # RETRACT is an action/history record, never current user state itself.
                status="history_only" if c["relation"]=="RETRACT" else "active"
                self.db.execute("""INSERT INTO claims
                  (claim_id,source_message_id,derivation_key,ordinal,claim_text,claim_text_hash,
                   evidence_quote,source_anchor,source_role,authority_base,relation_kind,
                   effective_at,status,created_order)
                  VALUES(?,?,NULL,?,?,?,?,?,?,?,?,?,?,?)""",
                  (cid,sid,i,c["claim_text"],sha_text(c["claim_text"]),c["evidence_quote"],
                   c["source_anchor"],role,base,c["relation"],t,status,order+i))
                self.db.execute("INSERT INTO claims_fts(claim_id,claim_text) VALUES(?,?)",(cid,c["claim_text"]))
                for target in c["targets"]:
                    rel={"SUPERSEDE":"SUPERSEDES","RETRACT":"RETRACTS","CONFLICT":"CONFLICTS"}[c["relation"]]
                    self.db.execute("INSERT INTO claim_relations VALUES(?,?,?)",(cid,target,rel))
                if c["relation"]=="CONFLICT":
                    self._quarantine_descendants(c["targets"])
        return {"status":"inserted","source_message_id":sid,"claim_ids":claim_ids}

    def derive(self,derivation_key,claim_text,parent_claim_ids,effective_at):
        parents=sorted(set(parent_claim_ids))
        if not parents:raise ValueError("derived_requires_parents")
        rows=[]
        for p in parents:
            r=self._claim(p)
            if r is None:raise ValueError("derived_parent_missing")
            rows.append(r)
        cid=sha_obj({"derivation_key":str(derivation_key),"parents":parents,
                     "claim_text":str(claim_text)})
        old=self._claim(cid)
        if old:return {"status":"duplicate","claim_id":cid}
        conflicted=self._conflicted_user_claims()
        status="active" if all(r["status"]=="active" and r["claim_id"] not in conflicted for r in rows) else "quarantined"
        order=self._next_order()
        with self.db:
            self.db.execute("""INSERT INTO claims
              (claim_id,source_message_id,derivation_key,ordinal,claim_text,claim_text_hash,
               evidence_quote,source_anchor,source_role,authority_base,relation_kind,
               effective_at,status,created_order)
              VALUES(?,NULL,?,0,?,?,NULL,NULL,'derived','derived_history','DERIVED',?,?,?)""",
              (cid,str(derivation_key),str(claim_text),sha_text(claim_text),int(effective_at),status,order))
            self.db.execute("INSERT INTO claims_fts(claim_id,claim_text) VALUES(?,?)",(cid,str(claim_text)))
            for p in parents:
                self.db.execute("INSERT INTO claim_relations VALUES(?,?, 'DERIVED_FROM')",(cid,p))
        return {"status":"inserted","claim_id":cid}

    def set_source_lifecycle(self,source_message_id,lifecycle,effective_at=None):
        if lifecycle not in ("active","quarantined","deleted"):raise ValueError("bad_lifecycle")
        src=self._source(source_message_id)
        if src is None:raise ValueError("source_missing")
        with self.db:
            self.db.execute("UPDATE source_messages SET lifecycle=? WHERE source_message_id=?",
                            (lifecycle,source_message_id))
            if lifecycle!="active":
                roots=[r[0] for r in self.db.execute(
                  "SELECT claim_id FROM claims WHERE source_message_id=?",(source_message_id,))]
                self._quarantine_claim_and_descendants(roots)
        return {"status":"updated","source_message_id":source_message_id,"lifecycle":lifecycle}

    def claim_ancestors(self,claim_id):
        out=[];todo=[claim_id];seen={claim_id}
        while todo:
            child=todo.pop()
            for r in self.db.execute(
              "SELECT parent_claim_id FROM claim_relations WHERE child_claim_id=? AND relation='DERIVED_FROM'",
              (child,)):
                p=r[0]
                if p not in seen:seen.add(p);out.append(p);todo.append(p)
        return sorted(out)

    def _conflicted_user_claims(self):
        bad=set()
        rows=self.db.execute("""SELECT child_claim_id,parent_claim_id FROM claim_relations
          WHERE relation='CONFLICTS'""").fetchall()
        for r in rows:
            a=self._claim(r["child_claim_id"]);b=self._claim(r["parent_claim_id"])
            if a and b and a["status"]=="active" and b["status"]=="active" and                a["source_role"]=="user" and b["source_role"]=="user":
                bad.add(a["claim_id"]);bad.add(b["claim_id"])
        return bad

    def current_view(self):
        conflicts=self._conflicted_user_claims()
        rows=[dict(r) for r in self.db.execute(
          "SELECT * FROM claims WHERE status='active' AND source_role='user' ORDER BY effective_at,created_order")]
        current=[];conf=[]
        for r in rows:
            if r["claim_id"] in conflicts:conf.append(r)
            else:current.append(r)
        return {"status":"unresolved_conflict" if conf else ("known" if current else "unknown"),
                "current":current,"conflict":conf}

    @staticmethod
    def _fts_query(text):
        toks=re.findall(r"[A-Za-z0-9_]+",str(text).lower())
        toks=[x for x in toks if len(x)>1]
        return " OR ".join('"'+x.replace('"','')+'"' for x in sorted(set(toks)))

    def recall(self,query,mode="history",limit=7):
        fq=self._fts_query(query)
        if not fq:return []
        ids=[r[0] for r in self.db.execute(
          "SELECT claim_id FROM claims_fts WHERE claims_fts MATCH ? ORDER BY bm25(claims_fts) LIMIT ?",
          (fq,max(int(limit)*8,32)))]
        conflicts=self._conflicted_user_claims()
        out=[]
        for cid in ids:
            r=self._claim(cid)
            if not r:continue
            status=r["status"];role=r["source_role"]
            if status=="quarantined":continue
            if mode=="current":
                if status!="active" or role!="user":continue
                authority="user_conflict" if cid in conflicts else "user_state"
            else:
                if role=="assistant":authority="conversation_history"
                elif role=="derived":authority="derived_history"
                elif status=="active" and cid not in conflicts:authority="user_state"
                elif status=="active" and cid in conflicts:authority="user_conflict"
                else:authority="user_history"
            out.append({"claim_id":cid,"text":r["claim_text"],"authority":authority,
                        "status":status,"effective_at":r["effective_at"],
                        "source_message_id":r["source_message_id"],
                        "ancestors":self.claim_ancestors(cid) if role=="derived" else []})
            if len(out)>=int(limit):break
        return out

    def history(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM claims ORDER BY created_order")]

    def source_history(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM source_messages ORDER BY effective_at,message_seq")]
