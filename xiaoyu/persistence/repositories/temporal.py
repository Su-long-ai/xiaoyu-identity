from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from xiaoyu.contracts.common import (
    canonical_json,
    datetime_from_text,
    datetime_to_text,
)


class TemporalRepository:
    def revision_state(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        fact_key: str,
    ) -> dict:
        row = conn.execute(
            """SELECT current_revision,last_source_ingest_revision,
                      erasure_generation
               FROM fact_authority_revisions
               WHERE identity_id=? AND fact_key=?""",
            (identity_id, fact_key),
        ).fetchone()
        if row is None:
            return {
                "current_revision": 0,
                "last_source_ingest_revision": 0,
                "erasure_generation": 0,
            }
        return {
            "current_revision": int(row["current_revision"]),
            "last_source_ingest_revision": int(
                row["last_source_ingest_revision"]
            ),
            "erasure_generation": int(row["erasure_generation"]),
        }

    def mutation_by_id(
        self,
        conn: sqlite3.Connection,
        mutation_id: str,
    ):
        return conn.execute(
            "SELECT * FROM fact_mutations WHERE mutation_id=?",
            (mutation_id,),
        ).fetchone()

    def current_facts(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        fact_key: str,
    ):
        return conn.execute(
            """SELECT * FROM temporal_facts
               WHERE identity_id=? AND fact_key=? AND status='CURRENT'
               ORDER BY revision,fact_id""",
            (identity_id, fact_key),
        ).fetchall()

    def current_fact_by_value(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        fact_key: str,
        value: Any,
    ):
        encoded = canonical_json(value)
        return conn.execute(
            """SELECT * FROM temporal_facts
               WHERE identity_id=? AND fact_key=? AND status='CURRENT'
                 AND value_json=?
               ORDER BY revision DESC LIMIT 1""",
            (identity_id, fact_key, encoded),
        ).fetchone()

    def insert_fact(
        self,
        conn: sqlite3.Connection,
        *,
        fact_id: str,
        identity_id: str,
        claim_id: str,
        fact_key: str,
        principal_scope: str,
        context_space: str,
        cardinality: str,
        subject: str,
        predicate: str,
        value: Any,
        valid_from: datetime,
        valid_to: Optional[datetime],
        recorded_at: datetime,
        revision: int,
        mutation_id: str,
        supersedes_fact_id: Optional[str] = None,
    ) -> None:
        conn.execute(
            """INSERT INTO temporal_facts(
                   fact_id,identity_id,claim_id,subject,predicate,value_json,
                   valid_from,valid_to,recorded_at,status,supersedes_fact_id,
                   fact_key,principal_scope,context_space,cardinality,revision,
                   mutation_id
               ) VALUES(?,?,?,?,?,?,?,?,?,'CURRENT',?,?,?,?,?,?,?)""",
            (
                fact_id,
                identity_id,
                claim_id,
                subject,
                predicate,
                canonical_json(value),
                datetime_to_text(valid_from.astimezone(timezone.utc), "valid_from"),
                None
                if valid_to is None
                else datetime_to_text(valid_to.astimezone(timezone.utc), "valid_to"),
                datetime_to_text(recorded_at, "recorded_at"),
                supersedes_fact_id,
                fact_key,
                principal_scope,
                context_space,
                cardinality,
                revision,
                mutation_id,
            ),
        )

    def set_fact_state(
        self,
        conn: sqlite3.Connection,
        fact_id: str,
        status: str,
        *,
        valid_to: Optional[datetime] = None,
    ) -> None:
        if valid_to is None:
            cur = conn.execute(
                "UPDATE temporal_facts SET status=? WHERE fact_id=?",
                (status, fact_id),
            )
        else:
            cur = conn.execute(
                """UPDATE temporal_facts
                   SET status=?,valid_to=? WHERE fact_id=?""",
                (
                    status,
                    datetime_to_text(valid_to.astimezone(timezone.utc), "valid_to"),
                    fact_id,
                ),
            )
        if cur.rowcount != 1:
            raise KeyError("unknown fact_id %s" % fact_id)

    def set_all_fact_state(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        fact_key: str,
        status: str,
    ) -> int:
        cur = conn.execute(
            """UPDATE temporal_facts SET status=?
               WHERE identity_id=? AND fact_key=? AND status!='DELETED'""",
            (status, identity_id, fact_key),
        )
        return int(cur.rowcount)

    def update_revision(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        fact_key: str,
        revision: int,
        source_ingest_revision: int,
        erasure_generation: int,
        updated_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO fact_authority_revisions(
                   identity_id,fact_key,current_revision,
                   last_source_ingest_revision,erasure_generation,updated_at
               ) VALUES(?,?,?,?,?,?)
               ON CONFLICT(identity_id,fact_key) DO UPDATE SET
                   current_revision=excluded.current_revision,
                   last_source_ingest_revision=excluded.last_source_ingest_revision,
                   erasure_generation=excluded.erasure_generation,
                   updated_at=excluded.updated_at""",
            (
                identity_id,
                fact_key,
                revision,
                source_ingest_revision,
                erasure_generation,
                datetime_to_text(updated_at, "updated_at"),
            ),
        )

    def record_mutation(
        self,
        conn: sqlite3.Connection,
        *,
        mutation_id: str,
        identity_id: str,
        source_event_id: str,
        source_ingest_revision: int,
        claim_id: Optional[str],
        fact_key: str,
        operation: str,
        mutation_digest: str,
        expected_revision: int,
        result_revision: int,
        request_json: str,
        created_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO fact_mutations(
                   mutation_id,identity_id,source_event_id,
                   source_ingest_revision,claim_id,fact_key,operation,
                   mutation_digest,expected_revision,result_revision,
                   request_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mutation_id,
                identity_id,
                source_event_id,
                source_ingest_revision,
                claim_id,
                fact_key,
                operation,
                mutation_digest,
                expected_revision,
                result_revision,
                request_json,
                datetime_to_text(created_at, "created_at"),
            ),
        )
        conn.execute(
            "INSERT INTO fact_mutation_order(mutation_id) VALUES(?)",
            (mutation_id,),
        )

    def ordered_mutations(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT fm.*,fmo.mutation_sequence
               FROM fact_mutations fm
               JOIN fact_mutation_order fmo
                 ON fmo.mutation_id=fm.mutation_id
               WHERE fm.identity_id=?
               ORDER BY fmo.mutation_sequence""",
            (identity_id,),
        ).fetchall()

    def latest_erasure_fence(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        fact_key: str,
    ):
        return conn.execute(
            """SELECT * FROM erasure_tombstones
               WHERE identity_id=? AND target_type='fact_key' AND target_id=?
               ORDER BY erasure_generation DESC LIMIT 1""",
            (identity_id, fact_key),
        ).fetchone()

    def next_erasure_generation(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ) -> int:
        row = conn.execute(
            """SELECT COALESCE(MAX(erasure_generation),0)
               FROM erasure_tombstones WHERE identity_id=?""",
            (identity_id,),
        ).fetchone()
        return int(row[0]) + 1

    def insert_erasure_fence(
        self,
        conn: sqlite3.Connection,
        *,
        erasure_id: str,
        identity_id: str,
        fact_key: str,
        generation: int,
        source_event_id: str,
        source_ingest_revision: int,
        mutation_id: str,
        created_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(created_at, "created_at")
        conn.execute(
            """INSERT INTO erasure_tombstones(
                   erasure_id,identity_id,target_type,target_id,
                   erasure_generation,requested_at,applied_at,source_event_id,
                   source_ingest_revision,mutation_id
               ) VALUES(?,?,'fact_key',?,?,?,?,?,?,?)""",
            (
                erasure_id,
                identity_id,
                fact_key,
                generation,
                timestamp,
                timestamp,
                source_event_id,
                source_ingest_revision,
                mutation_id,
            ),
        )

    def invalidate_projection(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        fact_key: str,
        revision: int,
        erasure_generation: int,
        mutation_id: str,
        invalidated_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO projection_invalidations(
                   identity_id,fact_key,source_revision,erasure_generation,
                   mutation_id,invalidated_at
               ) VALUES(?,?,?,?,?,?)""",
            (
                identity_id,
                fact_key,
                revision,
                erasure_generation,
                mutation_id,
                datetime_to_text(
                    invalidated_at, "invalidated_at"
                ),
            ),
        )

    def facts_at(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        fact_key: str,
        at: datetime,
    ):
        at_text = datetime_to_text(at.astimezone(timezone.utc), "at")
        return conn.execute(
            """SELECT * FROM temporal_facts
               WHERE identity_id=? AND fact_key=?
                 AND status IN ('CURRENT','HISTORICAL','RETRACTED')
                 AND valid_from<=?
                 AND (valid_to IS NULL OR valid_to>?)
               ORDER BY revision DESC,fact_id""",
            (identity_id, fact_key, at_text, at_text),
        ).fetchall()
