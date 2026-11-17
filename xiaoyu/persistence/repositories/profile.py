from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts.common import canonical_json, datetime_to_text


class ProfileRepository:
    def current_scope_facts(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        subject: str,
    ):
        return conn.execute(
            """SELECT tf.*,far.current_revision AS authority_revision,
                      far.erasure_generation AS authority_erasure_generation
               FROM temporal_facts tf
               JOIN fact_authority_revisions far
                 ON far.identity_id=tf.identity_id
                AND far.fact_key=tf.fact_key
               WHERE tf.identity_id=?
                 AND tf.principal_scope=?
                 AND tf.context_space=?
                 AND tf.subject=?
                 AND tf.status='CURRENT'
               ORDER BY tf.predicate,tf.cardinality,tf.fact_key,
                        tf.revision,tf.fact_id""",
            (identity_id, principal_scope, context_space, subject),
        ).fetchall()

    def scope_freshness(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        subject: str,
    ) -> tuple[int, int]:
        row = conn.execute(
            """SELECT COALESCE(MAX(far.current_revision),0) AS source_revision,
                      COALESCE(MAX(far.erasure_generation),0) AS erasure_generation
               FROM temporal_facts tf
               JOIN fact_authority_revisions far
                 ON far.identity_id=tf.identity_id
                AND far.fact_key=tf.fact_key
               WHERE tf.identity_id=?
                 AND tf.principal_scope=?
                 AND tf.context_space=?
                 AND tf.subject=?""",
            (identity_id, principal_scope, context_space, subject),
        ).fetchone()
        return int(row["source_revision"]), int(row["erasure_generation"])

    def upsert(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        projection_key: str,
        value: dict,
        source_fact_ids: list[str],
        builder_version: str,
        source_revision: int,
        erasure_generation: int,
        built_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO projections(
                   identity_id,projection_key,projection_type,value_json,
                   source_fact_ids_json,builder_version,built_at,
                   source_revision,erasure_generation
               ) VALUES(?,?,'PROFILE',?,?,?,?,?,?)
               ON CONFLICT(identity_id,projection_key,projection_type)
               DO UPDATE SET
                   value_json=excluded.value_json,
                   source_fact_ids_json=excluded.source_fact_ids_json,
                   builder_version=excluded.builder_version,
                   built_at=excluded.built_at,
                   source_revision=excluded.source_revision,
                   erasure_generation=excluded.erasure_generation""",
            (
                identity_id,
                projection_key,
                canonical_json(value),
                canonical_json(source_fact_ids),
                builder_version,
                datetime_to_text(built_at, "built_at"),
                source_revision,
                erasure_generation,
            ),
        )

    def get(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        projection_key: str,
    ) -> Optional[dict]:
        row = conn.execute(
            """SELECT * FROM projections
               WHERE identity_id=? AND projection_key=?
                 AND projection_type='PROFILE'""",
            (identity_id, projection_key),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["value"] = json.loads(result.pop("value_json"))
        result["source_fact_ids"] = json.loads(
            result.pop("source_fact_ids_json")
        )
        return result
