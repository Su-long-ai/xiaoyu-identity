from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from xiaoyu.core.export import NativeCanonicalExporter
from xiaoyu.core.identity import SelfAuthorityService
from xiaoyu.core.memory import (
    CanonicalMemoryItem,
    CanonicalMemoryService,
    MemoryControlState,
)
from xiaoyu.core.relationship import (
    RelationshipLifecycle,
    RelationshipProjection,
    RelationshipService,
)
from xiaoyu.persistence import Database
from xiaoyu.persistence.recovery import RecoveryManager
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime.host import RuntimeHost
from xiaoyu.runtime.product_store import CanonicalProductStore
from xiaoyu.runtime.provider_registry import ProviderDescriptor
from xiaoyu.runtime.resource_broker import ResourceBroker, ResourceMode


@dataclass(frozen=True)
class OnboardingCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class OnboardingReport:
    checks: tuple[OnboardingCheck, ...]

    @property
    def ready(self) -> bool:
        return all(item.ok for item in self.checks)

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(item.detail for item in self.checks if not item.ok)


class ProductOnboardingVerifier:
    """Read-only R20 onboarding verification over existing product authorities."""

    def __init__(
        self,
        db: Database,
        *,
        identity_id: str,
        runtime_host: Optional[RuntimeHost] = None,
        runtime_descriptor: Optional[ProviderDescriptor] = None,
        backup_path=None,
    ) -> None:
        self.db = db
        self.identity_id = str(identity_id)
        self.runtime_host = runtime_host
        self.runtime_descriptor = runtime_descriptor
        self.backup_path = None if backup_path is None else Path(backup_path)

    def verify(self) -> OnboardingReport:
        checks: list[OnboardingCheck] = []

        if self.runtime_host is None or self.runtime_descriptor is None:
            checks.append(
                OnboardingCheck(
                    "provider_connectivity",
                    False,
                    "provider runtime health is not bound",
                )
            )
        else:
            admission = self.runtime_host.admit_provider(
                self.runtime_descriptor
            )
            checks.append(
                OnboardingCheck(
                    "provider_connectivity",
                    bool(admission.allowed),
                    (
                        "provider runtime is READY"
                        if admission.allowed
                        else "provider runtime not ready: "
                        + ",".join(admission.reasons)
                    ),
                )
            )

        try:
            identity = SelfAuthorityService(self.db).get(self.identity_id)
        except Exception as exc:
            checks.append(
                OnboardingCheck(
                    "identity_loaded",
                    False,
                    "canonical identity unavailable: %s"
                    % type(exc).__name__,
                )
            )
        else:
            checks.append(
                OnboardingCheck(
                    "identity_loaded",
                    bool(identity.identity_id == self.identity_id),
                    "canonical identity loaded",
                )
            )

        with self.db.transaction() as conn:
            turn_count = int(
                conn.execute(
                    """SELECT COUNT(*) FROM canonical_events
                       WHERE identity_id=?
                         AND event_type='conversation.user'""",
                    (self.identity_id,),
                ).fetchone()[0]
            )
        checks.append(
            OnboardingCheck(
                "first_turn",
                turn_count > 0,
                (
                    "first canonical user turn present"
                    if turn_count > 0
                    else "first canonical user turn is missing"
                ),
            )
        )

        try:
            memories = CanonicalMemoryService(self.db).list_current(
                identity_id=self.identity_id,
                principal_scope="owner",
            )
        except Exception as exc:
            checks.append(
                OnboardingCheck(
                    "memory_control",
                    False,
                    "memory inspection failed: %s" % type(exc).__name__,
                )
            )
        else:
            inspectable = bool(memories) and all(
                item.revision > 0 and bool(item.source_event_id)
                for item in memories
            )
            checks.append(
                OnboardingCheck(
                    "memory_control",
                    inspectable,
                    (
                        "first memory is inspectable with source/revision"
                        if inspectable
                        else "no inspectable current memory yet"
                    ),
                )
            )

        backup_ok = False
        backup_detail = "managed backup/status is not configured"
        if self.backup_path is not None:
            try:
                RecoveryManager.validate_backup_manifest(
                    self.backup_path,
                    expected_identity_id=self.identity_id,
                )
            except Exception as exc:
                backup_detail = (
                    "managed backup/status invalid: %s"
                    % type(exc).__name__
                )
            else:
                backup_ok = True
                backup_detail = "managed backup/status is visible and valid"
        checks.append(
            OnboardingCheck(
                "backup_status",
                backup_ok,
                backup_detail,
            )
        )
        return OnboardingReport(tuple(checks))


@dataclass(frozen=True)
class MemoryControlView:
    memory_id: str
    fact_id: str
    revision: int
    source_event_id: str
    text: str
    category: str
    priority: int
    control_state: MemoryControlState
    archived: bool


class MemoryControlService:
    """R20 user-facing memory control backed only by canonical R9 memory."""

    def __init__(self, store: CanonicalProductStore) -> None:
        self.store = store

    @staticmethod
    def _view(item: CanonicalMemoryItem) -> MemoryControlView:
        return MemoryControlView(
            memory_id=item.memory_id,
            fact_id=item.fact_id,
            revision=item.revision,
            source_event_id=item.source_event_id,
            text=item.text,
            category=item.category,
            priority=item.priority,
            control_state=item.control_state,
            archived=item.archived,
        )

    def inspect(self, principal_id: str = "owner") -> list[MemoryControlView]:
        return [
            self._view(item)
            for item in self.store.memory.list_current(
                identity_id=self.store.identity_id,
                principal_scope=principal_id,
            )
        ]

    def set_state(
        self,
        *,
        memory_id: str,
        expected_revision: int,
        control_state: MemoryControlState,
        source_event_key: str,
        principal_id: str = "owner",
        created_at: Optional[datetime] = None,
    ) -> MemoryControlView:
        at = created_at or datetime.now(timezone.utc)
        event = self.store.record_owner_control(
            source_event_key=source_event_key,
            event_type="memory.control_state",
            payload={
                "memory_id": memory_id,
                "control_state": MemoryControlState(control_state).value,
            },
            principal_id=principal_id,
            observed_at=at,
        )
        item = self.store.memory.set_control_state(
            memory_id=memory_id,
            mutation_id="memory-control:" + source_event_key,
            source_event_id=event.event_id,
            principal_id=principal_id,
            expected_revision=expected_revision,
            control_state=MemoryControlState(control_state),
            created_at=at,
        )
        return self._view(item)

    def archive(
        self,
        *,
        memory_id: str,
        expected_revision: int,
        archived: bool,
        source_event_key: str,
        principal_id: str = "owner",
        created_at: Optional[datetime] = None,
    ) -> MemoryControlView:
        at = created_at or datetime.now(timezone.utc)
        event = self.store.record_owner_control(
            source_event_key=source_event_key,
            event_type="memory.archive" if archived else "memory.unarchive",
            payload={"memory_id": memory_id, "archived": bool(archived)},
            principal_id=principal_id,
            observed_at=at,
        )
        item = self.store.memory.archive(
            memory_id=memory_id,
            mutation_id="memory-archive:" + source_event_key,
            source_event_id=event.event_id,
            principal_id=principal_id,
            expected_revision=expected_revision,
            archived=bool(archived),
            created_at=at,
        )
        return self._view(item)

    def correct(
        self,
        *,
        memory_id: str,
        expected_revision: int,
        text: str,
        category: str,
        priority: int,
        source_event_key: str,
        principal_id: str = "owner",
        created_at: Optional[datetime] = None,
    ) -> MemoryControlView:
        at = created_at or datetime.now(timezone.utc)
        event = self.store.record_owner_control(
            source_event_key=source_event_key,
            event_type="memory.corrected",
            payload={"memory_id": memory_id},
            principal_id=principal_id,
            observed_at=at,
        )
        item = self.store.memory.correct(
            memory_id=memory_id,
            mutation_id="memory-correct:" + source_event_key,
            source_event_id=event.event_id,
            principal_id=principal_id,
            expected_revision=expected_revision,
            text=text,
            category=category,
            priority=priority,
            created_at=at,
        )
        return self._view(item)

    def delete(
        self,
        *,
        memory_id: str,
        expected_revision: int,
        source_event_key: str,
        principal_id: str = "owner",
        created_at: Optional[datetime] = None,
    ) -> None:
        at = created_at or datetime.now(timezone.utc)
        event = self.store.record_owner_control(
            source_event_key=source_event_key,
            event_type="memory.deleted",
            payload={"memory_id": memory_id},
            principal_id=principal_id,
            observed_at=at,
        )
        self.store.memory.delete(
            memory_id=memory_id,
            mutation_id="memory-delete:" + source_event_key,
            source_event_id=event.event_id,
            principal_id=principal_id,
            expected_revision=expected_revision,
            created_at=at,
        )


@dataclass(frozen=True)
class OffboardingReport:
    paused: bool
    cancelled_purpose_ids: tuple[str, ...]
    relationship: RelationshipProjection
    exported_path: Optional[str]
    deleted_memory_ids: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.blockers


class ProductOffboardingService:
    """Immediate, explicit R20 pause/export/reset/delete orchestration."""

    def __init__(
        self,
        store: CanonicalProductStore,
        *,
        resource_broker: Optional[ResourceBroker] = None,
    ) -> None:
        self.store = store
        self.db = store.db
        self.resource_broker = resource_broker
        self.relationships = RelationshipService(self.db)
        self.memory_controls = MemoryControlService(store)
        self.purposes = PurposeRepository()

    def _cancel_purposes(self, at: datetime) -> tuple[tuple[str, ...], tuple[str, ...]]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT purpose_id FROM purposes
                   WHERE identity_id=? AND state IN
                   ('CONFIRMED','SCHEDULED','ACTIVE','WAITING')
                   ORDER BY purpose_id""",
                (self.store.identity_id,),
            ).fetchall()
        cancelled: list[str] = []
        blockers: list[str] = []
        for row in rows:
            purpose_id = str(row["purpose_id"])
            with self.db.transaction(immediate=True) as conn:
                ok = self.purposes.cancel(conn, purpose_id, at)
                state_row = conn.execute(
                    "SELECT state FROM purposes WHERE purpose_id=?",
                    (purpose_id,),
                ).fetchone()
            if ok:
                cancelled.append(purpose_id)
            elif state_row is not None and str(state_row["state"]) == "NEEDS_RECONCILIATION":
                blockers.append(
                    "purpose %s requires reconciliation" % purpose_id
                )
            elif state_row is not None and str(state_row["state"]) != "CANCELLED":
                blockers.append(
                    "purpose %s did not pause" % purpose_id
                )
        return tuple(cancelled), tuple(blockers)

    def execute(
        self,
        *,
        source_event_key: str,
        principal_id: str = "owner",
        relationship_principal_id: str = "owner",
        export_path=None,
        reset_relationship: bool = False,
        delete_memory_ids: Sequence[str] = (),
        delete_all_memories: bool = False,
        created_at: Optional[datetime] = None,
    ) -> OffboardingReport:
        at = created_at or datetime.now(timezone.utc)
        event = self.store.record_owner_control(
            source_event_key=source_event_key,
            event_type="offboarding.requested",
            payload={
                "reset_relationship": bool(reset_relationship),
                "delete_all_memories": bool(delete_all_memories),
                "delete_memory_ids": list(delete_memory_ids),
            },
            principal_id=principal_id,
            observed_at=at,
        )

        blockers: list[str] = []
        cancelled, purpose_blockers = self._cancel_purposes(at)
        blockers.extend(purpose_blockers)

        background_paused = False
        if self.resource_broker is None:
            blockers.append("background runtime broker is not bound")
        else:
            try:
                self.resource_broker.set_mode(ResourceMode.SLEEP)
            except Exception as exc:
                blockers.append(
                    "background pause failed: %s" % type(exc).__name__
                )
            else:
                background_paused = True

        current = self.relationships.get(
            identity_id=self.store.identity_id,
            principal_id=relationship_principal_id,
        )
        relationship = current
        try:
            if reset_relationship:
                relationship = self.relationships.reset(
                    transition_id="relationship-reset:" + source_event_key,
                    identity_id=self.store.identity_id,
                    principal_id=relationship_principal_id,
                    source_event_id=event.event_id,
                    reason="OWNER_OFFBOARDING_RESET",
                    created_at=at,
                )
                relationship = self.relationships.transition(
                    transition_id="relationship-pause:" + source_event_key,
                    identity_id=self.store.identity_id,
                    principal_id=relationship_principal_id,
                    expected_state=RelationshipLifecycle.NEW,
                    to_state=RelationshipLifecycle.PAUSED,
                    source_event_id=event.event_id,
                    reason="OWNER_OFFBOARDING_PAUSE",
                    value_patch={
                        "proactivity_policy": {"enabled": False}
                    },
                    created_at=at,
                )
            elif current.state not in (
                RelationshipLifecycle.PAUSED,
                RelationshipLifecycle.ENDED,
            ):
                relationship = self.relationships.transition(
                    transition_id="relationship-pause:" + source_event_key,
                    identity_id=self.store.identity_id,
                    principal_id=relationship_principal_id,
                    expected_state=current.state,
                    to_state=RelationshipLifecycle.PAUSED,
                    source_event_id=event.event_id,
                    reason="OWNER_OFFBOARDING_PAUSE",
                    value_patch={
                        "proactivity_policy": {"enabled": False}
                    },
                    created_at=at,
                )
        except Exception as exc:
            blockers.append(
                "relationship pause/reset failed: %s" % type(exc).__name__
            )

        exported_path: Optional[str] = None
        if export_path is not None:
            try:
                exported = NativeCanonicalExporter(self.db).write(
                    export_path,
                    identity_id=self.store.identity_id,
                )
            except Exception as exc:
                blockers.append(
                    "native export failed: %s" % type(exc).__name__
                )
            else:
                exported_path = str(exported)

        current_memories = self.memory_controls.inspect(principal_id)
        current_by_id = {item.memory_id: item for item in current_memories}
        targets = (
            sorted(current_by_id)
            if delete_all_memories
            else [str(value) for value in delete_memory_ids]
        )
        deleted: list[str] = []
        for index, memory_id in enumerate(targets):
            item = current_by_id.get(memory_id)
            if item is None:
                blockers.append(
                    "memory %s is not current/managed" % memory_id
                )
                continue
            try:
                self.store.memory.delete(
                    memory_id=memory_id,
                    mutation_id=(
                        "offboarding-memory-delete:%s:%d"
                        % (source_event_key, index)
                    ),
                    source_event_id=event.event_id,
                    principal_id=principal_id,
                    expected_revision=item.revision,
                    created_at=at,
                )
            except Exception as exc:
                blockers.append(
                    "memory %s delete failed: %s"
                    % (memory_id, type(exc).__name__)
                )
            else:
                deleted.append(memory_id)

        paused = (
            background_paused
            and not purpose_blockers
            and relationship.state
            in (RelationshipLifecycle.PAUSED, RelationshipLifecycle.ENDED)
        )
        return OffboardingReport(
            paused=paused,
            cancelled_purpose_ids=cancelled,
            relationship=relationship,
            exported_path=exported_path,
            deleted_memory_ids=tuple(deleted),
            blockers=tuple(blockers),
        )
