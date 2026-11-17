from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Optional

from xiaoyu.contracts.common import canonical_json, datetime_to_text
from xiaoyu.core.events import CanonicalEvent


class ClaimRepository:
    def insert(
        self,
        conn: sqlite3.Connection,
        *,
        claim_id: str,
        event: CanonicalEvent,
        subject: str,
        predicate: str,
        value: Any,
        confidence: float,
        status: str,
        created_at: datetime,
        mutation_id: Optional[str] = None,
        principal_scope: Optional[str] = None,
        decision_reason: Optional[str] = None,
    ) -> None:
        conn.execute(
            """INSERT INTO claims(
                   claim_id,identity_id,subject,predicate,object_json,
                   trust_class,confidence,status,created_at,mutation_id,
                   principal_scope,context_space,audience_scope,taint_json,
                   eligible_for_memory,decision_reason
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                claim_id,
                event.identity_id,
                subject,
                predicate,
                canonical_json(value),
                event.trust_class.value,
                float(confidence),
                status,
                datetime_to_text(created_at, "created_at"),
                mutation_id,
                principal_scope or event.principal_id,
                event.context_space,
                event.audience_scope,
                canonical_json([value.value for value in event.taint]),
                1 if event.eligible_for_memory else 0,
                decision_reason,
            ),
        )
        conn.execute(
            "INSERT INTO claim_sources(claim_id,event_id) VALUES(?,?)",
            (claim_id, event.event_id),
        )

    def get_mutation_claim(
        self,
        conn: sqlite3.Connection,
        mutation_id: str,
    ):
        return conn.execute(
            "SELECT * FROM claims WHERE mutation_id=?",
            (mutation_id,),
        ).fetchone()
