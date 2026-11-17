from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ResourceMode(str, Enum):
    ECO = "ECO"
    BALANCED = "BALANCED"
    FULL = "FULL"
    GAME = "GAME"
    SLEEP = "SLEEP"


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_available_mb: Optional[float] = None
    process_rss_mb: Optional[float] = None
    battery_percent: Optional[float] = None
    power_plugged: Optional[bool] = None
    gpu_util_percent: Optional[float] = None
    vram_used_mb: Optional[float] = None
    vram_total_mb: Optional[float] = None
    gpu_power_w: Optional[float] = None


@dataclass(frozen=True)
class ResourceRequest:
    capability: str
    background: bool = False
    requires_gpu: bool = False
    requires_network: bool = False
    estimated_ram_mb: float = 0.0
    estimated_vram_mb: float = 0.0


@dataclass(frozen=True)
class ResourceDecision:
    allowed: bool
    mode: ResourceMode
    reasons: tuple[str, ...]
    snapshot: ResourceSnapshot


@dataclass(frozen=True)
class ResourcePolicy:
    max_cpu_percent: float
    max_memory_percent: float
    max_gpu_percent: float
    max_background_ram_mb: float
    max_background_vram_mb: float
    allow_background: bool
    allow_gpu: bool
    allow_network: bool


DEFAULT_POLICIES = {
    ResourceMode.ECO: ResourcePolicy(
        max_cpu_percent=75.0,
        max_memory_percent=88.0,
        max_gpu_percent=75.0,
        max_background_ram_mb=768.0,
        max_background_vram_mb=512.0,
        allow_background=True,
        allow_gpu=True,
        allow_network=True,
    ),
    ResourceMode.BALANCED: ResourcePolicy(
        max_cpu_percent=90.0,
        max_memory_percent=92.0,
        max_gpu_percent=90.0,
        max_background_ram_mb=2048.0,
        max_background_vram_mb=2048.0,
        allow_background=True,
        allow_gpu=True,
        allow_network=True,
    ),
    ResourceMode.FULL: ResourcePolicy(
        max_cpu_percent=98.0,
        max_memory_percent=97.0,
        max_gpu_percent=98.0,
        max_background_ram_mb=8192.0,
        max_background_vram_mb=8192.0,
        allow_background=True,
        allow_gpu=True,
        allow_network=True,
    ),
    ResourceMode.GAME: ResourcePolicy(
        max_cpu_percent=55.0,
        max_memory_percent=85.0,
        max_gpu_percent=35.0,
        max_background_ram_mb=512.0,
        max_background_vram_mb=0.0,
        allow_background=True,
        allow_gpu=False,
        allow_network=True,
    ),
    ResourceMode.SLEEP: ResourcePolicy(
        max_cpu_percent=20.0,
        max_memory_percent=80.0,
        max_gpu_percent=0.0,
        max_background_ram_mb=128.0,
        max_background_vram_mb=0.0,
        allow_background=False,
        allow_gpu=False,
        allow_network=False,
    ),
}


class OptionalResourceDependencyUnavailable(RuntimeError):
    pass


class PsutilResourceSampler:
    """Thin adapter over psutil; owns no scheduling or policy."""

    def __init__(self, module=None) -> None:
        if module is None:
            try:
                import psutil as module  # type: ignore
            except ImportError as exc:
                raise OptionalResourceDependencyUnavailable(
                    "psutil is required for host CPU/RAM/battery sampling"
                ) from exc
        self.psutil = module

    def sample(self) -> dict:
        memory = self.psutil.virtual_memory()
        battery_fn = getattr(self.psutil, "sensors_battery", None)
        battery = battery_fn() if callable(battery_fn) else None
        process = self.psutil.Process()
        rss = process.memory_info().rss
        return {
            "cpu_percent": float(
                self.psutil.cpu_percent(interval=None)
            ),
            "memory_percent": float(memory.percent),
            "memory_available_mb": float(memory.available)
            / (1024.0 * 1024.0),
            "process_rss_mb": float(rss) / (1024.0 * 1024.0),
            "battery_percent": (
                None if battery is None else float(battery.percent)
            ),
            "power_plugged": (
                None
                if battery is None
                else (
                    None
                    if battery.power_plugged is None
                    else bool(battery.power_plugged)
                )
            ),
        }


class NvmlResourceSampler:
    """Thin adapter over NVIDIA's NVML Python binding (pynvml)."""

    def __init__(self, module=None, *, device_index: int = 0) -> None:
        if module is None:
            try:
                import pynvml as module  # type: ignore
            except ImportError as exc:
                raise OptionalResourceDependencyUnavailable(
                    "nvidia-ml-py is required for NVIDIA GPU sampling"
                ) from exc
        self.nvml = module
        self.device_index = int(device_index)
        self._initialized = False

    def _handle(self):
        if not self._initialized:
            self.nvml.nvmlInit()
            self._initialized = True
        return self.nvml.nvmlDeviceGetHandleByIndex(
            self.device_index
        )

    def sample(self) -> dict:
        handle = self._handle()
        utilization = self.nvml.nvmlDeviceGetUtilizationRates(handle)
        memory = self.nvml.nvmlDeviceGetMemoryInfo(handle)
        power = None
        try:
            power = self.nvml.nvmlDeviceGetPowerUsage(handle)
        except Exception:
            power = None
        return {
            "gpu_util_percent": float(utilization.gpu),
            "vram_used_mb": float(memory.used) / (1024.0 * 1024.0),
            "vram_total_mb": float(memory.total) / (1024.0 * 1024.0),
            "gpu_power_w": (
                None if power is None else float(power) / 1000.0
            ),
        }

    def close(self) -> None:
        if self._initialized:
            try:
                self.nvml.nvmlShutdown()
            finally:
                self._initialized = False


class CompositeResourceSampler:
    def __init__(self, *samplers) -> None:
        self.samplers = tuple(samplers)

    def sample(self) -> ResourceSnapshot:
        values = {}
        for sampler in self.samplers:
            values.update(sampler.sample())
        allowed = {
            field
            for field in ResourceSnapshot.__dataclass_fields__
        }
        return ResourceSnapshot(
            **{
                key: value
                for key, value in values.items()
                if key in allowed
            }
        )


class ResourceBroker:
    """XiaoYu policy over externally sampled resource telemetry."""

    def __init__(
        self,
        sampler,
        *,
        mode: ResourceMode = ResourceMode.BALANCED,
        policies=None,
    ) -> None:
        self.sampler = sampler
        self.mode = ResourceMode(mode)
        self.policies = dict(policies or DEFAULT_POLICIES)

    def set_mode(self, mode: ResourceMode) -> None:
        self.mode = ResourceMode(mode)

    def snapshot(self) -> ResourceSnapshot:
        value = self.sampler.sample()
        if not isinstance(value, ResourceSnapshot):
            raise TypeError(
                "resource sampler must return ResourceSnapshot"
            )
        return value

    def admit(
        self,
        request: ResourceRequest,
        *,
        snapshot: Optional[ResourceSnapshot] = None,
    ) -> ResourceDecision:
        current = snapshot or self.snapshot()
        policy = self.policies[self.mode]
        reasons = []

        if request.background and not policy.allow_background:
            reasons.append("background_disabled")
        if request.requires_gpu and not policy.allow_gpu:
            reasons.append("gpu_disabled")
        if request.requires_network and not policy.allow_network:
            reasons.append("network_disabled")

        if (
            request.background
            and request.estimated_ram_mb
                > policy.max_background_ram_mb
        ):
            reasons.append("background_ram_budget_exceeded")
        if (
            request.background
            and request.estimated_vram_mb
                > policy.max_background_vram_mb
        ):
            reasons.append("background_vram_budget_exceeded")

        if (
            current.cpu_percent is not None
            and current.cpu_percent > policy.max_cpu_percent
        ):
            reasons.append("cpu_pressure")
        if (
            current.memory_percent is not None
            and current.memory_percent > policy.max_memory_percent
        ):
            reasons.append("memory_pressure")
        if (
            request.requires_gpu
            and current.gpu_util_percent is not None
            and current.gpu_util_percent > policy.max_gpu_percent
        ):
            reasons.append("gpu_pressure")

        # On low battery ECO becomes stricter for background network/GPU work,
        # without changing foreground user intent.
        if (
            self.mode is ResourceMode.ECO
            and request.background
            and current.power_plugged is False
            and current.battery_percent is not None
            and current.battery_percent < 20.0
            and (request.requires_gpu or request.requires_network)
        ):
            reasons.append("low_battery_background_work")

        return ResourceDecision(
            allowed=not reasons,
            mode=self.mode,
            reasons=tuple(reasons),
            snapshot=current,
        )
