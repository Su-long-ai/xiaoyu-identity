from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts.common import canonical_json, datetime_to_text


class RelationshipRepository:
    def get(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_id: str,
    ) -> Optional[dict]:
        row = conn.execute(
            """SELECT * FROM relationship_state
               WHERE identity_id=? AND principal_id=?""",
            (identity_id, principal_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["value"] = json.loads(result.pop("value_json"))
        result["source_fact_ids"] = json.loads(
            result.pop("source_fact_ids_json")
        )
        result["source_event_ids"] = json.loads(
            result.pop("source_event_ids_json")
        )
        return result

    def append_transition(
        self,
        conn: sqlite3.Connection,
        *,
        transition_id: str,
        identity_id: str,
        principal_id: str,
        from_state: str,
        to_state: str,
        source_event_id: str,
        source_ingest_revision: int,
        value_patch: dict,
        reason: str,
        created_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO relationship_transitions(
                   transition_id,identity_id,principal_id,from_state,to_state,
                   source_event_id,source_ingest_revision,value_patch_json,
                   reason,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                transition_id,
                identity_id,
                principal_id,
                from_state,
                to_state,
                source_event_id,
                source_ingest_revision,
                canonical_json(value_patch),
                reason,
                datetime_to_text(created_at, "created_at"),
            ),
        )

    def list_transitions(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_id: str,
    ):
        return conn.execute(
            """SELECT * FROM relationship_transitions
               WHERE identity_id=? AND principal_id=?
               ORDER BY transition_sequence""",
            (identity_id, principal_id),
        ).fetchall()

    def upsert_state(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_id: str,
        state: str,
        value: dict,
        source_event_ids: list[str],
        revision: int,
        builder_version: str,
        last_transition_id: str,
        effective_from: datetime,
        updated_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO relationship_state(
                   identity_id,principal_id,state,value_json,
                   source_fact_ids_json,effective_from,updated_at,
                   revision,builder_version,source_event_ids_json,
                   last_transition_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(identity_id,principal_id)
               DO UPDATE SET
                   state=excluded.state,
                   value_json=excluded.value_json,
                   source_fact_ids_json=excluded.source_fact_ids_json,
                   effective_from=excluded.effective_from,
                   updated_at=excluded.updated_at,
                   revision=excluded.revision,
                   builder_version=excluded.builder_version,
                   source_event_ids_json=excluded.source_event_ids_json,
                   last_transition_id=excluded.last_transition_id""",
            (
                identity_id,
                principal_id,
                state,
                canonical_json(value),
                "[]",
                datetime_to_text(effective_from, "effective_from"),
                datetime_to_text(updated_at, "updated_at"),
                revision,
                builder_version,
                canonical_json(source_event_ids),
                last_transition_id,
            ),
        )
