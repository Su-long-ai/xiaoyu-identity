from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Optional

from xiaoyu.contracts.common import canonical_json
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.profile import ProfileRepository


class ProfileProjectionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfileProjection:
    identity_id: str
    principal_scope: str
    context_space: str
    subject: str
    fields: dict[str, Any]
    source_fact_ids: tuple[str, ...]
    source_revision: int
    erasure_generation: int
    builder_version: str


class ProfileService:
    BUILDER_VERSION = "r10.profile.v1"

    def __init__(self, db: Database, repository=None) -> None:
        self.db = db
        self.repository = repository or ProfileRepository()

    @staticmethod
    def projection_key(
        identity_id: str,
        principal_scope: str,
        context_space: str,
        subject: str,
    ) -> str:
        payload = {
            "identity_id": identity_id,
            "principal_scope": principal_scope,
            "context_space": context_space,
            "subject": subject,
        }
        digest = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return "profile:" + digest[:32]

    @staticmethod
    def _materialize(rows) -> tuple[dict[str, Any], list[str]]:
        grouped: dict[str, list] = {}
        for row in rows:
            grouped.setdefault(str(row["predicate"]), []).append(row)

        fields: dict[str, Any] = {}
        source_ids: list[str] = []
        for predicate in sorted(grouped):
            items = grouped[predicate]
            cardinalities = {str(row["cardinality"]) for row in items}
            if len(cardinalities) != 1:
                raise ProfileProjectionConflict(
                    "predicate %s mixes SINGLE and SET facts" % predicate
                )
            cardinality = next(iter(cardinalities))
            source_ids.extend(str(row["fact_id"]) for row in items)
            if cardinality == "SINGLE":
                if len(items) != 1:
                    raise ProfileProjectionConflict(
                        "predicate %s has multiple current SINGLE facts"
                        % predicate
                    )
                fields[predicate] = json.loads(items[0]["value_json"])
            elif cardinality == "SET":
                values = [json.loads(row["value_json"]) for row in items]
                values.sort(key=canonical_json)
                fields[predicate] = values
            else:
                raise ProfileProjectionConflict(
                    "unknown fact cardinality %s" % cardinality
                )
        source_ids.sort()
        return fields, source_ids

    def rebuild(
        self,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        subject: Optional[str] = None,
        built_at: Optional[datetime] = None,
    ) -> ProfileProjection:
        actual_subject = subject or principal_scope
        at = built_at or datetime.now(timezone.utc)
        key = self.projection_key(
            identity_id,
            principal_scope,
            context_space,
            actual_subject,
        )
        with self.db.transaction(immediate=True) as conn:
            rows = self.repository.current_scope_facts(
                conn,
                identity_id=identity_id,
                principal_scope=principal_scope,
                context_space=context_space,
                subject=actual_subject,
            )
            source_revision, erasure_generation = (
                self.repository.scope_freshness(
                    conn,
                    identity_id=identity_id,
                    principal_scope=principal_scope,
                    context_space=context_space,
                    subject=actual_subject,
                )
            )
            fields, source_ids = self._materialize(rows)
            value = {
                "principal_scope": principal_scope,
                "context_space": context_space,
                "subject": actual_subject,
                "fields": fields,
            }
            self.repository.upsert(
                conn,
                identity_id=identity_id,
                projection_key=key,
                value=value,
                source_fact_ids=source_ids,
                builder_version=self.BUILDER_VERSION,
                source_revision=source_revision,
                erasure_generation=erasure_generation,
                built_at=at,
            )
        return ProfileProjection(
            identity_id=identity_id,
            principal_scope=principal_scope,
            context_space=context_space,
            subject=actual_subject,
            fields=fields,
            source_fact_ids=tuple(source_ids),
            source_revision=source_revision,
            erasure_generation=erasure_generation,
            builder_version=self.BUILDER_VERSION,
        )

    def read_fresh(
        self,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        subject: Optional[str] = None,
    ) -> Optional[ProfileProjection]:
        actual_subject = subject or principal_scope
        key = self.projection_key(
            identity_id,
            principal_scope,
            context_space,
            actual_subject,
        )
        with self.db.transaction() as conn:
            row = self.repository.get(
                conn,
                identity_id=identity_id,
                projection_key=key,
            )
            if row is None:
                return None
            current_revision, current_erasure = (
                self.repository.scope_freshness(
                    conn,
                    identity_id=identity_id,
                    principal_scope=principal_scope,
                    context_space=context_space,
                    subject=actual_subject,
                )
            )
            if (
                row["builder_version"] != self.BUILDER_VERSION
                or int(row["source_revision"]) != current_revision
                or int(row["erasure_generation"]) != current_erasure
            ):
                return None
            value = row["value"]
            return ProfileProjection(
                identity_id=identity_id,
                principal_scope=principal_scope,
                context_space=context_space,
                subject=actual_subject,
                fields=dict(value["fields"]),
                source_fact_ids=tuple(row["source_fact_ids"]),
                source_revision=current_revision,
                erasure_generation=current_erasure,
                builder_version=self.BUILDER_VERSION,
            )

    def rebuild_all(
        self,
        *,
        identity_id: str,
        built_at: Optional[datetime] = None,
    ) -> list[ProfileProjection]:
        with self.db.transaction() as conn:
            scopes = conn.execute(
                """SELECT DISTINCT principal_scope,context_space,subject
                   FROM temporal_facts
                   WHERE identity_id=? AND principal_scope IS NOT NULL
                     AND context_space IS NOT NULL
                   ORDER BY principal_scope,context_space,subject""",
                (identity_id,),
            ).fetchall()
        return [
            self.rebuild(
                identity_id=identity_id,
                principal_scope=str(row["principal_scope"]),
                context_space=str(row["context_space"]),
                subject=str(row["subject"]),
                built_at=built_at,
            )
            for row in scopes
        ]
