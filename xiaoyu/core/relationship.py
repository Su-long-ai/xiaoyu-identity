from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Optional

from xiaoyu.contracts import TrustClass
from xiaoyu.contracts.common import StringEnum, datetime_from_text
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.relationship import RelationshipRepository


class RelationshipLifecycle(StringEnum):
    NEW = "NEW"
    FAMILIAR = "FAMILIAR"
    ESTABLISHED = "ESTABLISHED"
    DISTANT = "DISTANT"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class RelationshipTransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RelationshipProjection:
    identity_id: str
    principal_id: str
    state: RelationshipLifecycle
    revision: int
    value: dict[str, Any]
    source_event_ids: tuple[str, ...]
    builder_version: str


class RelationshipService:
    BUILDER_VERSION = "r10.relationship.v1"
    TRUSTED_EVIDENCE = {
        TrustClass.OWNER_DIRECT,
        TrustClass.OWNER_AUTHENTICATED_DEVICE,
        TrustClass.KNOWN_CONTACT,
        TrustClass.GROUP_SHARED,
    }
    ALLOWED = {
        RelationshipLifecycle.NEW: {
            RelationshipLifecycle.FAMILIAR,
            RelationshipLifecycle.PAUSED,
            RelationshipLifecycle.ENDED,
        },
        RelationshipLifecycle.FAMILIAR: {
            RelationshipLifecycle.ESTABLISHED,
            RelationshipLifecycle.DISTANT,
            RelationshipLifecycle.PAUSED,
            RelationshipLifecycle.ENDED,
        },
        RelationshipLifecycle.ESTABLISHED: {
            RelationshipLifecycle.DISTANT,
            RelationshipLifecycle.PAUSED,
            RelationshipLifecycle.ENDED,
        },
        RelationshipLifecycle.DISTANT: {
            RelationshipLifecycle.FAMILIAR,
            RelationshipLifecycle.PAUSED,
            RelationshipLifecycle.ENDED,
        },
        RelationshipLifecycle.PAUSED: {
            RelationshipLifecycle.FAMILIAR,
            RelationshipLifecycle.ENDED,
        },
        RelationshipLifecycle.ENDED: set(),
    }
    ALLOWED_VALUE_KEYS = {
        "shared_history",
        "interaction_norms",
        "boundaries",
        "proactivity_policy",
    }

    def __init__(
        self,
        db: Database,
        repository=None,
        event_repository=None,
    ) -> None:
        self.db = db
        self.repository = repository or RelationshipRepository()
        self.event_repository = (
            event_repository or CanonicalEventRepository()
        )

    @staticmethod
    def _merge(base: dict, patch: dict) -> dict:
        result = json.loads(json.dumps(base))
        for key, value in patch.items():
            if (
                isinstance(value, dict)
                and isinstance(result.get(key), dict)
            ):
                merged = dict(result[key])
                merged.update(value)
                result[key] = merged
            else:
                result[key] = value
        return result

    def _validate_patch(self, patch: dict) -> None:
        unknown = set(patch) - self.ALLOWED_VALUE_KEYS
        if unknown:
            raise RelationshipTransitionError(
                "relationship projection keys not allowed: %s"
                % ",".join(sorted(unknown))
            )

    def transition(
        self,
        *,
        transition_id: str,
        identity_id: str,
        principal_id: str,
        expected_state: RelationshipLifecycle,
        to_state: RelationshipLifecycle,
        source_event_id: str,
        reason: str,
        value_patch: Optional[dict] = None,
        created_at: Optional[datetime] = None,
    ) -> RelationshipProjection:
        patch = dict(value_patch or {})
        self._validate_patch(patch)
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            event = self.event_repository.get(conn, source_event_id)
            if event is None:
                raise KeyError("unknown source event %s" % source_event_id)
            if event.identity_id != identity_id:
                raise RelationshipTransitionError(
                    "relationship evidence belongs to another identity"
                )
            if event.principal_id != principal_id:
                raise RelationshipTransitionError(
                    "relationship evidence principal mismatch"
                )
            if event.trust_class not in self.TRUSTED_EVIDENCE:
                raise RelationshipTransitionError(
                    "untrusted/model-derived evidence cannot move relationship state"
                )
            ingest_revision = self.event_repository.get_ingest_revision(
                conn, source_event_id
            )

            current = self.repository.get(
                conn,
                identity_id=identity_id,
                principal_id=principal_id,
            )
            if current is None:
                current_state = RelationshipLifecycle.NEW
                revision = 0
                value = {}
                source_ids: list[str] = []
            else:
                current_state = RelationshipLifecycle(current["state"])
                revision = int(current["revision"])
                value = dict(current["value"])
                source_ids = list(current["source_event_ids"])

            if current_state != expected_state:
                raise RelationshipTransitionError(
                    "expected %s but current relationship state is %s"
                    % (expected_state.value, current_state.value)
                )
            if to_state not in self.ALLOWED[current_state]:
                raise RelationshipTransitionError(
                    "invalid relationship transition %s -> %s"
                    % (current_state.value, to_state.value)
                )

            self.repository.append_transition(
                conn,
                transition_id=transition_id,
                identity_id=identity_id,
                principal_id=principal_id,
                from_state=current_state.value,
                to_state=to_state.value,
                source_event_id=source_event_id,
                source_ingest_revision=ingest_revision,
                value_patch=patch,
                reason=reason,
                created_at=at,
            )
            value = self._merge(value, patch)
            if source_event_id not in source_ids:
                source_ids.append(source_event_id)
            self.repository.upsert_state(
                conn,
                identity_id=identity_id,
                principal_id=principal_id,
                state=to_state.value,
                value=value,
                source_event_ids=source_ids,
                revision=revision + 1,
                builder_version=self.BUILDER_VERSION,
                last_transition_id=transition_id,
                effective_from=at,
                updated_at=at,
            )
        return RelationshipProjection(
            identity_id=identity_id,
            principal_id=principal_id,
            state=to_state,
            revision=revision + 1,
            value=value,
            source_event_ids=tuple(source_ids),
            builder_version=self.BUILDER_VERSION,
        )

    def get(
        self,
        *,
        identity_id: str,
        principal_id: str,
    ) -> RelationshipProjection:
        with self.db.transaction() as conn:
            current = self.repository.get(
                conn,
                identity_id=identity_id,
                principal_id=principal_id,
            )
        if current is None:
            return RelationshipProjection(
                identity_id=identity_id,
                principal_id=principal_id,
                state=RelationshipLifecycle.NEW,
                revision=0,
                value={},
                source_event_ids=(),
                builder_version=self.BUILDER_VERSION,
            )
        return RelationshipProjection(
            identity_id=identity_id,
            principal_id=principal_id,
            state=RelationshipLifecycle(current["state"]),
            revision=int(current["revision"]),
            value=dict(current["value"]),
            source_event_ids=tuple(current["source_event_ids"]),
            builder_version=str(current["builder_version"]),
        )

    def rebuild(
        self,
        *,
        identity_id: str,
        principal_id: str,
    ) -> RelationshipProjection:
        with self.db.transaction(immediate=True) as conn:
            transitions = self.repository.list_transitions(
                conn,
                identity_id=identity_id,
                principal_id=principal_id,
            )
            if not transitions:
                conn.execute(
                    """DELETE FROM relationship_state
                       WHERE identity_id=? AND principal_id=?""",
                    (identity_id, principal_id),
                )
                return RelationshipProjection(
                    identity_id=identity_id,
                    principal_id=principal_id,
                    state=RelationshipLifecycle.NEW,
                    revision=0,
                    value={},
                    source_event_ids=(),
                    builder_version=self.BUILDER_VERSION,
                )

            state = RelationshipLifecycle.NEW
            value: dict[str, Any] = {}
            source_ids: list[str] = []
            first_at = None
            last_at = None
            last_transition_id = ""
            revision = 0
            for row in transitions:
                from_state = RelationshipLifecycle(str(row["from_state"]))
                to_state = RelationshipLifecycle(str(row["to_state"]))
                if state != from_state or to_state not in self.ALLOWED[state]:
                    raise RelationshipTransitionError(
                        "relationship transition log is not replayable"
                    )
                patch = json.loads(row["value_patch_json"])
                self._validate_patch(patch)
                state = to_state
                value = self._merge(value, patch)
                source_id = str(row["source_event_id"])
                if source_id not in source_ids:
                    source_ids.append(source_id)
                at = datetime_from_text(str(row["created_at"]), "created_at")
                first_at = first_at or at
                last_at = at
                last_transition_id = str(row["transition_id"])
                revision += 1

            self.repository.upsert_state(
                conn,
                identity_id=identity_id,
                principal_id=principal_id,
                state=state.value,
                value=value,
                source_event_ids=source_ids,
                revision=revision,
                builder_version=self.BUILDER_VERSION,
                last_transition_id=last_transition_id,
                effective_from=first_at,
                updated_at=last_at,
            )
        return RelationshipProjection(
            identity_id=identity_id,
            principal_id=principal_id,
            state=state,
            revision=revision,
            value=value,
            source_event_ids=tuple(source_ids),
            builder_version=self.BUILDER_VERSION,
        )
