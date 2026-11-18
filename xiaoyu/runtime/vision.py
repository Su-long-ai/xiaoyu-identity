from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math
import subprocess
from typing import Any, Callable, Optional, Tuple

from xiaoyu.contracts import (
    InputSourceEnvelope,
    MultimodalEvidenceRef,
    Taint,
    TrustClass,
)
from xiaoyu.contracts.common import require_aware


@dataclass(frozen=True)
class CapturedVisionFrame:
    source_id: str
    content: bytes
    captured_at: datetime
    surface: str = "vision"
    principal_hint: Optional[str] = None
    audience_scope: str = "PRIVATE"
    context_space: str = "PERSONAL"
    privacy_class: str = "OWNER_PRIVATE"
    width: Optional[int] = None
    height: Optional[int] = None
    pixel_format: str = "BYTES"

    def __post_init__(self) -> None:
        require_aware(self.captured_at, "captured_at")
        if not self.source_id:
            raise ValueError("source_id is required")
        if not isinstance(self.content, (bytes, bytearray, memoryview)):
            raise TypeError("vision frame content must be bytes-like")


class OptionalVisionDependencyUnavailable(RuntimeError):
    pass


class MssScreenCapture:
    """Thin transient screen-capture adapter over python-mss."""

    def __init__(
        self,
        *,
        monitor_index: int = 1,
        source_id: str = "screen:primary",
        surface: str = "desktop.vision",
        principal_hint: Optional[str] = "owner",
        audience_scope: str = "PRIVATE",
        context_space: str = "PERSONAL",
        privacy_class: str = "OWNER_PRIVATE",
        mss_factory=None,
    ) -> None:
        if monitor_index < 0:
            raise ValueError("monitor_index cannot be negative")
        if mss_factory is None:
            try:
                from mss import MSS  # type: ignore
            except ImportError as exc:
                raise OptionalVisionDependencyUnavailable(
                    "python-mss is not installed"
                ) from exc
            mss_factory = MSS
        self.monitor_index = int(monitor_index)
        self.source_id = source_id
        self.surface = surface
        self.principal_hint = principal_hint
        self.audience_scope = audience_scope
        self.context_space = context_space
        self.privacy_class = privacy_class
        self._factory = mss_factory
        self._capture = None

    def _instance(self):
        if self._capture is None:
            self._capture = self._factory()
        return self._capture

    def __call__(self) -> CapturedVisionFrame:
        capture = self._instance()
        monitors = capture.monitors
        if self.monitor_index >= len(monitors):
            raise RuntimeError("requested monitor is unavailable")
        shot = capture.grab(monitors[self.monitor_index])
        return CapturedVisionFrame(
            source_id=self.source_id,
            content=bytes(shot.rgb),
            captured_at=datetime.now(timezone.utc),
            surface=self.surface,
            principal_hint=self.principal_hint,
            audience_scope=self.audience_scope,
            context_space=self.context_space,
            privacy_class=self.privacy_class,
            width=int(shot.width),
            height=int(shot.height),
            pixel_format="RGB",
        )

    def close(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is None:
            return
        close = getattr(capture, "close", None)
        if callable(close):
            close()


@dataclass(frozen=True)
class VisionAnalysis:
    derived_text: str
    confidence: float
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        value = float(self.confidence)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be finite and in [0,1]")


@dataclass(frozen=True)
class VisionObservation:
    evidence: MultimodalEvidenceRef
    envelope: InputSourceEnvelope


@dataclass(frozen=True)
class VisionSensorState:
    enabled: bool
    worker_running: bool
    last_capture_at: Optional[datetime]
    last_analysis_at: Optional[datetime]
    last_content_digest: Optional[str]
    expires_at: Optional[datetime]
    last_observation: Optional[VisionObservation]


class SidecarProcessSupervisor:
    """Own one optional worker process and guarantees explicit shutdown."""

    def __init__(
        self,
        process_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.process_factory = process_factory
        self._process = None

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self) -> bool:
        if self.running:
            return False
        if self.process_factory is None:
            return False
        process = self.process_factory()
        if process is None:
            raise RuntimeError("vision process factory returned None")
        self._process = process
        return True

    def stop(self, timeout_s: float = 2.0) -> bool:
        process = self._process
        if process is None:
            return False
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=timeout_s)
                except (subprocess.TimeoutExpired, TimeoutError):
                    process.kill()
                    process.wait(timeout=timeout_s)
        finally:
            self._process = None
        return True


CaptureFn = Callable[[], Optional[CapturedVisionFrame]]
AnalyzeFn = Callable[[bytes, CapturedVisionFrame], VisionAnalysis]


class VisionSidecar:
    """Bounded transient capture -> untrusted semantic observation pipeline."""

    def __init__(
        self,
        capture: CaptureFn,
        analyze: AnalyzeFn,
        *,
        min_capture_interval_s: float = 1.0,
        sensor_ttl_s: float = 30.0,
        change_threshold: float = 0.0,
        process_supervisor: Optional[SidecarProcessSupervisor] = None,
    ) -> None:
        if min_capture_interval_s < 0:
            raise ValueError("min_capture_interval_s cannot be negative")
        if sensor_ttl_s <= 0:
            raise ValueError("sensor_ttl_s must be positive")
        if not 0.0 <= float(change_threshold) <= 1.0:
            raise ValueError("change_threshold must be in [0,1]")
        self.capture = capture
        self.analyze = analyze
        self.min_capture_interval_s = float(min_capture_interval_s)
        self.sensor_ttl_s = float(sensor_ttl_s)
        self.change_threshold = float(change_threshold)
        self.process_supervisor = (
            process_supervisor or SidecarProcessSupervisor()
        )
        self._enabled = False
        self._last_capture_at: Optional[datetime] = None
        self._last_analysis_at: Optional[datetime] = None
        self._last_digest: Optional[str] = None
        self._last_signature: Optional[Tuple[float, ...]] = None
        self._expires_at: Optional[datetime] = None
        self._last_observation: Optional[VisionObservation] = None

    @staticmethod
    def _digest(raw: bytes) -> str:
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _signature(raw: bytes, bins: int = 16) -> Tuple[float, ...]:
        if not raw:
            return tuple(0.0 for _ in range(bins))
        counts = [0] * bins
        for value in raw:
            counts[min(bins - 1, value * bins // 256)] += 1
        total = float(len(raw))
        return tuple(count / total for count in counts)

    @staticmethod
    def _distance(
        left: Tuple[float, ...],
        right: Tuple[float, ...],
    ) -> float:
        return 0.5 * sum(
            abs(a - b) for a, b in zip(left, right)
        )

    def enable(self) -> bool:
        changed = not self._enabled
        self._enabled = True
        self.process_supervisor.start()
        return changed

    def disable(self) -> bool:
        changed = self._enabled or self.process_supervisor.running
        self._enabled = False
        self.process_supervisor.stop()
        close_capture = getattr(self.capture, "close", None)
        if callable(close_capture):
            close_capture()
        self._clear_sensor_state()
        return changed

    def close(self) -> None:
        self.disable()

    def _clear_sensor_state(self) -> None:
        self._last_capture_at = None
        self._last_analysis_at = None
        self._last_digest = None
        self._last_signature = None
        self._expires_at = None
        self._last_observation = None

    def _expire_if_needed(self, now: datetime) -> None:
        if self._expires_at is not None and now >= self._expires_at:
            self._clear_sensor_state()

    def state(self, now: datetime) -> VisionSensorState:
        require_aware(now, "now")
        self._expire_if_needed(now)
        return VisionSensorState(
            enabled=self._enabled,
            worker_running=self.process_supervisor.running,
            last_capture_at=self._last_capture_at,
            last_analysis_at=self._last_analysis_at,
            last_content_digest=self._last_digest,
            expires_at=self._expires_at,
            last_observation=self._last_observation,
        )

    def poll(self, now: datetime) -> Optional[VisionObservation]:
        require_aware(now, "now")
        self._expire_if_needed(now)
        if not self._enabled:
            return None
        if (
            self._last_capture_at is not None
            and (now - self._last_capture_at).total_seconds()
                < self.min_capture_interval_s
        ):
            return None

        frame = self.capture()
        self._last_capture_at = now
        self._expires_at = now + timedelta(seconds=self.sensor_ttl_s)
        if frame is None:
            return None

        raw = bytes(frame.content)
        digest = self._digest(raw)
        signature = self._signature(raw)

        unchanged = digest == self._last_digest
        below_threshold = False
        if (
            not unchanged
            and self._last_signature is not None
            and self.change_threshold > 0
        ):
            below_threshold = (
                self._distance(self._last_signature, signature)
                < self.change_threshold
            )

        self._last_digest = digest
        self._last_signature = signature
        if unchanged or below_threshold:
            return None

        analysis = self.analyze(raw, frame)
        # Do not retain raw bytes beyond this call.
        del raw

        evidence = MultimodalEvidenceRef(
            modality="vision",
            source_id=frame.source_id,
            observed_from=frame.captured_at,
            observed_to=None,
            content_digest=digest,
            derived_text=analysis.derived_text,
            retention_class="TRANSIENT_RAW",
            privacy_class=frame.privacy_class,
        )
        event_material = (
            frame.source_id
            + "\0"
            + digest
            + "\0"
            + frame.captured_at.isoformat()
        )
        event_id = "vision:" + hashlib.sha256(
            event_material.encode("utf-8")
        ).hexdigest()[:32]
        envelope = InputSourceEnvelope(
            event_id=event_id,
            surface=frame.surface,
            source_type="vision.observation",
            principal_hint=frame.principal_hint,
            audience_scope=frame.audience_scope,
            context_space=frame.context_space,
            trust_class=TrustClass.VISION_OBSERVATION,
            taint=(
                Taint.TRANSIENT_SENSOR,
                Taint.MODEL_INFERRED,
            ),
            eligible_for_memory=False,
            correlation_id=event_id,
            observed_at=frame.captured_at,
            payload_type="application/x-xiaoyu-vision-observation+json",
            payload={
                "evidence_class": "UNTRUSTED_OBSERVATION",
                "evidence": evidence.to_dict(),
                "analysis": {
                    "confidence": float(analysis.confidence),
                    # External analyzer metadata is transient implementation
                    # detail and may contain raw-frame/debug copies. It must
                    # never cross into a persistable semantic envelope.
                    "metadata": {},
                },
            },
        )
        observation = VisionObservation(evidence, envelope)
        self._last_analysis_at = now
        self._last_observation = observation
        return observation
