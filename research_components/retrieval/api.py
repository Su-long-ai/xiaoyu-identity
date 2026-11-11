# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

CONTEXT_CAP = 20

class ComponentContractError(RuntimeError):
    pass

def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def authorized_documents(bridge, batch_size: int = 64) -> list[dict]:
    """Materialize every active ProductMemoryBridge memory that still passes authority.

    Research components receive only this list. They cannot create authority or
    reach quarantined/inactive memories through the fast-lane API.
    """
    bridge.sync()
    rows = bridge.identity_store.conn.execute(
        """SELECT m.memory_id,m.category,m.text,m.priority,m.status,m.source_event,e.extra
           FROM memories m
           LEFT JOIN events e ON e.event_id=m.source_event
           WHERE m.status='active'
           ORDER BY m.memory_id"""
    ).fetchall()
    out = []
    seen = set()
    for p in range(0, len(rows), batch_size):
        batch = rows[p:p+batch_size]
        authoritative = {
            int(r["memory_id"]): {
                "memory_id": int(r["memory_id"]),
                "category": str(r["category"]),
                "text": str(r["text"]),
                "priority": int(r["priority"] or 3),
                "status": str(r["status"]),
            }
            for r in batch
        }
        auth = bridge._r47_authority_batch(list(authoritative), authoritative)
        for r in batch:
            mid = int(r["memory_id"])
            allowed, _reason = auth.get(mid, (False, "authority_missing"))
            if not allowed:
                continue
            key = (str(r["category"]), str(r["text"]))
            if key in seen:
                continue
            seen.add(key)
            extra = {}
            try:
                extra = json.loads(r["extra"] or "{}")
            except Exception:
                pass
            out.append({
                "id": f"memory:{mid}",
                "memory_id": mid,
                "category": key[0],
                "text": key[1],
                "priority": int(r["priority"] or 3),
                "source_event": int(r["source_event"]) if r["source_event"] is not None else None,
                "speaker": str(extra.get("speaker") or ""),
                "session": str(extra.get("locomo_session") or extra.get("session") or ""),
                "timestamp": extra.get("chat_time"),
                "source_key": str(extra.get("source_key") or ""),
                "authority": "user_state",
            })
    return out

def enrich_bridge_hits(bridge, hits: list[dict]) -> list[dict]:
    """Convert ProductMemoryBridge recall rows into the same fast-lane document shape."""
    out = []
    for hit in hits:
        mid = int(hit["memory_id"])
        row = bridge.identity_store.conn.execute(
            """SELECT m.memory_id,m.category,m.text,m.priority,m.source_event,e.extra
               FROM memories m LEFT JOIN events e ON e.event_id=m.source_event
               WHERE m.memory_id=?""",
            (mid,),
        ).fetchone()
        if row is None:
            continue
        extra = {}
        try:
            extra = json.loads(row["extra"] or "{}")
        except Exception:
            pass
        out.append({
            "id": f"memory:{mid}",
            "memory_id": mid,
            "category": str(row["category"]),
            "text": str(row["text"]),
            "priority": int(row["priority"] or 3),
            "source_event": int(row["source_event"]) if row["source_event"] is not None else None,
            "speaker": str(extra.get("speaker") or ""),
            "session": str(extra.get("locomo_session") or extra.get("session") or ""),
            "timestamp": extra.get("chat_time"),
            "source_key": str(extra.get("source_key") or ""),
            "authority": str(hit.get("authority") or "user_state"),
            "retrieval": str(hit.get("retrieval") or "current_product"),
        })
    return out

def _module_from_path(path: Path):
    path = path.resolve()
    spec = importlib.util.spec_from_file_location(
        "_xiaoyu_fast_retrieval_" + hashlib.sha256(str(path).encode()).hexdigest()[:16],
        path,
    )
    if spec is None or spec.loader is None:
        raise ComponentContractError(f"cannot load component: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_component(spec: str):
    """Load a retrieval component.

    Builtins:
      hybrid
      multifacet

    Arbitrary research component:
      D:\path\candidate.py

    The module must expose create_component().
    """
    raw = str(spec).strip()
    aliases = {
        "hybrid": "research_components.retrieval.components.hybrid_bge_bm25_rrf",
        "multifacet": "research_components.retrieval.components.multifacet_bge",
    }
    if raw in aliases:
        module = importlib.import_module(aliases[raw])
    else:
        p = Path(raw)
        if not p.is_file():
            raise ComponentContractError(f"unknown component or missing file: {raw}")
        module = _module_from_path(p)
    factory = getattr(module, "create_component", None)
    if not callable(factory):
        raise ComponentContractError("component module must expose create_component()")
    component = factory()
    for method in ("prepare", "rank"):
        if not callable(getattr(component, method, None)):
            raise ComponentContractError(f"component missing {method}()")
    cid = str(getattr(component, "component_id", "")).strip()
    if not cid:
        raise ComponentContractError("component must expose nonempty component_id")
    return component, Path(module.__file__).resolve()

def prepare_component(component, documents: list[dict]):
    ids = [str(d.get("id") or "") for d in documents]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ComponentContractError("authorized document IDs must be unique and nonempty")
    state = component.prepare([dict(d) for d in documents])
    return state

def authorized_document_index(documents: list[dict]) -> dict[str, dict]:
    by_id = {}
    for d in documents:
        did = str(d.get("id") or "")
        if not did or did in by_id:
            raise ComponentContractError("authorized document IDs must be unique and nonempty")
        by_id[did] = d
    return by_id

def rank_component(component, state, documents: list[dict], query: str, limit: int = CONTEXT_CAP, metadata: dict | None = None, authorized_index: dict[str, dict] | None = None) -> list[dict]:
    cap = max(1, min(CONTEXT_CAP, int(limit)))
    ranked = component.rank(str(query), state=state, limit=cap, metadata=dict(metadata or {}))
    if not isinstance(ranked, list):
        raise ComponentContractError("rank() must return a list")
    by_id = authorized_index if authorized_index is not None else authorized_document_index(documents)
    out = []
    seen = set()
    for item in ranked:
        if isinstance(item, dict):
            did = str(item.get("id") or "")
        else:
            did = str(item)
        if did not in by_id:
            raise ComponentContractError(f"component returned unauthorized document id: {did}")
        if did in seen:
            continue
        seen.add(did)
        d = dict(by_id[did])
        d["retrieval"] = str(getattr(component, "component_id"))
        out.append(d)
        if len(out) >= cap:
            break
    return out

def component_fingerprint(component_path: str | Path, component_id: str) -> dict:
    p = Path(component_path).resolve()
    return {
        "component_id": str(component_id),
        "path": str(p),
        "sha256": sha256_file(p),
    }
