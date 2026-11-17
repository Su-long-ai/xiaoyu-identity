from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import inspect
import math
from typing import Any, Callable, Optional, Tuple

from xiaoyu.contracts import (
    InputSourceEnvelope,
    Taint,
    TrustClass,
)
from xiaoyu.contracts.common import require_aware
from xiaoyu.runtime.resource_broker import ResourceBroker, ResourceRequest


VOICE_ENGINE = "PIPECAT_PIPELINE_WORKER"


@dataclass(frozen=True)
class VoiceTurnToken:
    generation: int
    started_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.started_at, "started_at")


@dataclass(frozen=True)
class VoiceTurn:
    token: VoiceTurnToken
    transcript: str
    envelope: InputSourceEnvelope


@dataclass(frozen=True)
class VoicePresentation:
    presentation_id: str
    text: str
    durable_mutation: bool = False


@dataclass(frozen=True)
class VoiceMetrics:
    speech_started_ms: float
    transcript_final_ms: float
    llm_first_output_ms: float
    tts_first_audio_ms: float

    def __post_init__(self) -> None:
        values = (
            self.speech_started_ms,
            self.transcript_final_ms,
            self.llm_first_output_ms,
            self.tts_first_audio_ms,
        )
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("voice metric timestamps must be finite")
        if not (
            self.speech_started_ms
            <= self.transcript_final_ms
            <= self.llm_first_output_ms
            <= self.tts_first_audio_ms
        ):
            raise ValueError("voice metric timestamps must be monotonic")

    @property
    def asr_ms(self) -> float:
        return self.transcript_final_ms - self.speech_started_ms

    @property
    def llm_first_ms(self) -> float:
        return self.llm_first_output_ms - self.transcript_final_ms

    @property
    def tts_first_ms(self) -> float:
        return self.tts_first_audio_ms - self.llm_first_output_ms

    @property
    def end_to_first_audio_ms(self) -> float:
        return self.tts_first_audio_ms - self.speech_started_ms


@dataclass(frozen=True)
class VoiceLatencyBudget:
    max_asr_ms: float = 1800.0
    max_llm_first_ms: float = 2500.0
    max_tts_first_ms: float = 1200.0
    max_end_to_first_audio_ms: float = 5000.0


@dataclass(frozen=True)
class VoiceResourceSample:
    ram_mb: float
    vram_mb: float
    cpu_fraction: float
    gpu_fraction: float


@dataclass(frozen=True)
class VoiceResourceBudget:
    max_ram_mb: float = 1536.0
    max_vram_mb: float = 1024.0
    max_cpu_fraction: float = 0.50
    max_gpu_fraction: float = 0.35


@dataclass(frozen=True)
class VoiceGateResult:
    passed: bool
    reasons: Tuple[str, ...]


def evaluate_voice_gate(
    metrics: VoiceMetrics,
    resources: VoiceResourceSample,
    *,
    latency: VoiceLatencyBudget = VoiceLatencyBudget(),
    resource: VoiceResourceBudget = VoiceResourceBudget(),
) -> VoiceGateResult:
    reasons = []
    comparisons = (
        ("asr_latency", metrics.asr_ms, latency.max_asr_ms),
        ("llm_first_latency", metrics.llm_first_ms, latency.max_llm_first_ms),
        ("tts_first_latency", metrics.tts_first_ms, latency.max_tts_first_ms),
        (
            "end_to_first_audio_latency",
            metrics.end_to_first_audio_ms,
            latency.max_end_to_first_audio_ms,
        ),
        ("ram_budget", resources.ram_mb, resource.max_ram_mb),
        ("vram_budget", resources.vram_mb, resource.max_vram_mb),
        ("cpu_budget", resources.cpu_fraction, resource.max_cpu_fraction),
        ("gpu_budget", resources.gpu_fraction, resource.max_gpu_fraction),
    )
    for name, actual, maximum in comparisons:
        actual = float(actual)
        maximum = float(maximum)
        if not math.isfinite(actual) or actual < 0:
            reasons.append(name + "_invalid")
        elif actual > maximum:
            reasons.append(name + "_exceeded")
    return VoiceGateResult(not reasons, tuple(reasons))


CancelFn = Callable[[], Any]


class VoiceSessionController:
    """XiaoYu semantic boundary around a Pipecat voice session."""

    def __init__(
        self,
        *,
        surface: str = "voice",
        principal_hint: Optional[str] = None,
        audience_scope: str = "PRIVATE",
        context_space: str = "PERSONAL",
    ) -> None:
        self.surface = surface
        self.principal_hint = principal_hint
        self.audience_scope = audience_scope
        self.context_space = context_space
        self._generation = 0
        self._current_token: Optional[VoiceTurnToken] = None
        self._presentation_cancel: Optional[CancelFn] = None
        self._presentation: Optional[VoicePresentation] = None

    def begin_user_turn(self, started_at: datetime) -> VoiceTurnToken:
        require_aware(started_at, "started_at")
        self.interrupt_output()
        self._generation += 1
        token = VoiceTurnToken(self._generation, started_at)
        self._current_token = token
        return token

    def final_transcript(
        self,
        token: VoiceTurnToken,
        transcript: str,
        observed_at: datetime,
    ) -> Optional[VoiceTurn]:
        require_aware(observed_at, "observed_at")
        if self._current_token != token:
            return None
        text = " ".join(str(transcript).split())
        if not text:
            # Silence / empty ASR output is not a semantic turn.
            self._current_token = None
            return None

        material = (
            str(token.generation)
            + "\0"
            + token.started_at.isoformat()
            + "\0"
            + observed_at.isoformat()
            + "\0"
            + text
        )
        event_id = "voice:" + hashlib.sha256(
            material.encode("utf-8")
        ).hexdigest()[:32]
        envelope = InputSourceEnvelope(
            event_id=event_id,
            surface=self.surface,
            source_type="audio.transcript",
            principal_hint=self.principal_hint,
            audience_scope=self.audience_scope,
            context_space=self.context_space,
            trust_class=TrustClass.AUDIO_OBSERVATION,
            taint=(
                Taint.TRANSIENT_SENSOR,
                Taint.MODEL_INFERRED,
            ),
            eligible_for_memory=False,
            correlation_id=event_id,
            observed_at=observed_at,
            payload_type="text/plain",
            payload={
                "text": text,
                "evidence_class": "UNTRUSTED_OBSERVATION",
                "voice_turn_generation": token.generation,
                "raw_audio_retained": False,
            },
        )
        self._current_token = None
        return VoiceTurn(token, text, envelope)

    def begin_tts(
        self,
        presentation_id: str,
        text: str,
        cancel: CancelFn,
    ) -> VoicePresentation:
        if not presentation_id:
            raise ValueError("presentation_id is required")
        if not str(text).strip():
            raise ValueError("TTS text is required")
        self.interrupt_output()
        presentation = VoicePresentation(
            presentation_id,
            str(text),
            False,
        )
        self._presentation = presentation
        self._presentation_cancel = cancel
        return presentation

    def interrupt_output(self) -> bool:
        cancel = self._presentation_cancel
        if cancel is None:
            return False
        try:
            cancel()
        finally:
            self._presentation_cancel = None
            self._presentation = None
        return True

    def clear_presentation(self, presentation_id: str) -> bool:
        if (
            self._presentation is None
            or self._presentation.presentation_id != presentation_id
        ):
            return False
        self._presentation = None
        self._presentation_cancel = None
        return True


class PipecatUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PipecatPipelinePolicy:
    audio_in_sample_rate: int = 16000
    audio_out_sample_rate: int = 24000
    enable_metrics: bool = True
    enable_usage_metrics: bool = True
    report_only_initial_ttfb: bool = False

    def __post_init__(self) -> None:
        if self.audio_in_sample_rate <= 0:
            raise ValueError("audio_in_sample_rate must be positive")
        if self.audio_out_sample_rate <= 0:
            raise ValueError("audio_out_sample_rate must be positive")


def build_pipecat_params(
    policy: PipecatPipelinePolicy = PipecatPipelinePolicy(),
):
    try:
        from pipecat.pipeline.worker import PipelineParams
    except ImportError as exc:
        raise PipecatUnavailable(
            "Pipecat is not installed; voice runtime stays unavailable"
        ) from exc
    return PipelineParams(
        audio_in_sample_rate=policy.audio_in_sample_rate,
        audio_out_sample_rate=policy.audio_out_sample_rate,
        enable_metrics=policy.enable_metrics,
        enable_usage_metrics=policy.enable_usage_metrics,
        report_only_initial_ttfb=policy.report_only_initial_ttfb,
    )


def pipecat_api_status() -> dict[str, Any]:
    """Probe the selected engine lazily; importing XiaoYu never requires Pipecat."""
    try:
        from pipecat.pipeline.worker import PipelineWorker, PipelineParams
    except ImportError:
        return {
            "engine": VOICE_ENGINE,
            "available": False,
            "worker": "PipelineWorker",
        }
    return {
        "engine": VOICE_ENGINE,
        "available": True,
        "worker": PipelineWorker.__name__,
        "params": PipelineParams.__name__,
    }


class PipecatVoiceBinding:
    """Lifecycle binding for an externally constructed Pipecat PipelineWorker."""

    def __init__(
        self,
        controller: VoiceSessionController,
    ) -> None:
        self.controller = controller
        self._worker = None

    def attach_worker(self, worker: Any) -> None:
        if not callable(getattr(worker, "cancel", None)):
            raise TypeError("Pipecat worker must expose cancel()")
        if not callable(getattr(worker, "has_finished", None)):
            raise TypeError("Pipecat worker must expose has_finished()")
        self._worker = worker

    @property
    def running(self) -> bool:
        worker = self._worker
        return (
            worker is not None
            and not bool(worker.has_finished())
        )

    async def cancel(self) -> bool:
        worker = self._worker
        if worker is None:
            return False
        try:
            result = worker.cancel()
            if inspect.isawaitable(result):
                await result
        finally:
            self._worker = None
        return True

    def on_user_started_speaking(self) -> bool:
        """Pipecat turn-start interruption also clears XiaoYu TTS presentation."""
        return self.controller.interrupt_output()


class VoiceRuntimeLease:
    """Bind the external Pipecat worker to the existing R13 resource policy."""

    def __init__(
        self,
        broker: ResourceBroker,
        *,
        lease_id: str = "voice-pipeline",
        request: Optional[ResourceRequest] = None,
    ) -> None:
        self.broker = broker
        self.lease_id = lease_id
        self.request = request or ResourceRequest(
            owner_id="voice-pipeline",
            ram_mb=512,
            vram_mb=0,
            cpu_fraction=0.15,
            gpu_fraction=0.0,
            priority=80,
            preemptible=True,
        )
        self._active = False

    def start(self):
        lease = self.broker.reserve(self.lease_id, self.request)
        self._active = True
        return lease

    def stop(self) -> bool:
        released = self.broker.release(self.lease_id)
        self._active = False
        return released

    @property
    def active(self) -> bool:
        return self._active
