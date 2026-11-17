from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Dict, Mapping, Optional, Tuple

from xiaoyu.contracts import CapabilityDescriptor


class ResourceMode(str, Enum):
    ECO = "ECO"
    BALANCED = "BALANCED"
    FULL = "FULL"
    GAME = "GAME"
    SLEEP = "SLEEP"


@dataclass(frozen=True)
class ResourceBudget:
    ram_mb: int
    vram_mb: int
    cpu_fraction: float
    gpu_fraction: float

    def __post_init__(self) -> None:
        if self.ram_mb < 0 or self.vram_mb < 0:
            raise ValueError("memory budgets cannot be negative")
        for value, name in (
            (self.cpu_fraction, "cpu_fraction"),
            (self.gpu_fraction, "gpu_fraction"),
        ):
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError("%s must be finite and between 0 and 1" % name)


@dataclass(frozen=True)
class ResourceRequest:
    owner_id: str
    ram_mb: int = 0
    vram_mb: int = 0
    cpu_fraction: float = 0.0
    gpu_fraction: float = 0.0
    priority: int = 50
    preemptible: bool = True

    def __post_init__(self) -> None:
        if not self.owner_id:
            raise ValueError("owner_id is required")
        ResourceBudget(
            self.ram_mb,
            self.vram_mb,
            self.cpu_fraction,
            self.gpu_fraction,
        )
        if not 0 <= int(self.priority) <= 100:
            raise ValueError("priority must be in [0,100]")


@dataclass(frozen=True)
class ResourceLease:
    lease_id: str
    request: ResourceRequest
    mode: ResourceMode


@dataclass(frozen=True)
class ModeTransition:
    previous: ResourceMode
    current: ResourceMode
    revoked_lease_ids: Tuple[str, ...]


class ResourceUnavailable(RuntimeError):
    pass


class ResourceBroker:
    """In-process admission broker for replaceable runtime capabilities.

    It is intentionally ephemeral. Provider processes/resources can be rebuilt
    after restart; no identity or semantic state belongs here.
    """

    DEFAULT_BUDGETS: Mapping[ResourceMode, ResourceBudget] = {
        ResourceMode.ECO: ResourceBudget(2048, 512, 0.35, 0.15),
        ResourceMode.BALANCED: ResourceBudget(4096, 2048, 0.65, 0.45),
        ResourceMode.FULL: ResourceBudget(8192, 6144, 0.95, 0.90),
        ResourceMode.GAME: ResourceBudget(3072, 1024, 0.45, 0.20),
        ResourceMode.SLEEP: ResourceBudget(512, 0, 0.10, 0.0),
    }

    def __init__(
        self,
        *,
        mode: ResourceMode = ResourceMode.BALANCED,
        budgets: Optional[Mapping[ResourceMode, ResourceBudget]] = None,
    ) -> None:
        self.mode = ResourceMode(mode)
        self.budgets = dict(budgets or self.DEFAULT_BUDGETS)
        missing = set(ResourceMode) - set(self.budgets)
        if missing:
            raise ValueError(
                "missing resource budgets: %s"
                % ",".join(sorted(value.value for value in missing))
            )
        self._leases: Dict[str, ResourceLease] = {}

    @staticmethod
    def request_from_descriptor(
        descriptor: CapabilityDescriptor,
        *,
        priority: int = 50,
        preemptible: bool = True,
    ) -> ResourceRequest:
        profile = dict(descriptor.resource_profile or {})

        def integer(name: str) -> int:
            value = profile.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("%s must be numeric" % name)
            if not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("%s must be finite and non-negative" % name)
            return int(math.ceil(float(value)))

        def fraction(name: str) -> float:
            value = profile.get(name, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("%s must be numeric" % name)
            value = float(value)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("%s must be in [0,1]" % name)
            return value

        return ResourceRequest(
            owner_id=descriptor.provider_id,
            ram_mb=integer("ram_mb"),
            vram_mb=integer("vram_mb"),
            cpu_fraction=fraction("cpu_fraction"),
            gpu_fraction=fraction("gpu_fraction"),
            priority=priority,
            preemptible=preemptible,
        )

    def budget(self) -> ResourceBudget:
        return self.budgets[self.mode]

    def leases(self) -> Tuple[ResourceLease, ...]:
        return tuple(
            self._leases[key] for key in sorted(self._leases)
        )

    def used(self) -> ResourceBudget:
        return ResourceBudget(
            ram_mb=sum(lease.request.ram_mb for lease in self._leases.values()),
            vram_mb=sum(lease.request.vram_mb for lease in self._leases.values()),
            cpu_fraction=sum(
                lease.request.cpu_fraction for lease in self._leases.values()
            ),
            gpu_fraction=sum(
                lease.request.gpu_fraction for lease in self._leases.values()
            ),
        )

    @staticmethod
    def _fits(used: ResourceBudget, request: ResourceRequest, budget: ResourceBudget) -> bool:
        return (
            used.ram_mb + request.ram_mb <= budget.ram_mb
            and used.vram_mb + request.vram_mb <= budget.vram_mb
            and used.cpu_fraction + request.cpu_fraction
                <= budget.cpu_fraction + 1e-12
            and used.gpu_fraction + request.gpu_fraction
                <= budget.gpu_fraction + 1e-12
        )

    def can_reserve(self, request: ResourceRequest) -> bool:
        return self._fits(self.used(), request, self.budget())

    def reserve(
        self,
        lease_id: str,
        request: ResourceRequest,
    ) -> ResourceLease:
        if not lease_id:
            raise ValueError("lease_id is required")
        existing = self._leases.get(lease_id)
        if existing is not None:
            if existing.request == request:
                return existing
            raise ValueError("lease_id reused with different resource request")
        if not self.can_reserve(request):
            raise ResourceUnavailable(
                "resource request exceeds %s budget" % self.mode.value
            )
        lease = ResourceLease(lease_id, request, self.mode)
        self._leases[lease_id] = lease
        return lease

    def release(self, lease_id: str) -> bool:
        return self._leases.pop(lease_id, None) is not None

    def set_mode(
        self,
        mode: ResourceMode,
        *,
        allow_preemption: bool = True,
    ) -> ModeTransition:
        target = ResourceMode(mode)
        previous = self.mode
        if target == previous:
            return ModeTransition(previous, target, ())

        budget = self.budgets[target]
        active = list(self._leases.values())

        def total(items) -> ResourceBudget:
            return ResourceBudget(
                sum(x.request.ram_mb for x in items),
                sum(x.request.vram_mb for x in items),
                sum(x.request.cpu_fraction for x in items),
                sum(x.request.gpu_fraction for x in items),
            )

        used = total(active)
        dummy = ResourceRequest("mode-check")
        if self._fits(used, dummy, budget):
            self.mode = target
            return ModeTransition(previous, target, ())

        if not allow_preemption:
            raise ResourceUnavailable(
                "active leases exceed %s budget" % target.value
            )

        # Lowest-priority, preemptible work is removed first. Stable lease-id
        # ordering makes the decision deterministic.
        candidates = sorted(
            (
                lease
                for lease in active
                if lease.request.preemptible
            ),
            key=lambda lease: (
                lease.request.priority,
                lease.lease_id,
            ),
        )
        revoked = []
        survivors = list(active)
        for lease in candidates:
            if self._fits(total(survivors), dummy, budget):
                break
            survivors.remove(lease)
            revoked.append(lease.lease_id)

        if not self._fits(total(survivors), dummy, budget):
            raise ResourceUnavailable(
                "non-preemptible leases exceed %s budget" % target.value
            )

        for lease_id in revoked:
            self._leases.pop(lease_id, None)
        self.mode = target
        return ModeTransition(previous, target, tuple(revoked))
