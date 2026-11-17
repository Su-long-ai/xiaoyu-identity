from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable, Dict, List, Optional


ResourceCallback = Callable[[], None]


@dataclass(frozen=True)
class ResourceLeaseSnapshot:
    lease_id: str
    effect_id: str
    resource_id: str
    state: str
    cancel_supported: bool
    last_error: Optional[str]


@dataclass
class _ResourceLease:
    lease_id: str
    effect_id: str
    resource_id: str
    cancel: Optional[ResourceCallback]
    release: ResourceCallback
    state: str = "ACQUIRED"
    last_error: Optional[str] = None


class ExecutionResourceBroker:
    """Small execution-side resource cancellation/release registry.

    The broker is intentionally process-local: it coordinates runtime handles
    such as subprocesses, sockets or provider sessions.  Durable effect state
    remains in the existing SQLite execution ledger.  Release is idempotent;
    cancel always attempts release even when the provider cancel callback
    fails, so a best-effort cancellation cannot leak a local resource handle.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._leases: Dict[str, _ResourceLease] = {}

    def acquire(
        self,
        *,
        lease_id: str,
        effect_id: str,
        resource_id: str,
        release: ResourceCallback,
        cancel: Optional[ResourceCallback] = None,
    ) -> ResourceLeaseSnapshot:
        if not lease_id or not effect_id or not resource_id:
            raise ValueError("lease_id, effect_id and resource_id are required")
        if not callable(release):
            raise TypeError("release must be callable")
        if cancel is not None and not callable(cancel):
            raise TypeError("cancel must be callable")

        with self._lock:
            existing = self._leases.get(lease_id)
            if existing is not None:
                if (
                    existing.effect_id == effect_id
                    and existing.resource_id == resource_id
                ):
                    return self._snapshot(existing)
                raise ValueError("lease_id already belongs to another resource")
            lease = _ResourceLease(
                lease_id=lease_id,
                effect_id=effect_id,
                resource_id=resource_id,
                cancel=cancel,
                release=release,
            )
            self._leases[lease_id] = lease
            return self._snapshot(lease)

    def release(self, lease_id: str) -> ResourceLeaseSnapshot:
        with self._lock:
            lease = self._require(lease_id)
            if lease.state == "RELEASED":
                return self._snapshot(lease)
            try:
                lease.release()
            except Exception as exc:
                lease.state = "RELEASE_FAILED"
                lease.last_error = "%s:%s" % (
                    type(exc).__name__,
                    str(exc),
                )
                return self._snapshot(lease)
            lease.state = "RELEASED"
            lease.last_error = None
            return self._snapshot(lease)

    def cancel(self, lease_id: str) -> ResourceLeaseSnapshot:
        with self._lock:
            lease = self._require(lease_id)
            if lease.state == "RELEASED":
                return self._snapshot(lease)

            cancel_error = None
            if lease.cancel is not None:
                try:
                    lease.cancel()
                except Exception as exc:
                    cancel_error = "%s:%s" % (
                        type(exc).__name__,
                        str(exc),
                    )

            try:
                lease.release()
            except Exception as exc:
                release_error = "%s:%s" % (
                    type(exc).__name__,
                    str(exc),
                )
                lease.state = "RELEASE_FAILED"
                lease.last_error = (
                    release_error
                    if cancel_error is None
                    else cancel_error + ";" + release_error
                )
                return self._snapshot(lease)

            lease.state = "RELEASED"
            lease.last_error = cancel_error
            return self._snapshot(lease)

    def cancel_effect(self, effect_id: str) -> List[ResourceLeaseSnapshot]:
        with self._lock:
            lease_ids = [
                lease_id
                for lease_id, lease in self._leases.items()
                if lease.effect_id == effect_id
                and lease.state != "RELEASED"
            ]
        return [self.cancel(lease_id) for lease_id in lease_ids]

    def release_effect(self, effect_id: str) -> List[ResourceLeaseSnapshot]:
        with self._lock:
            lease_ids = [
                lease_id
                for lease_id, lease in self._leases.items()
                if lease.effect_id == effect_id
                and lease.state != "RELEASED"
            ]
        return [self.release(lease_id) for lease_id in lease_ids]

    def list_effect(self, effect_id: str) -> List[ResourceLeaseSnapshot]:
        with self._lock:
            return [
                self._snapshot(lease)
                for lease in self._leases.values()
                if lease.effect_id == effect_id
            ]

    def _require(self, lease_id: str) -> _ResourceLease:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise KeyError("unknown resource lease %s" % lease_id)
        return lease

    @staticmethod
    def _snapshot(lease: _ResourceLease) -> ResourceLeaseSnapshot:
        return ResourceLeaseSnapshot(
            lease_id=lease.lease_id,
            effect_id=lease.effect_id,
            resource_id=lease.resource_id,
            state=lease.state,
            cancel_supported=lease.cancel is not None,
            last_error=lease.last_error,
        )
