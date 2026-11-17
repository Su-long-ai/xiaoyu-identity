from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from xiaoyu.contracts import InputSourceEnvelope, Taint, TrustClass
from xiaoyu.contracts.common import SCHEMA_VERSION, canonical_json, datetime_from_text, datetime_to_text, require_aware


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    identity_id: str
    turn_id: Optional[str]
    event_type: str
    surface: str
    source_type: str
    principal_id: Optional[str]
    audience_scope: str
    context_space: str
    trust_class: TrustClass
    taint: Tuple[Taint, ...]
    eligible_for_memory: bool
    payload_type: str
    payload: Any
    observed_at: datetime
    recorded_at: datetime
    correlation_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.recorded_at, "recorded_at")
        if not self.event_id or not self.identity_id or not self.event_type:
            raise ValueError("event_id, identity_id and event_type are required")

    @classmethod
    def from_envelope(
        cls,
        identity_id: str,
        event_type: str,
        envelope: InputSourceEnvelope,
        principal_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        recorded_at: Optional[datetime] = None,
    ) -> "CanonicalEvent":
        return cls(
            event_id=envelope.event_id,
            identity_id=identity_id,
            turn_id=turn_id,
            event_type=event_type,
            surface=envelope.surface,
            source_type=envelope.source_type,
            principal_id=principal_id,
            audience_scope=envelope.audience_scope,
            context_space=envelope.context_space,
            trust_class=envelope.trust_class,
            taint=envelope.taint,
            eligible_for_memory=envelope.eligible_for_memory,
            payload_type=envelope.payload_type,
            payload=envelope.payload,
            observed_at=envelope.observed_at,
            recorded_at=recorded_at or datetime.now(timezone.utc),
            correlation_id=envelope.correlation_id,
            schema_version=envelope.schema_version,
        )

    def storage_tuple(self) -> tuple:
        return (
            self.event_id,
            self.identity_id,
            self.turn_id,
            self.event_type,
            self.surface,
            self.source_type,
            self.principal_id,
            self.audience_scope,
            self.context_space,
            self.trust_class.value,
            canonical_json([value.value for value in self.taint]),
            1 if self.eligible_for_memory else 0,
            self.payload_type,
            canonical_json(self.payload),
            datetime_to_text(self.observed_at, "observed_at"),
            datetime_to_text(self.recorded_at, "recorded_at"),
            self.correlation_id,
            self.schema_version,
        )


def legacy_event_to_envelope(
    legacy_event_id: int,
    at: str,
    kind: str,
    actor: str,
    content: str,
    extra: Optional[Dict[str, Any]] = None,
) -> InputSourceEnvelope:
    """Map proven legacy IdentityStore events into the V1 envelope without inference."""
    metadata = dict(extra or {})
    observed_at = datetime_from_text(at, "legacy_event.at")

    explicit_trust = metadata.get("trust_class")
    if explicit_trust:
        trust = TrustClass(str(explicit_trust))
    elif actor == "user":
        trust = TrustClass.OWNER_DIRECT
    elif actor == "assistant":
        trust = TrustClass.MODEL_DERIVED
    elif actor == "tool":
        trust = TrustClass.TOOL_OUTPUT
    else:
        trust = TrustClass.UNKNOWN

    taints = []
    if trust == TrustClass.MODEL_DERIVED:
        taints.append(Taint.MODEL_INFERRED)
    if trust in (TrustClass.TOOL_OUTPUT, TrustClass.WEB_CONTENT):
        taints.append(Taint.THIRD_PARTY_DATA)

    return InputSourceEnvelope(
        event_id="legacy:%d" % int(legacy_event_id),
        surface=str(metadata.get("surface") or "legacy"),
        source_type=str(metadata.get("source_type") or "text"),
        principal_hint=metadata.get("principal_id"),
        audience_scope=str(metadata.get("audience_scope") or "PRIVATE"),
        context_space=str(metadata.get("context_space") or "PERSONAL"),
        trust_class=trust,
        taint=tuple(taints),
        eligible_for_memory=(actor == "user"),
        correlation_id=str(metadata.get("correlation_id") or "legacy:%d" % int(legacy_event_id)),
        observed_at=observed_at,
        payload_type="application/x-xiaoyu-legacy-event+json",
        payload={
            "legacy_event_id": int(legacy_event_id),
            "content": str(content),
            "extra": metadata,
        },
    )
