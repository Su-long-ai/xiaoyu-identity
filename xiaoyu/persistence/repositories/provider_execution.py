from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from typing import Optional

from xiaoyu.contracts import CapabilityDescriptor, ProviderHealth, ProviderLifecycle
from xiaoyu.contracts.common import canonical_json, datetime_to_text
from xiaoyu.persistence import Database


class ProviderExecutionRegistry:
    """Execution-facing provider registry.

    This intentionally owns only descriptor/version, lifecycle and health data
    required at the transport authorization boundary.  Privacy/fallback policy
    remains outside this component.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def register(
        self,
        descriptor: CapabilityDescriptor,
        health: ProviderHealth,
        updated_at: Optional[datetime] = None,
    ) -> None:
        current = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO provider_registry(
                       provider_id,capability,descriptor_json,artifact_digest,
                       descriptor_digest,interface_digest,tool_schema_digest,
                       lifecycle_state,health_state_json,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(provider_id) DO UPDATE SET
                       capability=excluded.capability,
                       descriptor_json=excluded.descriptor_json,
                       artifact_digest=excluded.artifact_digest,
                       descriptor_digest=excluded.descriptor_digest,
                       interface_digest=excluded.interface_digest,
                       tool_schema_digest=excluded.tool_schema_digest,
                       lifecycle_state=excluded.lifecycle_state,
                       health_state_json=excluded.health_state_json,
                       updated_at=excluded.updated_at""",
                (
                    descriptor.provider_id,
                    descriptor.capability,
                    canonical_json(descriptor.to_dict()),
                    descriptor.artifact_digest,
                    descriptor.descriptor_digest,
                    descriptor.interface_digest,
                    descriptor.tool_schema_digest,
                    descriptor.lifecycle.value,
                    canonical_json(health.to_dict()),
                    datetime_to_text(current, "updated_at"),
                ),
            )

    def update_health(
        self,
        provider_id: str,
        health: ProviderHealth,
        updated_at: Optional[datetime] = None,
    ) -> bool:
        current = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            cur = conn.execute(
                """UPDATE provider_registry
                   SET health_state_json=?,updated_at=?
                   WHERE provider_id=?""",
                (
                    canonical_json(health.to_dict()),
                    datetime_to_text(current, "updated_at"),
                    provider_id,
                ),
            )
            return cur.rowcount == 1

    def set_lifecycle(
        self,
        provider_id: str,
        lifecycle: ProviderLifecycle,
        updated_at: Optional[datetime] = None,
    ) -> bool:
        current = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            cur = conn.execute(
                """UPDATE provider_registry
                   SET lifecycle_state=?,updated_at=?
                   WHERE provider_id=?""",
                (
                    lifecycle.value,
                    datetime_to_text(current, "updated_at"),
                    provider_id,
                ),
            )
            return cur.rowcount == 1


    def snapshot(
        self,
        provider_id: str,
    ) -> Optional[tuple[CapabilityDescriptor, ProviderHealth]]:
        """Return the current durable descriptor + health snapshot.

        The mutable lifecycle column is authoritative over the descriptor JSON
        captured at registration time.
        """
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT descriptor_json,lifecycle_state,health_state_json
                   FROM provider_registry WHERE provider_id=?""",
                (provider_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            descriptor = CapabilityDescriptor.from_dict(
                json.loads(str(row["descriptor_json"]))
            )
            health = ProviderHealth.from_dict(
                json.loads(str(row["health_state_json"]))
            )
            descriptor = replace(
                descriptor,
                lifecycle=ProviderLifecycle(
                    str(row["lifecycle_state"])
                ),
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return None
        return descriptor, health

    def list_for_capability(
        self,
        capability: str,
    ) -> list[tuple[CapabilityDescriptor, ProviderHealth]]:
        with self.db.transaction() as conn:
            provider_ids = [
                str(row["provider_id"])
                for row in conn.execute(
                    """SELECT provider_id FROM provider_registry
                       WHERE capability=?
                       ORDER BY provider_id""",
                    (capability,),
                ).fetchall()
            ]
        result = []
        for provider_id in provider_ids:
            snapshot = self.snapshot(provider_id)
            if snapshot is not None:
                result.append(snapshot)
        return result

    def authorization_compatible(
        self,
        *,
        provider_id: str,
        capability: str,
        artifact_digest: Optional[str],
        interface_digest: str,
        tool_schema_digest: Optional[str],
    ) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT capability,artifact_digest,interface_digest,
                          tool_schema_digest,lifecycle_state,health_state_json
                   FROM provider_registry WHERE provider_id=?""",
                (provider_id,),
            ).fetchone()
        if row is None or str(row["lifecycle_state"]) != "ACTIVE":
            return False
        if (
            str(row["capability"]) != capability
            or row["artifact_digest"] != artifact_digest
            or str(row["interface_digest"]) != interface_digest
            or row["tool_schema_digest"] != tool_schema_digest
        ):
            return False
        import json
        try:
            health = json.loads(str(row["health_state_json"]))
        except (TypeError, ValueError):
            return False
        return (
            str(health.get("readiness", "")).upper() == "READY"
            and str(health.get("liveness", "")).upper()
            not in {"DOWN", "DEAD", "UNAVAILABLE"}
        )
