# -*- coding: utf-8 -*-
"""Product memory bridge base: minimal derived index plus R47-only confirmed-memory runtime.

Only the exact accepted R47 store is a frozen runtime dependency. User-confirmed
product memories are projected into authoritative user state through that store,
while the local SQLite/FTS index remains retrieval acceleration only.

The adapter never uploads private identity data and performs no provider/model/network calls.
"""
from __future__ import annotations

import hashlib
import importlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_MEMORY_SOURCE_KINDS = {"conversation.user", "memory.saved", "memory.corrected"}


def _bulk_ingest_confirmed_new(r47, store, items, chunk_size=256):
    """Atomic all-new confirmed-NEW bulk writer for the exact R47 schema."""
    if not items:
        return {"mode":"bulk","results":[],"chunks":0}
    prepared=[];seen=set()
    for item in items:
        src=item["src"]; candidate=item["candidate"]
        sid=r47.source_message_id(src["conversation_id"],src["message_id"])
        if sid in seen: raise ValueError("bulk_duplicate_source_id")
        seen.add(sid)
        if store._source(sid) is not None: raise ValueError("bulk_existing_source")
        canonical=store._canonical_candidates(src["text"],[candidate])
        if len(canonical)!=1 or canonical[0]["relation"]!="NEW" or canonical[0]["targets"]:
            raise ValueError("bulk_requires_single_targetless_new")
        c=canonical[0]; t=int(src["effective_at"]); role=str(src["source_role"]); txt=str(src["text"])
        source_row=(sid,str(src["conversation_id"]),str(src["message_id"]),int(src["message_seq"]),
                    role,txt,r47.sha_text(txt),t,r47.sha_obj(canonical),"active")
        cid=r47.sha_obj({"source_message_id":sid,"ordinal":0})
        authority="user_assertion" if role=="user" else "assistant_history"
        claim_prefix=(cid,sid,None,0,c["claim_text"],r47.sha_text(c["claim_text"]),c["evidence_quote"],
                      c["source_anchor"],role,authority,"NEW",t,"active")
        prepared.append((source_row,claim_prefix,(cid,c["claim_text"]),cid))
    chunk=max(1,int(chunk_size))
    store.db.execute("BEGIN IMMEDIATE")
    try:
        if int(store.db.execute("SELECT count(*) FROM source_messages").fetchone()[0])!=0:
            store.db.rollback()
            return {"mode":"fallback_race","results":[],"chunks":0}
        next_order=int(store.db.execute("SELECT COALESCE(MAX(created_order),0)+1 FROM claims").fetchone()[0])
        built=[]
        for source_row,claim_prefix,fts_row,cid in prepared:
            built.append((source_row,claim_prefix+(next_order,),fts_row,cid)); next_order+=1
        chunks=0
        for off in range(0,len(built),chunk):
            part=built[off:off+chunk]
            store.db.executemany("""INSERT INTO source_messages(
                source_message_id,conversation_id,message_id,message_seq,source_role,source_text,
                source_text_hash,effective_at,projection_hash,lifecycle) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [x[0] for x in part])
            store.db.executemany("""INSERT INTO claims(
                claim_id,source_message_id,derivation_key,ordinal,claim_text,claim_text_hash,
                evidence_quote,source_anchor,source_role,authority_base,relation_kind,
                effective_at,status,created_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [x[1] for x in part])
            store.db.executemany("INSERT INTO claims_fts(claim_id,claim_text) VALUES(?,?)",[x[2] for x in part])
            chunks+=1
        store.db.commit()
    except Exception:
        store.db.rollback(); raise
    return {"mode":"bulk","chunks":chunks,"results":[
        {"status":"inserted","source_message_id":x[0][0],"claim_ids":[x[3]]} for x in built]}


EXPECTED = {
    "r47_open_domain_memory_store_frozen.py": "44d41231dae573dbc360b62a8144ebe4b929808a72dc7197705ee26a704092f9",
}


def safe_product_recall(bridge, query: str, limit: int = 7):
    """Return product-authorized memory rows or an explicit empty set on failure."""
    if bridge is None:
        return [], "memory_bridge_unavailable"
    try:
        rows = bridge.recall(query, limit=limit)
        status = bridge.status()
        quarantined = int(status.get("quarantined_rows") or 0)
        if quarantined:
            return rows, f"quarantined_memories:{quarantined}"
        return rows, None
    except Exception as err:
        return [], type(err).__name__ + ": " + str(err)


class ProductMemoryBridgeError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _keywords(text: str) -> set[str]:
    """Dependency-free Chinese bigrams + normalized Latin tokens."""
    parts = re.findall(r"[\u3400-\u9fff]+|[a-zA-Z0-9_-]+", str(text).lower())
    out: set[str] = set()
    for part in parts:
        if re.fullmatch(r"[\u3400-\u9fff]+", part):
            if len(part) == 1:
                out.add(part)
            else:
                out.update(part[i : i + 2] for i in range(len(part) - 1))
        elif len(part) > 1:
            token = part
            if len(token) > 4 and token.endswith("ing"):
                token = token[:-3]
            elif len(token) > 3 and token.endswith("ed"):
                token = token[:-2]
            elif len(token) > 3 and token.endswith("s"):
                token = token[:-1]
            out.add(token)
    return out


def _epoch(iso: Any, fallback: int) -> int:
    try:
        d = datetime.fromisoformat(str(iso))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp())
    except Exception:
        return int(fallback)


class ProductMemoryBridge:
    """Mirror confirmed product memories into exact accepted R47 authority state.

    The R47 store remains the authority layer. A separate local inverted index only
    accelerates candidate retrieval; it never creates or upgrades memory authority.
    """

    INDEX_SCHEMA_VERSION = 6

    def __init__(self, home, identity_store, component_root=None):
        self.home = Path(home)
        self.identity_store = identity_store
        self.component_root = Path(component_root) if component_root else Path(__file__).resolve().parent
        self.frozen = self.component_root / "product_components" / "memory_engine_v1"
        self.pipeline = None
        self.index = None
        try:
            self._verify_frozen()
            self._load_modules()
            self.db_path = self.home / "identity" / "product_memory_bridge.sqlite3"
            self.index_db_path = self.home / "identity" / "product_memory_index.sqlite3"
            identity_id = str(self.identity_store.persona().get("id") or "xiaoyu-product")
            self.pipeline = self._pipeline_cls(self.db_path, identity_id=identity_id)
            self.index = sqlite3.connect(str(self.index_db_path), timeout=15)
            self.index.row_factory = sqlite3.Row
            self.index.execute("PRAGMA foreign_keys=ON")
            self.index.execute("PRAGMA journal_mode=WAL")
            self._index_schema()
            self.last_sync = {
                "warnings": [], "processed": 0, "full_reconcile": False,
            }
            self.sync()
        except Exception:
            if self.index is not None:
                try:
                    self.index.close()
                except Exception:
                    pass
            if self.pipeline is not None:
                try:
                    self.pipeline.close()
                except Exception:
                    pass
            raise

    def _verify_frozen(self):
        name = "r47_open_domain_memory_store_frozen.py"
        expected = EXPECTED[name]
        path = self.frozen / name
        if not path.is_file():
            raise ProductMemoryBridgeError(
                "accepted R47 runtime dependency unavailable"
            )
        actual = _sha(path)
        if actual != expected:
            raise ProductMemoryBridgeError(
                "accepted R47 runtime dependency drifted: "
                + repr({"file": name, "expected": expected, "actual": actual})
            )

    def _load_modules(self):
        frozen = str(self.frozen)
        inserted = not sys.path or sys.path[0] != frozen
        if inserted:
            sys.path.insert(0, frozen)
        try:
            sys.modules.pop("r47_open_domain_memory_store_frozen", None)
            self._r47 = importlib.import_module("r47_open_domain_memory_store_frozen")
        finally:
            if inserted and sys.path and sys.path[0] == frozen:
                sys.path.pop(0)
        r47 = self._r47

        class ConfirmedProductPipeline:
            def __init__(self, db_path, identity_id="xiaoyu-product", confirmation_key=None):
                self.store = r47.OpenDomainMemoryStore(db_path)
                self.identity_id = identity_id
                self.external_by_internal = {}
                self.seen_external = {}

            def close(self):
                self.store.close()

            def _bind_source(self, src):
                internal = r47.source_message_id(
                    src["conversation_id"], src["message_id"]
                )
                external = str(src["source_id"])
                old = self.external_by_internal.get(internal)
                if old is not None and old != external:
                    raise ValueError("external_source_binding_drift")
                self.external_by_internal[internal] = external
                self.seen_external[external] = {
                    "source_id": external,
                    "source_role": src["source_role"],
                    "effective_at": int(src["effective_at"]),
                }
                return internal

            @staticmethod
            def _confirmed_new_candidate(src, raw_projection):
                if str(src.get("source_role")) != "user":
                    raise ValueError("confirmed_new_requires_user_source")
                if not isinstance(raw_projection, dict) or set(raw_projection) != {"outputs"}:
                    raise ValueError("confirmed_new_bad_projection")
                outs = raw_projection["outputs"]
                if not isinstance(outs, list) or len(outs) != 1 or not isinstance(outs[0], dict):
                    raise ValueError("confirmed_new_bad_outputs")
                out = outs[0]
                if set(out) != {"status", "proposals"} or out.get("status") != "propose":
                    raise ValueError("confirmed_new_requires_propose")
                props = out.get("proposals")
                if not isinstance(props, list) or len(props) != 1 or not isinstance(props[0], dict):
                    raise ValueError("confirmed_new_single_proposal_required")
                p = props[0]
                if set(p) != {"claim_text", "evidence_quote", "relation", "target_ids"}:
                    raise ValueError("confirmed_new_bad_proposal_shape")
                if p.get("relation") != "NEW" or p.get("target_ids") != []:
                    raise ValueError("confirmed_new_must_be_targetless_new")
                source_text = str(src.get("text") or "")
                claim = str(p.get("claim_text") or "")
                quote = str(p.get("evidence_quote") or "")
                if not source_text or claim != source_text.strip() or quote != source_text.strip():
                    raise ValueError("confirmed_new_text_mismatch")
                return {
                    "claim_text": claim,
                    "evidence_quote": quote,
                    "relation": "NEW",
                    "targets": [],
                }

            def ingest_source(self, src, raw_projection=None):
                candidate = self._confirmed_new_candidate(src, raw_projection)
                self._bind_source(src)
                rr = self.store.ingest(
                    src["conversation_id"],
                    src["message_id"],
                    src["message_seq"],
                    src["source_role"],
                    src["text"],
                    src["effective_at"],
                    [candidate],
                )
                return {
                    "kind": "ingested",
                    "ingest": rr,
                    "canonical": {
                        "outputs": [
                            {
                                "source_position": 0,
                                "status": "propose",
                                "proposals": [
                                    {
                                        "claim_text": candidate["claim_text"],
                                        "evidence_quote": candidate["evidence_quote"],
                                        "relation": "NEW",
                                        "target_ids": [],
                                    }
                                ],
                            }
                        ]
                    },
                }

            def _external_sid(self, internal):
                return self.external_by_internal.get(str(internal), str(internal))

            def current_rows(self):
                view = self.store.current_view()
                out = []
                for row in view["current"]:
                    out.append(
                        {
                            "text": row["claim_text"],
                            "authority": "user_state",
                            "source_id": self._external_sid(row["source_message_id"]),
                        }
                    )
                for row in view["conflict"]:
                    out.append(
                        {
                            "text": row["claim_text"],
                            "authority": "user_conflict",
                            "source_id": self._external_sid(row["source_message_id"]),
                        }
                    )
                return out

            def source_count(self):
                return int(
                    self.store.db.execute(
                        "SELECT count(*) FROM source_messages"
                    ).fetchone()[0]
                )

            def semantic_duplicate_count(self):
                row = self.store.db.execute(
                    "SELECT COALESCE(MAX(n),0) FROM "
                    "(SELECT count(*) n FROM claims "
                    "GROUP BY source_message_id,claim_text_hash)"
                ).fetchone()
                return int(row[0] or 0)

        self._pipeline_cls = ConfirmedProductPipeline

    def _index_schema(self):
        # Derived retrieval state keeps only fields needed before final authority
        # reconstruction. Product text/category stay single-sourced in IdentityStore.
        self.index.execute("""
            CREATE TABLE IF NOT EXISTS index_settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        prior = self._index_get("schema_version")
        with self.index:
            self.index.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS product_memory_fts "
                "USING fts5(memory_id UNINDEXED, terms, tokenize='unicode61')"
            )
            self.index.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS product_memory_history_fts "
                "USING fts5(memory_id UNINDEXED, terms, tokenize='unicode61')"
            )
            self.index.execute("""
                CREATE TABLE IF NOT EXISTS product_memory_history_exact(
                    memory_id INTEGER PRIMARY KEY,
                    text_sha256 TEXT NOT NULL
                )
            """)
            self.index.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_memory_history_exact_sha "
                "ON product_memory_history_exact(text_sha256,memory_id)"
            )
            columns = {
                str(row["name"])
                for row in self.index.execute("PRAGMA table_info(product_memory_meta)")
            }
            expected = {"memory_id", "priority", "status", "source_event"}
            if columns and columns != expected:
                self.index.execute("DROP TABLE product_memory_meta")
                self._index_set("initialized", "0")
            self.index.execute("""
                CREATE TABLE IF NOT EXISTS product_memory_meta(
                    memory_id INTEGER PRIMARY KEY,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    source_event INTEGER
                )
            """)
            self.index.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_memory_meta_status "
                "ON product_memory_meta(status,memory_id)"
            )
            if prior not in (None, str(self.INDEX_SCHEMA_VERSION)):
                self.index.execute("DROP TABLE IF EXISTS product_memory_terms")
                self.index.execute("DELETE FROM product_memory_fts")
                self.index.execute("DELETE FROM product_memory_history_fts")
                self.index.execute("DELETE FROM product_memory_history_exact")
                self._index_set("initialized", "0")
            self._index_set("schema_version", str(self.INDEX_SCHEMA_VERSION))

    def _index_get(self, key, default=None):
        row = self.index.execute(
            "SELECT value FROM index_settings WHERE key=?", (str(key),)
        ).fetchone()
        return row["value"] if row else default

    def _index_set(self, key, value):
        self.index.execute(
            "INSERT INTO index_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(key), str(value)),
        )

    def close(self):
        try:
            if self.index is not None:
                self.index.close()
        finally:
            if self.pipeline is not None:
                self.pipeline.close()

    @staticmethod
    def _external_id(memory_id: int) -> str:
        return f"memory:{int(memory_id)}"

    def _source(self, row: dict) -> dict:
        mid = int(row["memory_id"])
        created = row.get("created_at")
        return {
            "conversation_id": "xiaoyu-product-confirmed-memory",
            "message_id": f"memory-{mid}",
            "message_seq": mid,
            "source_role": "user",
            "text": str(row["text"]),
            "effective_at": _epoch(created, mid),
            "source_id": self._external_id(mid),
        }

    @staticmethod
    def _confirmed_projection(text: str) -> dict:
        text = str(text).strip()
        return {
            "outputs": [
                {
                    "status": "propose",
                    "proposals": [
                        {
                            "claim_text": text,
                            "evidence_quote": text,
                            "relation": "NEW",
                            "target_ids": [],
                        }
                    ],
                }
            ]
        }

    def _rows(self) -> list[dict]:
        q = """SELECT memory_id,created_at,updated_at,category,text,source_event,priority,status,change_seq
               FROM memories
               WHERE category NOT IN ('bootstrap','legacy')
               ORDER BY memory_id"""
        return [dict(r) for r in self.identity_store.conn.execute(q)]

    def _changed_rows(self) -> list[dict]:
        if self._index_get("initialized") != "1":
            return self._rows()
        last_seq = int(self._index_get("last_change_seq", "0") or 0)
        last_updated = self._index_get("last_updated_at", "")
        last_id = int(self._index_get("last_memory_id", "0") or 0)
        # change_seq is the correctness boundary for normal product mutations.
        # updated_at remains a secondary integrity probe for out-of-contract
        # direct DB edits that bypass the IdentityStore mutation allocator.
        q = """SELECT memory_id,created_at,updated_at,category,text,source_event,priority,status,change_seq
               FROM memories
               WHERE category NOT IN ('bootstrap','legacy')
                 AND (change_seq > ? OR updated_at > ? OR memory_id > ?)
               ORDER BY change_seq,memory_id"""
        return [
            dict(r) for r in self.identity_store.conn.execute(
                q, (last_seq, last_updated, last_id)
            )
        ]

    def _snapshot_rows_and_boundary(self, *, full: bool = False):
        """Capture rows and cursor maxima from one short SQLite read snapshot."""
        initialized = self._index_get("initialized") == "1"
        last_seq = int(self._index_get("last_change_seq", "0") or 0)
        last_updated = self._index_get("last_updated_at", "")
        last_id = int(self._index_get("last_memory_id", "0") or 0)

        # Normal product calls arrive outside an IdentityStore transaction. Reuse
        # that WAL connection so the snapshot costs only two reads. If a caller
        # already owns a transaction, use a separate read connection rather than
        # committing/rolling back caller state.
        snap = self.identity_store.conn
        separate = bool(snap.in_transaction)
        if separate:
            snap = sqlite3.connect(str(self.identity_store.db_path), timeout=15)
            snap.row_factory = sqlite3.Row
            snap.execute("PRAGMA query_only=ON")
        opened = False
        try:
            snap.execute("BEGIN")
            opened = True
            boundary = dict(snap.execute(
                """SELECT COALESCE(MAX(updated_at),'') AS max_updated,
                          COALESCE(MAX(memory_id),0) AS max_id,
                          COALESCE(MAX(change_seq),0) AS max_change_seq,
                          COUNT(*) AS n
                   FROM memories WHERE category NOT IN ('bootstrap','legacy')"""
            ).fetchone())
            revision = snap.execute(
                "SELECT value FROM settings WHERE key='memory_table_revision'"
            ).fetchone()
            boundary["memory_table_revision"] = int(revision["value"] if revision else 0)
            if full or not initialized:
                q = """SELECT memory_id,created_at,updated_at,category,text,source_event,priority,status,change_seq
                       FROM memories
                       WHERE category NOT IN ('bootstrap','legacy')
                       ORDER BY memory_id"""
                rows = [dict(r) for r in snap.execute(q)]
            else:
                q = """SELECT memory_id,created_at,updated_at,category,text,source_event,priority,status,change_seq
                       FROM memories
                       WHERE category NOT IN ('bootstrap','legacy')
                         AND (change_seq > ? OR updated_at > ? OR memory_id > ?)
                       ORDER BY change_seq,memory_id"""
                rows = [dict(r) for r in snap.execute(q,(last_seq,last_updated,last_id))]
            return rows, boundary
        finally:
            try:
                if opened and snap.in_transaction:
                    snap.rollback()
            finally:
                if separate:
                    snap.close()

    def _index_upsert(self, row: dict, source_id: str, source_message_id: str, active: bool, history_admissible: bool = False):
        mid = int(row["memory_id"])
        text_value = str(row["text"])
        status = "active" if active else (
            "quarantined" if row["status"] == "active" else str(row["status"])
        )
        self.index.execute(
            """INSERT INTO product_memory_meta(memory_id,priority,status,source_event)
               VALUES(?,?,?,?)
               ON CONFLICT(memory_id) DO UPDATE SET
                   priority=excluded.priority,
                   status=excluded.status,
                   source_event=excluded.source_event""",
            (
                mid,
                int(row.get("priority") or 3),
                status,
                int(row["source_event"]) if row.get("source_event") is not None else None,
            ),
        )
        self.index.execute(
            "DELETE FROM product_memory_fts WHERE memory_id=?", (str(mid),)
        )
        self.index.execute(
            "DELETE FROM product_memory_history_fts WHERE memory_id=?", (str(mid),)
        )
        self.index.execute(
            "DELETE FROM product_memory_history_exact WHERE memory_id=?", (mid,)
        )
        if active or (str(row["status"]) == "superseded" and history_admissible):
            terms = " ".join(sorted(_keywords(text_value)))
            if terms:
                table = "product_memory_fts" if active else "product_memory_history_fts"
                self.index.execute(
                    f"INSERT INTO {table}(memory_id,terms) VALUES(?,?)",
                    (str(mid), terms),
                )
            if (not active) and str(row["status"]) == "superseded" and history_admissible:
                self.index.execute(
                    "INSERT INTO product_memory_history_exact(memory_id,text_sha256) VALUES(?,?)",
                    (mid, hashlib.sha256(text_value.encode("utf-8")).hexdigest()),
                )

    def _remove_index_memory(self, memory_id: int):
        self.index.execute(
            "DELETE FROM product_memory_fts WHERE memory_id=?", (str(int(memory_id)),)
        )
        self.index.execute(
            "DELETE FROM product_memory_history_fts WHERE memory_id=?", (str(int(memory_id)),)
        )
        self.index.execute(
            "DELETE FROM product_memory_history_exact WHERE memory_id=?", (int(memory_id),)
        )
        self.index.execute(
            "DELETE FROM product_memory_meta WHERE memory_id=?", (int(memory_id),)
        )

    def _record_physical_delete(self, memory_id: int, source_event: int | None):
        """Persist a plaintext-free deletion marker at the identity boundary.

        The deleted memory text and its digest are deliberately not retained here.
        source_event is enough for model-visible history projection to avoid
        resurrecting deleted sibling plaintext after a full reconcile/restart.
        """
        if source_event is None:
            return
        mid = int(memory_id)
        exists = self.identity_store.conn.execute(
            "SELECT 1 FROM events WHERE kind='memory.deleted' AND content=? LIMIT 1",
            (str(mid),),
        ).fetchone()
        if exists:
            return
        self.identity_store.record(
            "memory.deleted",
            "system",
            str(mid),
            {"source_event": int(source_event), "detected_by": "product_memory_bridge"},
        )

    def _process_row(self, row: dict, warnings: list[str]) -> tuple[bool, bool]:
        src = self._source(row)
        sid = self._r47.source_message_id(src["conversation_id"], src["message_id"])
        self.pipeline.external_by_internal[sid] = src["source_id"]
        stored = self.pipeline.store._source(sid)

        canonical = self.identity_store.conn.execute(
            "SELECT event_id,kind,actor,content FROM events WHERE event_id=?",
            (row.get("source_event"),),
        ).fetchone()
        valid_user_source = bool(
            canonical
            and canonical["actor"] == "user"
            and canonical["kind"] in USER_MEMORY_SOURCE_KINDS
        )
        if not valid_user_source:
            if stored is not None and stored["lifecycle"] == "active":
                self.pipeline.store.set_source_lifecycle(sid, "quarantined")
            warnings.append(
                f"memory_{row['memory_id']}_invalid_canonical_source_quarantined"
            )
            self._index_upsert(row, src["source_id"], sid, False)
            return False, True

        self.pipeline.seen_external[src["source_id"]] = {
            "source_id": src["source_id"],
            "source_role": "user",
            "effective_at": int(src["effective_at"]),
        }
        active = row["status"] == "active"

        if active:
            if stored is None:
                try:
                    result = self.pipeline.ingest_source(
                        src, raw_projection=self._confirmed_projection(src["text"])
                    )
                except Exception as err:
                    landed = self.pipeline.store._source(sid)
                    if landed is not None and landed["lifecycle"] == "active":
                        self.pipeline.store.set_source_lifecycle(sid, "quarantined")
                    warnings.append(
                        f"memory_{row['memory_id']}_ingest_rejected:{type(err).__name__}"
                    )
                    self._index_upsert(row, src["source_id"], sid, False)
                    return False, True
                if result.get("kind") not in ("ingested", "pending"):
                    warnings.append("unexpected_ingest:" + repr(result))
                    self._index_upsert(row, src["source_id"], sid, False)
                    return False, True
                stored = self.pipeline.store._source(sid)

            expected_hash = hashlib.sha256(src["text"].encode()).hexdigest()
            if stored is None or stored["source_text_hash"] != expected_hash:
                # In-place mutation is outside the product API. Never let the local
                # acceleration index bypass R47's immutable-source semantics.
                if stored is not None and stored["lifecycle"] == "active":
                    self.pipeline.store.set_source_lifecycle(sid, "quarantined")
                warnings.append(f"memory_{row['memory_id']}_source_text_drift_quarantined")
                self._index_upsert(row, src["source_id"], sid, False)
                return False, True

            if stored["lifecycle"] != "active":
                warnings.append(f"memory_{row['memory_id']}_inactive_source_not_reactivated")
                self._index_upsert(row, src["source_id"], sid, False)
                return False, True

            self._index_upsert(row, src["source_id"], sid, True)
            return True, False

        if stored is not None and stored["lifecycle"] == "active":
            self.pipeline.store.set_source_lifecycle(sid, "quarantined")
        history_admissible = bool(
            str(row["status"]) == "superseded"
            and canonical
            and str(canonical["content"]) == str(row["text"])
            and (stored is None or stored["source_text_hash"] == hashlib.sha256(src["text"].encode()).hexdigest())
        )
        self._index_upsert(
            row, src["source_id"], sid, False,
            history_admissible=history_admissible,
        )
        return False, True

    def _checkpoint(self, boundary=None):
        row = boundary
        memory_table_revision = (
            self.identity_store.memory_table_revision()
            if boundary is None
            else int(boundary["memory_table_revision"])
        )
        if row is None:
            row = self.identity_store.conn.execute(
                """SELECT COALESCE(MAX(updated_at),'') AS max_updated,
                          COALESCE(MAX(memory_id),0) AS max_id,
                          COALESCE(MAX(change_seq),0) AS max_change_seq,
                          COUNT(*) AS n
                   FROM memories WHERE category NOT IN ('bootstrap','legacy')"""
            ).fetchone()
        self._index_set("last_updated_at", row["max_updated"])
        self._index_set("last_memory_id", int(row["max_id"]))
        self._index_set("last_change_seq", int(row["max_change_seq"]))
        self._index_set("identity_row_count", int(row["n"]))
        self._index_set("last_memory_table_revision", memory_table_revision)
        self._index_set("initialized", "1")
        self.index.commit()

    def _bulk_cold_reconcile(self, rows: list[dict], warnings: list[str]):
        # The fast path is intentionally unavailable for small batches, replay,
        # inactive rows, invalid provenance, or any non-empty R47 store. Those
        # cases retain the existing row-local exact path.
        if len(rows) < 256 or self.pipeline.source_count() != 0:
            return None

        prepared=[]
        for row in rows:
            if row["status"] != "active":
                return None
            canonical = self.identity_store.conn.execute(
                "SELECT event_id,kind,actor,content FROM events WHERE event_id=?",
                (row.get("source_event"),),
            ).fetchone()
            if not (
                canonical
                and canonical["actor"] == "user"
                and canonical["kind"] in USER_MEMORY_SOURCE_KINDS
            ):
                return None
            src=self._source(row)
            sid=self._r47.source_message_id(src["conversation_id"],src["message_id"])
            if self.pipeline.store._source(sid) is not None:
                return None
            candidate=self.pipeline._confirmed_new_candidate(
                src,self._confirmed_projection(src["text"])
            )
            prepared.append({"row":row,"src":src,"sid":sid,"candidate":candidate})

        # Authority lands in R47 first. If a process dies between chunks, no
        # derived-index checkpoint is committed; restart observes the non-empty
        # R47 store and falls back to exact per-row replay/convergence.
        bulk_result=_bulk_ingest_confirmed_new(
            self._r47,self.pipeline.store,
            [{"src":x["src"],"candidate":x["candidate"]} for x in prepared],
            chunk_size=256,
        )
        if bulk_result.get("mode") != "bulk":
            return None

        for item in prepared:
            row=item["row"];src=item["src"];sid=item["sid"]
            self.pipeline.external_by_internal[sid]=src["source_id"]
            self.pipeline.seen_external[src["source_id"]]={
                "source_id":src["source_id"],
                "source_role":"user",
                "effective_at":int(src["effective_at"]),
            }
            stored=self.pipeline.store._source(sid)
            expected_hash=hashlib.sha256(src["text"].encode()).hexdigest()
            if (
                stored is None
                or stored["source_text_hash"] != expected_hash
                or stored["lifecycle"] != "active"
            ):
                raise ProductMemoryBridgeError("bulk_confirmed_new_postcondition_failed")
            self._index_upsert(row,src["source_id"],sid,True)

        return len(rows),0,len(rows)

    def _full_reconcile(self, warnings: list[str]) -> tuple[int, int, int]:
        rows, boundary = self._snapshot_rows_and_boundary(full=True)
        present = set()
        bulk = self._bulk_cold_reconcile(rows,warnings)
        if bulk is not None:
            active,inactive,processed=bulk
            present={int(row["memory_id"]) for row in rows}
        else:
            active = inactive = 0
            for row in rows:
                present.add(int(row["memory_id"]))
                is_active, is_inactive = self._process_row(row, warnings)
                active += int(is_active)
                inactive += int(is_inactive)
            processed=len(rows)

        indexed = [
            dict(r)
            for r in self.index.execute(
                "SELECT memory_id,source_event FROM product_memory_meta"
            )
        ]
        for meta in indexed:
            mid = int(meta["memory_id"])
            if mid not in present:
                self._record_physical_delete(mid, meta.get("source_event"))
                self._remove_index_memory(mid)

        live_sids = {
            self._r47.source_message_id(
                "xiaoyu-product-confirmed-memory", f"memory-{mid}"
            )
            for mid in present
        }
        for src in self.pipeline.store.source_history():
            if src["conversation_id"] != "xiaoyu-product-confirmed-memory":
                continue
            sid = str(src["source_message_id"])
            if sid not in live_sids and src["lifecycle"] == "active":
                self.pipeline.store.set_source_lifecycle(sid, "quarantined")

        self._checkpoint(boundary)
        return active, inactive, processed

    def sync(self) -> dict:
        warnings: list[str] = []
        initialized = self._index_get("initialized") == "1"

        if not initialized:
            active, inactive, processed = self._full_reconcile(warnings)
            self.last_sync = {
                "active": active,
                "inactive": inactive,
                "warnings": warnings,
                "processed": processed,
                "full_reconcile": True,
            }
            return dict(self.last_sync)

        current_revision = self.identity_store.memory_table_revision()
        last_revision = int(
            self._index_get("last_memory_table_revision", "-1") or -1
        )
        if current_revision == last_revision:
            active_count = self.last_sync.get("active")
            inactive_count = self.last_sync.get("inactive")
            if active_count is None or inactive_count is None:
                indexed_count = int(
                    self.index.execute(
                        "SELECT COUNT(*) FROM product_memory_meta"
                    ).fetchone()[0]
                )
                active_count = int(
                    self.index.execute(
                        "SELECT COUNT(*) FROM product_memory_meta WHERE status='active'"
                    ).fetchone()[0]
                )
                inactive_count = indexed_count - active_count
            self.last_sync = {
                "active": int(active_count),
                "inactive": int(inactive_count),
                "warnings": warnings,
                "processed": 0,
                "full_reconcile": False,
            }
            return dict(self.last_sync)

        rows, boundary = self._snapshot_rows_and_boundary(full=False)
        active_delta = inactive_delta = 0
        for row in rows:
            is_active, is_inactive = self._process_row(row, warnings)
            active_delta += int(is_active)
            inactive_delta += int(is_inactive)

        identity_count = int(boundary["n"])
        indexed_count = int(
            self.index.execute("SELECT COUNT(*) FROM product_memory_meta").fetchone()[0]
        )
        membership_mismatch = indexed_count != identity_count
        missing_ids = set()
        if membership_mismatch:
            identity_ids = {
                int(row["memory_id"])
                for row in self.identity_store.conn.execute(
                    """SELECT memory_id FROM memories
                       WHERE category NOT IN ('bootstrap','legacy')"""
                )
            }
            indexed = {
                int(row["memory_id"]): row["source_event"]
                for row in self.index.execute(
                    "SELECT memory_id,source_event FROM product_memory_meta"
                )
            }

            for mid in indexed.keys() - identity_ids:
                self._record_physical_delete(mid, indexed[mid])
                self._remove_index_memory(mid)
                sid = self._r47.source_message_id(
                    "xiaoyu-product-confirmed-memory", f"memory-{mid}"
                )
                stored = self.pipeline.store._source(sid)
                if stored is not None and stored["lifecycle"] == "active":
                    self.pipeline.store.set_source_lifecycle(sid, "quarantined")

            missing_ids = identity_ids - indexed.keys()
            for mid in sorted(missing_ids):
                row = self.identity_store.conn.execute(
                    """SELECT memory_id,created_at,updated_at,category,text,
                              source_event,priority,status,change_seq
                       FROM memories WHERE memory_id=?
                         AND category NOT IN ('bootstrap','legacy')""",
                    (mid,),
                ).fetchone()
                if row is not None:
                    self._process_row(dict(row), warnings)

        self._checkpoint(boundary)

        indexed_count = int(
            self.index.execute("SELECT COUNT(*) FROM product_memory_meta").fetchone()[0]
        )
        active_count = int(
            self.index.execute(
                "SELECT COUNT(*) FROM product_memory_meta WHERE status='active'"
            ).fetchone()[0]
        )
        inactive_count = indexed_count - active_count
        processed = len(rows) + len(missing_ids)
        full_reconcile = bool(membership_mismatch)

        self.last_sync = {
            "active": active_count,
            "inactive": inactive_count,
            "warnings": warnings,
            "processed": processed,
            "full_reconcile": full_reconcile,
        }
        return dict(self.last_sync)

    def recall(self, query: str, limit: int = 7) -> list[dict]:
        self.sync()
        qk = sorted(_keywords(query))
        if not qk:
            return []

        def quote_fts(token: str) -> str:
            return '"' + str(token).replace('"', '""') + '"'

        match = " OR ".join(quote_fts(x) for x in qk[:256])
        candidate_cap = max(64, min(256, int(limit) * 24))
        rows = self.index.execute(
            """SELECT product_memory_fts.memory_id AS memory_id,
                      product_memory_fts.terms AS terms,
                      product_memory_meta.priority AS priority
               FROM product_memory_fts
               JOIN product_memory_meta
                 ON product_memory_meta.memory_id =
                    CAST(product_memory_fts.memory_id AS INTEGER)
               WHERE product_memory_fts MATCH ?
                 AND product_memory_meta.status='active'
               ORDER BY bm25(product_memory_fts)
               LIMIT ?""",
            (match, candidate_cap),
        ).fetchall()

        query_terms = set(qk)
        ranked = []
        for row in rows:
            mid = int(row["memory_id"])
            overlap = len(query_terms & set(str(row["terms"]).split()))
            if overlap <= 0:
                continue
            priority = int(row["priority"] or 3)
            score = overlap * 12 + priority * 2 + min(mid, 1_000_000) / 1_000_000
            ranked.append((score, mid, priority))
        ranked.sort(key=lambda x: (-x[0], -x[1]))
        if not ranked:
            return []

        out = []
        seen = set()
        batch_size = max(16, min(64, max(1, int(limit)) * 4))
        for offset in range(0, len(ranked), batch_size):
            batch = ranked[offset : offset + batch_size]
            ids = [mid for _, mid, _ in batch]
            marks = ",".join("?" for _ in ids)
            authoritative = {
                int(row["memory_id"]): dict(row)
                for row in self.identity_store.conn.execute(
                    f"""SELECT memory_id,category,text,priority,status
                        FROM memories
                        WHERE status='active' AND memory_id IN ({marks})""",
                    ids,
                )
            }
            for _, mid, priority in batch:
                m = authoritative.get(mid)
                if m is None:
                    continue
                key = (str(m["category"]), str(m["text"]))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "memory_id": mid,
                        "category": key[0],
                        "text": key[1],
                        "priority": int(m.get("priority") or priority),
                        "authority": "user_state",
                        "source_id": self._external_id(mid),
                        "retrieval": "product_state+sqlite_fts5_zh_bigram_v2",
                    }
                )
                if len(out) >= max(1, min(20, int(limit))):
                    return out
        return out

    def status(self) -> dict:
        active_count = int(
            self.index.execute(
                "SELECT COUNT(*) FROM product_memory_meta WHERE status='active'"
            ).fetchone()[0]
        )
        quarantined_count = int(
            self.index.execute(
                "SELECT COUNT(*) FROM product_memory_meta WHERE status='quarantined'"
            ).fetchone()[0]
        )
        return {
            "enabled": True,
            "db_path": str(self.db_path),
            "index_db_path": str(self.index_db_path),
            "index_schema_version": self.INDEX_SCHEMA_VERSION,
            "retrieval_backend": "sqlite_fts5",
            "quarantined_rows": quarantined_count,
            "runtime_memory_core": "r47_confirmed_product_adapter",
            "runtime_core_sha256": EXPECTED["r47_open_domain_memory_store_frozen.py"],
            "r52_runtime_loaded": False,
            "provider_calls": 0,
            "private_data_uploaded": False,
            "last_sync": dict(self.last_sync),
            "current_rows": active_count,
        }

