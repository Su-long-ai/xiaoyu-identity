from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .common import SCHEMA_VERSION, datetime_from_text, datetime_to_text, ensure_exact_fields, require_aware


@dataclass(frozen=True)
class MultimodalEvidenceRef:
    modality: str
    source_id: str
    observed_from: datetime
    observed_to: Optional[datetime]
    content_digest: str
    derived_text: Optional[str]
    retention_class: str
    privacy_class: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.observed_from, "observed_from")
        if self.observed_to is not None:
            require_aware(self.observed_to, "observed_to")
            if self.observed_to < self.observed_from:
                raise ValueError("observed_to cannot be earlier than observed_from")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "modality": self.modality,
            "source_id": self.source_id,
            "observed_from": datetime_to_text(self.observed_from, "observed_from"),
            "observed_to": None if self.observed_to is None else datetime_to_text(self.observed_to, "observed_to"),
            "content_digest": self.content_digest,
            "derived_text": self.derived_text,
            "retention_class": self.retention_class,
            "privacy_class": self.privacy_class,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultimodalEvidenceRef":
        ensure_exact_fields(data, (
            "schema_version", "modality", "source_id", "observed_from", "observed_to",
            "content_digest", "derived_text", "retention_class", "privacy_class",
        ))
        end = data["observed_to"]
        return cls(
            schema_version=int(data["schema_version"]),
            modality=str(data["modality"]),
            source_id=str(data["source_id"]),
            observed_from=datetime_from_text(data["observed_from"], "observed_from"),
            observed_to=None if end is None else datetime_from_text(end, "observed_to"),
            content_digest=str(data["content_digest"]),
            derived_text=data["derived_text"],
            retention_class=str(data["retention_class"]),
            privacy_class=str(data["privacy_class"]),
        )
