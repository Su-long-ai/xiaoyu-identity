from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Optional, Tuple

from xiaoyu.contracts import InputSourceEnvelope, Taint, TrustClass
from xiaoyu.contracts.common import (
    SCHEMA_VERSION,
    canonical_json,
    datetime_from_text,
    datetime_to_text,
    require_aware,
)


def _semantic_payload(payload_type: str, payload: Any) -> Any:
    if (
        payload_type == "application/x-xiaoyu-legacy-event+json"
        and isinstance(payload, dict)
    ):
        value = dict(payload)
        value.pop("legacy_event_id", None)
        extra = value.get("extra")
        if isinstance(extra, dict):
            extra = dict(extra)
            for volatile in (
                "correlation_id",
                "source_event_key",
                "source_namespace",
            ):
                extra.pop(volatile, None)
            value["extra"] = extra
        return value
    return payload


def stable_event_id(
    identity_id: str,
    source_namespace: str,
    source_event_key: str,
) -> str:
    raw = "%s\0%s\0%s" % (
        identity_id,
        source_namespace,
        source_event_key,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return "source:" + digest[:32]


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
    source_namespace: str = "legacy"
    source_event_key: Optional[str] = None
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.recorded_at, "recorded_at")
        if not self.event_id or not self.identity_id or not self.event_type:
            raise ValueError(
                "event_id, identity_id and event_type are required"
            )
        if not self.source_namespace:
            raise ValueError("source_namespace is required")
        if not self.semantic_digest:
            object.__setattr__(
                self,
                "semantic_digest",
                self.compute_semantic_digest(),
            )

    def semantic_content(self) -> Dict[str, Any]:
        return {
            "identity_id": self.identity_id,
            "event_type": self.event_type,
            "surface": self.surface,
            "source_type": self.source_type,
            "principal_id": self.principal_id,
            "audience_scope": self.audience_scope,
            "context_space": self.context_space,
            "trust_class": self.trust_class.value,
            "taint": [value.value for value in self.taint],
            "eligible_for_memory": self.eligible_for_memory,
            "payload_type": self.payload_type,
            "payload": _semantic_payload(
                self.payload_type,
                self.payload,
            ),
        }

    def compute_semantic_digest(self) -> str:
        return "sha256:" + hashlib.sha256(
            canonical_json(self.semantic_content()).encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_envelope(
        cls,
        identity_id: str,
        event_type: str,
        envelope: InputSourceEnvelope,
        principal_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        recorded_at: Optional[datetime] = None,
        *,
        source_namespace: str = "legacy",
        source_event_key: Optional[str] = None,
        event_id_override: Optional[str] = None,
    ) -> "CanonicalEvent":
        return cls(
            event_id=event_id_override or envelope.event_id,
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
            source_namespace=source_namespace,
            source_event_key=source_event_key,
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
            self.source_namespace,
            self.source_event_key,
            self.semantic_digest,
        )


def legacy_event_to_envelope(
    legacy_event_id: int,
    at: str,
    kind: str,
    actor: str,
    content: str,
    extra: Optional[Dict[str, Any]] = None,
) -> InputSourceEnvelope:
    """Map a legacy row into an envelope; authority is decided later."""
    metadata = dict(extra or {})
    observed_at = datetime_from_text(at, "legacy_event.at")

    if actor == "user":
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
    if trust in (
        TrustClass.TOOL_OUTPUT,
        TrustClass.WEB_CONTENT,
    ):
        taints.append(Taint.THIRD_PARTY_DATA)

    return InputSourceEnvelope(
        event_id="legacy:%d" % int(legacy_event_id),
        surface=str(metadata.get("surface") or "legacy"),
        source_type=str(metadata.get("source_type") or "text"),
        principal_hint=metadata.get("principal_id"),
        audience_scope=str(
            metadata.get("audience_scope") or "PRIVATE"
        ),
        context_space=str(
            metadata.get("context_space") or "PERSONAL"
        ),
        trust_class=trust,
        taint=tuple(taints),
        eligible_for_memory=(actor == "user"),
        correlation_id=str(
            metadata.get("correlation_id")
            or "legacy:%d" % int(legacy_event_id)
        ),
        observed_at=observed_at,
        payload_type="application/x-xiaoyu-legacy-event+json",
        payload={
            "legacy_event_id": int(legacy_event_id),
            "content": str(content),
            "extra": metadata,
        },
    )
