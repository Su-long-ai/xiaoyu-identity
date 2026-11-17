from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .common import (
    SCHEMA_VERSION,
    datetime_from_text,
    datetime_to_text,
    ensure_exact_fields,
    require_aware,
)


@dataclass(frozen=True)
class PrincipalContext:
    principal_id: str
    authentication_level: str
    confidence: float
    evidence_classes: Tuple[str, ...]
    viewer_set: Tuple[str, ...]
    session_scope: str
    expires_at: Optional[datetime]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "principal_id": self.principal_id,
            "authentication_level": self.authentication_level,
            "confidence": self.confidence,
            "evidence_classes": list(self.evidence_classes),
            "viewer_set": list(self.viewer_set),
            "session_scope": self.session_scope,
            "expires_at": None if self.expires_at is None else datetime_to_text(self.expires_at, "expires_at"),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrincipalContext":
        ensure_exact_fields(data, (
            "schema_version", "principal_id", "authentication_level", "confidence",
            "evidence_classes", "viewer_set", "session_scope", "expires_at",
        ))
        expires = data["expires_at"]
        return cls(
            schema_version=int(data["schema_version"]),
            principal_id=str(data["principal_id"]),
            authentication_level=str(data["authentication_level"]),
            confidence=float(data["confidence"]),
            evidence_classes=tuple(str(v) for v in data["evidence_classes"]),
            viewer_set=tuple(str(v) for v in data["viewer_set"]),
            session_scope=str(data["session_scope"]),
            expires_at=None if expires is None else datetime_from_text(expires, "expires_at"),
        )
