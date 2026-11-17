from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Optional

from xiaoyu.contracts import TrustClass
from xiaoyu.contracts.common import datetime_from_text
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.events import (
    CanonicalEventRepository,
)
from xiaoyu.persistence.repositories.self_authority import (
    SelfAuthorityRepository,
)


class SelfAuthorityError(RuntimeError):
    pass


class PersonaRevisionConflict(SelfAuthorityError):
    pass


class PersonaEvidenceError(SelfAuthorityError):
    pass


PERSONA_FIELDS = (
    "name",
    "identity_commitments",
    "style",
    "growth_notes",
    "bond_description",
)


@dataclass(frozen=True)
class SelfIdentity:
    identity_id: str
    created_at: datetime
    persona_revision: int
    persona: dict
    persona_digest: str
    authority_digest: str
    source_event_ids: tuple[str, ...]


class SelfAuthorityService:
    """Canonical SELF authority: stable identity + slow persona history."""

    OWNER_TRUST = {
        TrustClass.OWNER_DIRECT,
        TrustClass.OWNER_AUTHENTICATED_DEVICE,
    }

    def __init__(
        self,
        db: Database,
        *,
        repository=None,
        event_repository=None,
    ) -> None:
        self.db = db
        self.repository = repository or SelfAuthorityRepository()
        self.event_repository = (
            event_repository or CanonicalEventRepository()
        )

    @staticmethod
    def normalize_persona(
        identity_id: str,
        persona: dict,
    ) -> dict:
        if not isinstance(persona, dict):
            raise TypeError("persona must be an object")
        embedded_id = persona.get("id")
        if (
            embedded_id is not None
            and str(embedded_id) != identity_id
        ):
            raise SelfAuthorityError(
                "persona cannot change identity_id"
            )
        result = {}
        for field in PERSONA_FIELDS:
            if field in persona:
                result[field] = persona[field]
        if not str(result.get("name") or "").strip():
            raise SelfAuthorityError("persona name is required")
        commitments = result.get("identity_commitments")
        if commitments is not None and not isinstance(
            commitments, list
        ):
            raise SelfAuthorityError(
                "identity_commitments must be a list"
            )
        style = result.get("style")
        if style is not None and not isinstance(style, dict):
            raise SelfAuthorityError("style must be an object")
        growth = result.get("growth_notes")
        if growth is not None and not isinstance(growth, list):
            raise SelfAuthorityError(
                "growth_notes must be a list"
            )
        return result

    def initialize(
        self,
        *,
        identity_id: str,
        persona: dict,
        created_at: datetime,
        reason: str,
        source_event_ids: tuple[str, ...] = (),
        legacy_persona_version: Optional[int] = None,
    ) -> SelfIdentity:
        normalized = self.normalize_persona(
            identity_id, persona
        )
        with self.db.transaction(immediate=True) as conn:
            self.repository.initialize(
                conn,
                identity_id=identity_id,
                created_at=created_at,
                persona=normalized,
                reason=reason,
                source_event_ids=list(source_event_ids),
                legacy_persona_version=legacy_persona_version,
            )
        return self.get(identity_id)

    def revise(
        self,
        *,
        identity_id: str,
        expected_revision: int,
        persona: dict,
        reason: str,
        source_event_ids: tuple[str, ...],
        principal_id: str,
        created_at: Optional[datetime] = None,
    ) -> SelfIdentity:
        if not source_event_ids:
            raise PersonaEvidenceError(
                "persona revision requires owner evidence"
            )
        normalized = self.normalize_persona(
            identity_id, persona
        )
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            identity = self.repository.get_identity(
                conn, identity_id
            )
            if identity is None:
                raise KeyError(
                    "unknown self identity %s" % identity_id
                )
            if int(identity["current_persona_revision"]) != int(
                expected_revision
            ):
                raise PersonaRevisionConflict(
                    "expected persona revision %d current %d"
                    % (
                        expected_revision,
                        int(identity["current_persona_revision"]),
                    )
                )
            for event_id in source_event_ids:
                event = self.event_repository.get(
                    conn, event_id
                )
                if event is None:
                    raise PersonaEvidenceError(
                        "unknown persona evidence event %s"
                        % event_id
                    )
                if event.identity_id != identity_id:
                    raise PersonaEvidenceError(
                        "persona evidence identity mismatch"
                    )
                if event.principal_id != principal_id:
                    raise PersonaEvidenceError(
                        "persona evidence principal mismatch"
                    )
                if event.trust_class not in self.OWNER_TRUST:
                    raise PersonaEvidenceError(
                        "persona evidence is not owner-authoritative"
                    )
            try:
                self.repository.append_persona(
                    conn,
                    identity_id=identity_id,
                    expected_revision=expected_revision,
                    persona=normalized,
                    reason=reason,
                    source_event_ids=list(source_event_ids),
                    created_at=at,
                )
            except RuntimeError as exc:
                if "revision conflict" in str(exc):
                    raise PersonaRevisionConflict(str(exc)) from exc
                raise
        return self.get(identity_id)

    def get(self, identity_id: str) -> SelfIdentity:
        with self.db.transaction() as conn:
            identity = self.repository.get_identity(
                conn, identity_id
            )
            if identity is None:
                raise KeyError(
                    "unknown self identity %s" % identity_id
                )
            persona = self.repository.current_persona(
                conn, identity_id
            )
            if persona is None:
                raise SelfAuthorityError(
                    "self identity has no current persona"
                )
            return SelfIdentity(
                identity_id=identity_id,
                created_at=datetime_from_text(
                    str(identity["created_at"]),
                    "created_at",
                ),
                persona_revision=int(
                    identity["current_persona_revision"]
                ),
                persona=self.repository.decode_persona(persona),
                persona_digest=str(persona["persona_digest"]),
                authority_digest=str(
                    identity["authority_digest"]
                ),
                source_event_ids=
                    self.repository.decode_sources(persona),
            )

    def identity_block(self, identity_id: str) -> dict:
        current = self.get(identity_id)
        return {
            "identity_id": current.identity_id,
            "persona_revision": current.persona_revision,
            "persona_digest": current.persona_digest,
            **current.persona,
        }


class LegacySelfBackfill:
    """One-way import of legacy persona history into canonical SELF."""

    def __init__(
        self,
        db: Database,
        *,
        service: Optional[SelfAuthorityService] = None,
    ) -> None:
        self.db = db
        self.service = service or SelfAuthorityService(db)

    @staticmethod
    def _legacy_persona(conn) -> dict:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='persona'"
        ).fetchone()
        if row is None:
            raise SelfAuthorityError(
                "legacy persona setting is missing"
            )
        value = json.loads(str(row[0]))
        if not isinstance(value, dict):
            raise SelfAuthorityError(
                "legacy persona setting is malformed"
            )
        return value

    @staticmethod
    def _canonical_evidence_ids(conn, raw) -> tuple[str, ...]:
        try:
            values = json.loads(str(raw or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        result = []
        for value in values if isinstance(values, list) else []:
            try:
                legacy_id = int(value)
            except (TypeError, ValueError):
                continue
            event_id = "legacy:%d" % legacy_id
            exists = conn.execute(
                """SELECT 1 FROM canonical_events
                   WHERE event_id=?""",
                (event_id,),
            ).fetchone()
            if exists is not None:
                result.append(event_id)
        return tuple(result)

    def run(self) -> SelfIdentity:
        with self.db.transaction() as conn:
            legacy_persona = self._legacy_persona(conn)
            identity_id = str(legacy_persona.get("id") or "")
            if not identity_id:
                raise SelfAuthorityError(
                    "legacy persona has no identity id"
                )
            rows = conn.execute(
                """SELECT version,at,persona_json,reason,evidence_json
                   FROM persona_versions
                   ORDER BY version"""
            ).fetchall()

        current = None
        for row in rows:
            persona = json.loads(str(row["persona_json"]))
            created_at = datetime_from_text(
                str(row["at"]), "legacy_persona.at"
            )
            evidence = ()
            with self.db.transaction() as conn:
                evidence = self._canonical_evidence_ids(
                    conn, row["evidence_json"]
                )
            if current is None:
                current = self.service.initialize(
                    identity_id=identity_id,
                    persona=persona,
                    created_at=created_at,
                    reason="legacy-backfill:" + str(row["reason"]),
                    source_event_ids=evidence,
                    legacy_persona_version=int(row["version"]),
                )
                continue

            normalized = self.service.normalize_persona(
                identity_id, persona
            )
            if normalized == current.persona:
                continue
            with self.db.transaction(immediate=True) as conn:
                revision = self.service.repository.append_persona(
                    conn,
                    identity_id=identity_id,
                    expected_revision=current.persona_revision,
                    persona=normalized,
                    reason="legacy-backfill:" + str(row["reason"]),
                    source_event_ids=list(evidence),
                    created_at=created_at,
                    legacy_persona_version=int(row["version"]),
                )
            current = self.service.get(identity_id)
            if current.persona_revision != revision:
                raise SelfAuthorityError(
                    "legacy persona revision did not advance"
                )

        if current is None:
            created_raw = legacy_persona.get("created_at")
            created_at = (
                datetime_from_text(
                    str(created_raw), "legacy_persona.created_at"
                )
                if created_raw
                else datetime.now(timezone.utc)
            )
            current = self.service.initialize(
                identity_id=identity_id,
                persona=legacy_persona,
                created_at=created_at,
                reason="legacy-backfill:current-persona",
            )

        normalized_current = self.service.normalize_persona(
            identity_id, legacy_persona
        )
        if normalized_current != current.persona:
            with self.db.transaction(immediate=True) as conn:
                self.service.repository.append_persona(
                    conn,
                    identity_id=identity_id,
                    expected_revision=current.persona_revision,
                    persona=normalized_current,
                    reason="legacy-backfill:current-persona-reconcile",
                    source_event_ids=[],
                    created_at=datetime.now(timezone.utc),
                )
            current = self.service.get(identity_id)

        return current
