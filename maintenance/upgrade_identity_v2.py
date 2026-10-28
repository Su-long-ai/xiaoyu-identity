# -*- coding: utf-8 -*-
"""One-time source migration to provenance-aware identity V2.
Edits only identity_core.py; caller must back up DB and old source first.
"""
from pathlib import Path

f=Path(__file__).resolve().parent / "identity_core.py"
s=f.read_text(encoding="utf-8")
if 'def _upgrade_schema' in s:
    print("SOURCE_ALREADY_UPGRADED")
    raise SystemExit(0)

def rep(before, after):
    global s
    n=s.count(before)
    if n!=1:
        raise RuntimeError("Expected one anchor, got "+str(n)+": "+repr(before[:90]))
    s=s.replace(before,after)

rep('SCHEMA_VERSION = 1','SCHEMA_VERSION = 2')
rep('        self._schema()\n        self._bootstrap_once()', '        self._schema()\n        self._bootstrap_once()\n        self._upgrade_schema()')
rep('    def _set(self, key, value):', '''
    def _upgrade_schema(self):
        """v1 imported four creator-authored setup notes as active 'legacy' memories.
        These are NOT user interaction memories. Reclassify without losing originals.
        """
        version=self._get("schema_version",0)
        if version >= SCHEMA_VERSION:
            return
        with self.conn:
            rows=self.conn.execute(
                "UPDATE memories SET category='bootstrap',status='bootstrap',updated_at=? "
                "WHERE category='legacy' AND source_event IS NULL", (now(),))
            self._set("schema_version", SCHEMA_VERSION)
            self._insert_event("system.provenance_migration","system",
                "Creator-authored initialization notes reclassified as bootstrap settings.",
                {"reclassified":rows.rowcount,"from_schema":version})

    def _set(self, key, value):'''.lstrip('\n'))
rep('            """ )', '            """ )') if False else None
rep('                CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind,event_id);',
    '''                CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind,event_id);''')
# Create proposal table separately, compatible with both old and new databases.
rep('    def _bootstrap_once(self):',
    '''    def _bootstrap_once(self):''')
rep('            self.conn.executescript("""', '            self.conn.executescript("""') if False else None
rep('            """)\n\n    def _upgrade_schema', '''
            """)
            self.conn.execute("""CREATE TABLE IF NOT EXISTS memory_proposals (
                proposal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                source_event INTEGER NOT NULL UNIQUE,
                text TEXT NOT NULL,
                origin TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_at TEXT,
                FOREIGN KEY(source_event) REFERENCES events(event_id)
            )""")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status "
                              "ON memory_proposals(status,proposal_id)")

    def _upgrade_schema''')
rep('(now(),now(),"legacy",line[2:],3,"active")',
    '(now(),now(),"bootstrap",line[2:],3,"bootstrap")')
rep('    def archive_memory(self, memory_id):', '''
    def list_bootstrap(self):
        """Read-only creator-supplied setup notes, excluded from active recall."""
        return [dict(row) for row in self.conn.execute(
            "SELECT memory_id,text,created_at FROM memories "
            "WHERE category='bootstrap' AND status='bootstrap' ORDER BY memory_id")]

    def propose_from_user_event(self, source_event, message):
        """Conservative literal proposals, never fabricate or auto-accept memories.
        Only direct, real user statements trigger proposals. One per source event.
        """
        message=str(message).strip()
        if not 5 <= len(message) <= 240 or '\\n' in message:
            return None
        source=self.conn.execute("SELECT kind,actor,content FROM events "
                                 "WHERE event_id=?",(int(source_event),)).fetchone()
        if not source or source["kind"]!="conversation.user" or source["content"]!=message:
            raise ValueError("Source must be an actual user message matching the proposal")
        explicit=re.match(r"^(?:请)?记住[：:\\s]+(.{3,200})$",message)
        if explicit:
            candidate=explicit.group(1).strip()
            origin="explicit"
        elif re.match(r"^(?:我(?:很|特别|更)?(?:喜欢|不喜欢|希望|讨厌|倾向于|习惯|偏好)|以后(?:你|我们))",message):
            if any(mark in message for mark in ("?", "？")):
                return None
            candidate=message
            origin="literal_preference"
        else:
            return None
        if len(candidate)<3:
            return None
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO memory_proposals(at,source_event,text,origin,status)"
                " VALUES(?,?,?,?,?)", (now(),int(source_event),candidate,origin,"pending"))
            found=self.conn.execute("SELECT proposal_id FROM memory_proposals "
                                    "WHERE source_event=?",(int(source_event),)).fetchone()
        return int(found[0]) if found else None

    def list_proposals(self, status="pending"):
        if status not in ("pending","accepted","rejected"):
            raise ValueError("Unknown proposal status")
        return [dict(row) for row in self.conn.execute(
            "SELECT p.proposal_id,p.source_event,p.text,p.origin,p.at,p.status,"
            "e.content AS evidence_text,e.at AS evidence_at FROM memory_proposals p "
            "JOIN events e ON e.event_id=p.source_event "
            "WHERE p.status=? ORDER BY p.proposal_id", (status,))]

    def review_proposal(self, proposal_id, accept):
        """No automatic inference becomes memory without explicit approval."""
        with self.conn:
            proposal=self.conn.execute(
                "SELECT * FROM memory_proposals WHERE proposal_id=? AND status='pending'",
                (int(proposal_id),)).fetchone()
            if not proposal:
                raise ValueError("Candidate not pending")
            if accept:
                category="preference" if proposal["origin"]=="literal_preference" else "shared"
                self.conn.execute(
                    "INSERT INTO memories(created_at,updated_at,category,text,source_event,priority,status)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (now(),now(),category,proposal["text"],proposal["source_event"],4,"active"))
            self.conn.execute(
                "UPDATE memory_proposals SET status=?,reviewed_at=? WHERE proposal_id=?",
                ("accepted" if accept else "rejected",now(),int(proposal_id)))
            self._insert_event("memory.reviewed","user",str(proposal_id),
                               {"decision":"accepted" if accept else "rejected",
                                "source_event":proposal["source_event"]})

    def actual_progress(self):
        """Only real user & assistant interactions are shared history.
        Bootstrap/setup and technical system events NEVER count as shared memories.
        """
        scalar=lambda sql:self.conn.execute(sql).fetchone()[0]
        return {
            "user_messages":scalar("SELECT count(*) FROM events WHERE kind='conversation.user'"),
            "assistant_replies":scalar("SELECT count(*) FROM events WHERE kind='conversation.assistant'"),
            "pet_actions":scalar("SELECT count(*) FROM events WHERE kind LIKE 'pet.%'"),
            "confirmed_memories":scalar(
                "SELECT count(*) FROM memories WHERE status='active' "
                "AND category NOT IN ('bootstrap','legacy')"),
            "bootstrap_notes":scalar(
                "SELECT count(*) FROM memories WHERE status='bootstrap' AND category='bootstrap'"),
            "pending_candidates":scalar(
                "SELECT count(*) FROM memory_proposals WHERE status='pending'"),
            "approved_growth":max(0,scalar("SELECT count(*) FROM persona_versions")-1)
        }

    def archive_memory(self, memory_id):'''.lstrip('\n'))
rep('            "memories":[dict(x) for x in self.conn.execute(',
    '            "memory_proposals":[dict(x) for x in self.conn.execute(\n                "SELECT * FROM memory_proposals ORDER BY proposal_id")],\n            "memories":[dict(x) for x in self.conn.execute(')
rep('if manifest.get("format") != NAMESPACE or manifest.get("version") != SCHEMA_VERSION:',
    'if manifest.get("format") != NAMESPACE or manifest.get("version") not in (1,SCHEMA_VERSION):')
# Suppress bootstrap contents from contextual long-term recall, even after upgrades.
rep('            "\\n【相关长期记忆（可追溯，可能过时）】\\n" +',
    '            "\\n【经确认的长期记忆；不包含开发者初始化设定】\\n" +')
f.write_text(s,encoding="utf-8")
print("SOURCE_V2_PATCHED")
