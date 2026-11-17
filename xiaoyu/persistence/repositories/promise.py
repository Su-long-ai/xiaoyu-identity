from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts.common import canonical_json, datetime_to_text


class PromiseRepository:
    def insert_candidate(
        self,
        conn: sqlite3.Connection,
        *,
        candidate_id: str,
        identity_id: str,
        source_event_id: str,
        source_ingest_revision: int,
        speaker_actor: str,
        commitment_text: str,
        due_window: Optional[dict],
        explicit_commitment: bool,
        created_at: datetime,
    ) -> None:
        stamp = datetime_to_text(created_at, "created_at")
        conn.execute(
            """INSERT INTO promise_candidates(
                   candidate_id,identity_id,source_event_id,
                   source_ingest_revision,speaker_actor,commitment_text,
                   due_window_json,explicit_commitment,state,
                   promoted_promise_id,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,'CANDIDATE',NULL,?,?)""",
            (
                candidate_id,
                identity_id,
                source_event_id,
                source_ingest_revision,
                speaker_actor,
                commitment_text,
                None if due_window is None else canonical_json(due_window),
                1 if explicit_commitment else 0,
                stamp,
                stamp,
            ),
        )

    def get_candidate(
        self,
        conn: sqlite3.Connection,
        candidate_id: str,
    ) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM promise_candidates WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["due_window"] = (
            None
            if result["due_window_json"] is None
            else json.loads(result["due_window_json"])
        )
        return result

    def promote_candidate(
        self,
        conn: sqlite3.Connection,
        *,
        candidate_id: str,
        promise_id: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            """UPDATE promise_candidates
               SET state='PROMOTED',promoted_promise_id=?,updated_at=?
               WHERE candidate_id=? AND state='CANDIDATE'""",
            (
                promise_id,
                datetime_to_text(updated_at, "updated_at"),
                candidate_id,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("promise candidate is not promotable")

    def insert_promise(
        self,
        conn: sqlite3.Connection,
        *,
        promise_id: str,
        candidate: dict,
        created_at: datetime,
    ) -> None:
        stamp = datetime_to_text(created_at, "created_at")
        conn.execute(
            """INSERT INTO promises(
                   promise_id,identity_id,speaker_actor,source_event_id,
                   commitment_text,due_window_json,state,linked_purpose_id,
                   created_at,updated_at,candidate_id,revision,
                   source_ingest_revision,last_transition_id
               ) VALUES(?,?,?,?,?,?,'OPEN',NULL,?,?,?,?,?,NULL)""",
            (
                promise_id,
                candidate["identity_id"],
                candidate["speaker_actor"],
                candidate["source_event_id"],
                candidate["commitment_text"],
                candidate["due_window_json"],
                stamp,
                stamp,
                candidate["candidate_id"],
                1,
                int(candidate["source_ingest_revision"]),
            ),
        )

    def get_promise(
        self,
        conn: sqlite3.Connection,
        promise_id: str,
    ) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM promises WHERE promise_id=?",
            (promise_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["due_window"] = (
            None
            if result["due_window_json"] is None
            else json.loads(result["due_window_json"])
        )
        return result

    def append_transition(
        self,
        conn: sqlite3.Connection,
        *,
        transition_id: str,
        promise_id: str,
        identity_id: str,
        operation: str,
        from_state: Optional[str],
        to_state: Optional[str],
        linked_purpose_id: Optional[str],
        source_event_id: str,
        source_ingest_revision: int,
        created_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO promise_transitions(
                   transition_id,promise_id,identity_id,operation,
                   from_state,to_state,linked_purpose_id,source_event_id,
                   source_ingest_revision,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                transition_id,
                promise_id,
                identity_id,
                operation,
                from_state,
                to_state,
                linked_purpose_id,
                source_event_id,
                source_ingest_revision,
                datetime_to_text(created_at, "created_at"),
            ),
        )

    def list_transitions(
        self,
        conn: sqlite3.Connection,
        *,
        promise_id: str,
    ):
        return conn.execute(
            """SELECT * FROM promise_transitions
               WHERE promise_id=? ORDER BY transition_sequence""",
            (promise_id,),
        ).fetchall()

    def update_state(
        self,
        conn: sqlite3.Connection,
        *,
        promise_id: str,
        expected_state: str,
        to_state: str,
        transition_id: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            """UPDATE promises
               SET state=?,revision=revision+1,last_transition_id=?,updated_at=?
               WHERE promise_id=? AND state=?""",
            (
                to_state,
                transition_id,
                datetime_to_text(updated_at, "updated_at"),
                promise_id,
                expected_state,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("promise state changed concurrently")

    def update_link(
        self,
        conn: sqlite3.Connection,
        *,
        promise_id: str,
        linked_purpose_id: str,
        transition_id: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            """UPDATE promises
               SET linked_purpose_id=?,revision=revision+1,
                   last_transition_id=?,updated_at=?
               WHERE promise_id=? AND state IN ('OPEN','WAITING')""",
            (
                linked_purpose_id,
                transition_id,
                datetime_to_text(updated_at, "updated_at"),
                promise_id,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("promise cannot link purpose in current state")

    def overwrite_rebuilt(
        self,
        conn: sqlite3.Connection,
        *,
        promise_id: str,
        state: str,
        linked_purpose_id: Optional[str],
        revision: int,
        last_transition_id: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            """UPDATE promises
               SET state=?,linked_purpose_id=?,revision=?,
                   last_transition_id=?,updated_at=?
               WHERE promise_id=?""",
            (
                state,
                linked_purpose_id,
                revision,
                last_transition_id,
                datetime_to_text(updated_at, "updated_at"),
                promise_id,
            ),
        )
        if cur.rowcount != 1:
            raise KeyError("unknown promise %s" % promise_id)
