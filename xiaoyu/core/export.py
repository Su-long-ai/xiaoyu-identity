from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Protocol

from xiaoyu.contracts.common import canonical_json
from xiaoyu.persistence import (
    Database,
    ExternalErasureFenceStore,
    applied_versions,
    apply_migrations,
    verify_schema,
)


class PortableExportAdapter(Protocol):
    adapter_id: str

    def convert(self, native_bundle: Dict[str, Any]) -> Dict[str, Any]:
        ...


class NativeCanonicalExporter:
    FORMAT = "xiaoyu.native.identity.v1"

    def __init__(self, db: Database) -> None:
        self.db = db

    def build(self, *, identity_id: str) -> Dict[str, Any]:
        apply_migrations(self.db)
        verify_schema(self.db)
        fence = ExternalErasureFenceStore(self.db.path)
        fence_identity = fence.sync_from_db(self.db, identity_id)

        with self.db.transaction() as conn:
            data = {
                "canonical_events": self._rows(
                    conn,
                    """SELECT cei.ingest_revision,ce.*
                       FROM canonical_events ce
                       JOIN canonical_event_ingest cei ON cei.event_id=ce.event_id
                       WHERE ce.identity_id=?
                       ORDER BY cei.ingest_revision""",
                    (identity_id,),
                ),
                "claims": self._rows(
                    conn,
                    "SELECT * FROM claims WHERE identity_id=? ORDER BY claim_id",
                    (identity_id,),
                ),
                "claim_sources": self._rows(
                    conn,
                    """SELECT cs.*
                       FROM claim_sources cs
                       JOIN claims c ON c.claim_id=cs.claim_id
                       WHERE c.identity_id=?
                       ORDER BY cs.claim_id,cs.event_id""",
                    (identity_id,),
                ),
                "temporal_facts": self._rows(
                    conn,
                    """SELECT * FROM temporal_facts
                       WHERE identity_id=?
                       ORDER BY fact_key,revision,fact_id""",
                    (identity_id,),
                ),
                "fact_authority_revisions": self._rows(
                    conn,
                    """SELECT * FROM fact_authority_revisions
                       WHERE identity_id=? ORDER BY fact_key""",
                    (identity_id,),
                ),
                "fact_mutations": self._rows(
                    conn,
                    """SELECT fmo.mutation_sequence,fm.*
                       FROM fact_mutation_order fmo
                       JOIN fact_mutations fm ON fm.mutation_id=fmo.mutation_id
                       WHERE fm.identity_id=?
                       ORDER BY fmo.mutation_sequence""",
                    (identity_id,),
                ),
                "erasure_tombstones": self._rows(
                    conn,
                    """SELECT * FROM erasure_tombstones
                       WHERE identity_id=?
                       ORDER BY erasure_generation,target_type,target_id""",
                    (identity_id,),
                ),
                "self_identity": self._rows(
                    conn,
                    """SELECT * FROM self_identity
                       WHERE identity_id=?""",
                    (identity_id,),
                ),
                "self_persona_versions": self._rows(
                    conn,
                    """SELECT * FROM self_persona_versions
                       WHERE identity_id=? ORDER BY revision""",
                    (identity_id,),
                ),
                "relationship_transitions": self._rows(
                    conn,
                    """SELECT * FROM relationship_transitions
                       WHERE identity_id=?
                       ORDER BY transition_sequence""",
                    (identity_id,),
                ),
                "relationship_state": self._rows(
                    conn,
                    """SELECT * FROM relationship_state
                       WHERE identity_id=? ORDER BY principal_id""",
                    (identity_id,),
                ),
                "promise_candidates": self._rows(
                    conn,
                    """SELECT * FROM promise_candidates
                       WHERE identity_id=? ORDER BY created_at,candidate_id""",
                    (identity_id,),
                ),
                "promise_transitions": self._rows(
                    conn,
                    """SELECT * FROM promise_transitions
                       WHERE identity_id=?
                       ORDER BY transition_sequence""",
                    (identity_id,),
                ),
                "promises": self._rows(
                    conn,
                    """SELECT * FROM promises
                       WHERE identity_id=? ORDER BY promise_id""",
                    (identity_id,),
                ),
                "memory_proposal_decisions": self._rows(
                    conn,
                    """SELECT * FROM memory_proposal_decisions
                       WHERE identity_id=? ORDER BY created_at,claim_id""",
                    (identity_id,),
                ),
                "purposes": self._rows(
                    conn,
                    """SELECT * FROM purposes
                       WHERE identity_id=? ORDER BY purpose_id""",
                    (identity_id,),
                ),
                "activities": self._rows(
                    conn,
                    """SELECT * FROM activities
                       WHERE identity_id=? ORDER BY activity_id""",
                    (identity_id,),
                ),
                "authority_cutover_state": self._rows(
                    conn,
                    """SELECT * FROM authority_cutover_state
                       WHERE identity_id=?""",
                    (identity_id,),
                ),
            }

        versions = applied_versions(self.db)
        payload = {
            "format": self.FORMAT,
            "identity_id": identity_id,
            "schema_version": max(versions, default=0),
            "erasure_generation": int(fence_identity["erasure_generation"]),
            "external_erasure_fence": fence_identity,
            "data": data,
        }
        digest = "sha256:" + hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return {
            "bundle_digest": digest,
            **payload,
        }

    def write(self, path, *, identity_id: str) -> Path:
        bundle = self.build(identity_id=identity_id)
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            canonical_json(bundle) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return output

    @staticmethod
    def _rows(conn, sql: str, args=()):
        return [dict(row) for row in conn.execute(sql, args).fetchall()]


def adapt_native_export(
    native_bundle: Dict[str, Any],
    adapter: PortableExportAdapter,
) -> Dict[str, Any]:
    """Convert a native snapshot without granting the adapter authority.

    Adapters only receive an immutable-style serialized document and never a
    Database handle. Their output is portability material, not canonical Core
    state.
    """
    if str(native_bundle.get("format")) != NativeCanonicalExporter.FORMAT:
        raise ValueError("portable adapter requires a native XiaoYu export")
    converted = adapter.convert(json.loads(canonical_json(native_bundle)))
    if not isinstance(converted, dict):
        raise TypeError("portable adapter must return a JSON object")
    return {
        "format": "xiaoyu.portable.adapter.v1",
        "adapter_id": str(adapter.adapter_id),
        "source_bundle_digest": str(native_bundle["bundle_digest"]),
        "payload": converted,
    }
