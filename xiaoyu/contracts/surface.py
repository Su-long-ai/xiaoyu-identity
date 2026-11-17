from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from .common import SCHEMA_VERSION, datetime_from_text, datetime_to_text, ensure_exact_fields, require_aware
from .envelopes import InputSourceEnvelope


@dataclass(frozen=True)
class DeliveryReceipt:
    logical_delivery_id: str
    surface: str
    state: str
    external_ref: Optional[str]
    observed_at: datetime
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "logical_delivery_id": self.logical_delivery_id,
            "surface": self.surface,
            "state": self.state,
            "external_ref": self.external_ref,
            "observed_at": datetime_to_text(self.observed_at, "observed_at"),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeliveryReceipt":
        ensure_exact_fields(data, (
            "schema_version", "logical_delivery_id", "surface", "state",
            "external_ref", "observed_at",
        ))
        return cls(
            schema_version=int(data["schema_version"]),
            logical_delivery_id=str(data["logical_delivery_id"]),
            surface=str(data["surface"]),
            state=str(data["state"]),
            external_ref=data["external_ref"],
            observed_at=datetime_from_text(data["observed_at"], "observed_at"),
        )


@dataclass(frozen=True)
class SurfaceHealth:
    liveness: str
    readiness: str
    reason: Optional[str] = None
    schema_version: int = SCHEMA_VERSION


class SurfaceAdapter(Protocol):
    async def ingest(self, raw_input: Any) -> InputSourceEnvelope:
        ...

    async def deliver(self, delivery: Any) -> DeliveryReceipt:
        ...

    async def status(self) -> SurfaceHealth:
        ...
