from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts.common import canonical_json, datetime_to_text


DEFAULT_PRESENTATION = {
    "mood": 80,
    "hunger": 20,
    "energy": 90,
    "bond": 0,
}


class PresentationStateRepository:
    """Explicitly non-authoritative durable presentation state."""

    @staticmethod
    def _clean(value: dict) -> dict:
        result = {}
        for key, default in DEFAULT_PRESENTATION.items():
            raw = value.get(key, default)
            number = int(raw)
            result[key] = max(0, min(100, number))
        return result

    def initialize(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        state: dict,
        updated_at: datetime,
    ) -> dict:
        clean = self._clean(state)
        conn.execute(
            """INSERT INTO presentation_state(
                   identity_id,mood,hunger,energy,bond,updated_at
               ) VALUES(?,?,?,?,?,?)
               ON CONFLICT(identity_id) DO NOTHING""",
            (
                identity_id,
                clean["mood"],
                clean["hunger"],
                clean["energy"],
                clean["bond"],
                datetime_to_text(updated_at, "updated_at"),
            ),
        )
        return self.get(conn, identity_id)

    def get(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ) -> Optional[dict]:
        row = conn.execute(
            """SELECT mood,hunger,energy,bond,updated_at
               FROM presentation_state
               WHERE identity_id=?""",
            (identity_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "mood": int(row["mood"]),
            "hunger": int(row["hunger"]),
            "energy": int(row["energy"]),
            "bond": int(row["bond"]),
            "updated_at": str(row["updated_at"]),
        }

    def update(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        state: dict,
        updated_at: datetime,
    ) -> dict:
        current = self.get(conn, identity_id)
        base = dict(DEFAULT_PRESENTATION)
        if current is not None:
            base.update(
                {
                    key: current[key]
                    for key in DEFAULT_PRESENTATION
                }
            )
        base.update(
            {
                key: value
                for key, value in state.items()
                if key in DEFAULT_PRESENTATION
            }
        )
        clean = self._clean(base)
        conn.execute(
            """INSERT INTO presentation_state(
                   identity_id,mood,hunger,energy,bond,updated_at
               ) VALUES(?,?,?,?,?,?)
               ON CONFLICT(identity_id) DO UPDATE SET
                   mood=excluded.mood,
                   hunger=excluded.hunger,
                   energy=excluded.energy,
                   bond=excluded.bond,
                   updated_at=excluded.updated_at""",
            (
                identity_id,
                clean["mood"],
                clean["hunger"],
                clean["energy"],
                clean["bond"],
                datetime_to_text(updated_at, "updated_at"),
            ),
        )
        return self.get(conn, identity_id)


class MemoryProposalDecisionRepository:
    def insert_pending(
        self,
        conn: sqlite3.Connection,
        *,
        claim_id: str,
        identity_id: str,
        created_at: datetime,
    ) -> None:
        stamp = datetime_to_text(created_at, "created_at")
        conn.execute(
            """INSERT INTO memory_proposal_decisions(
                   claim_id,identity_id,state,memory_id,
                   decision_event_id,created_at,updated_at
               ) VALUES(?,?,'PENDING',NULL,NULL,?,?)""",
            (claim_id, identity_id, stamp, stamp),
        )

    def get(
        self,
        conn: sqlite3.Connection,
        claim_id: str,
    ) -> Optional[dict]:
        row = conn.execute(
            """SELECT mpd.*,c.object_json,c.subject,c.predicate,
                      c.status AS claim_status,
                      cs.event_id AS source_event_id
               FROM memory_proposal_decisions mpd
               JOIN claims c ON c.claim_id=mpd.claim_id
               JOIN claim_sources cs ON cs.claim_id=c.claim_id
               WHERE mpd.claim_id=?""",
            (claim_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["value"] = json.loads(
            str(result.pop("object_json"))
        )
        return result

    def decide(
        self,
        conn: sqlite3.Connection,
        *,
        claim_id: str,
        expected_state: str,
        state: str,
        memory_id: Optional[str],
        decision_event_id: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            """UPDATE memory_proposal_decisions
               SET state=?,memory_id=?,decision_event_id=?,updated_at=?
               WHERE claim_id=? AND state=?""",
            (
                state,
                memory_id,
                decision_event_id,
                datetime_to_text(updated_at, "updated_at"),
                claim_id,
                expected_state,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                "memory proposal state changed concurrently"
            )

    def list_state(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        state: str = "PENDING",
    ):
        return conn.execute(
            """SELECT mpd.claim_id,mpd.state,mpd.memory_id,
                      mpd.decision_event_id,mpd.created_at,mpd.updated_at,
                      c.object_json,c.confidence,cs.event_id AS source_event_id
               FROM memory_proposal_decisions mpd
               JOIN claims c ON c.claim_id=mpd.claim_id
               JOIN claim_sources cs ON cs.claim_id=c.claim_id
               WHERE mpd.identity_id=? AND mpd.state=?
               ORDER BY mpd.created_at,mpd.claim_id""",
            (identity_id, state),
        ).fetchall()
