from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Optional

from xiaoyu.contracts import InputSourceEnvelope, Taint, TrustClass
from xiaoyu.contracts.common import require_aware
from xiaoyu.runtime.resource_broker import (
    ResourceBroker,
    ResourceRequest,
)


class OptionalVoiceDependencyUnavailable(RuntimeError):
    pass


class VoiceSessionState(str, Enum):
    IDLE = "IDLE"
    USER_SPEAKING = "USER_SPEAKING"
    ASSISTANT_SPEAKING = "ASSISTANT_SPEAKING"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class VoiceTranscript:
    text: str
    final: bool
    observed_at: datetime
    confidence: Optional[float] = None
    language: Optional[str] = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if self.confidence is not None:
            value = float(self.confidence)
            if not 0.0 <= value <= 1.0:
                raise ValueError("confidence must be in [0,1]")


@dataclass(frozen=True)
class VoiceControl:
    state: VoiceSessionState
    cancel_tts: bool = False
    cancel_generation: bool = False


@dataclass(frozen=True)
class VoiceFrameResult:
    control: VoiceControl
    envelope: Optional[InputSourceEnvelope] = None


@dataclass(frozen=True)
class VoiceLatencySample:
    transcript_final_at: datetime
    tts_first_audio_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.transcript_final_at, "transcript_final_at")
        require_aware(self.tts_first_audio_at, "tts_first_audio_at")
        if self.tts_first_audio_at < self.transcript_final_at:
            raise ValueError("TTS audio cannot precede final transcription")

    @property
    def first_audio_ms(self) -> float:
        return (
            self.tts_first_audio_at - self.transcript_final_at
        ).total_seconds() * 1000.0


class VoiceLatencyGate:
    def __init__(self, max_first_audio_ms: float) -> None:
        if max_first_audio_ms <= 0:
            raise ValueError("max_first_audio_ms must be positive")
        self.max_first_audio_ms = float(max_first_audio_ms)

    def allowed(self, sample: VoiceLatencySample) -> bool:
        return sample.first_audio_ms <= self.max_first_audio_ms


class VoiceTurnBridge:
    """Pipecat-facing turn bridge; owns no ASR/TTS/VAD implementation."""

    def __init__(
        self,
        *,
        session_id: str,
        principal_hint: Optional[str] = "owner",
        surface: str = "voice",
        audience_scope: str = "PRIVATE",
        context_space: str = "PERSONAL",
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        self.session_id = session_id
        self.principal_hint = principal_hint
        self.surface = surface
        self.audience_scope = audience_scope
        self.context_space = context_space
        self.state = VoiceSessionState.IDLE
        self._turn_sequence = 0

    def user_started(self) -> VoiceControl:
        cancel = self.state is VoiceSessionState.ASSISTANT_SPEAKING
        self.state = VoiceSessionState.USER_SPEAKING
        return VoiceControl(
            self.state,
            cancel_tts=cancel,
            cancel_generation=cancel,
        )

    def user_stopped(self) -> VoiceControl:
        if self.state is VoiceSessionState.USER_SPEAKING:
            self.state = VoiceSessionState.IDLE
        return VoiceControl(self.state)

    def assistant_started(self) -> VoiceControl:
        self.state = VoiceSessionState.ASSISTANT_SPEAKING
        return VoiceControl(self.state)

    def assistant_stopped(self) -> VoiceControl:
        if self.state is VoiceSessionState.ASSISTANT_SPEAKING:
            self.state = VoiceSessionState.IDLE
        return VoiceControl(self.state)

    def cancel(self) -> VoiceControl:
        self.state = VoiceSessionState.CANCELLED
        return VoiceControl(
            self.state,
            cancel_tts=True,
            cancel_generation=True,
        )

    def final_transcript(
        self,
        transcript: VoiceTranscript,
    ) -> Optional[InputSourceEnvelope]:
        if not transcript.final:
            return None
        text = transcript.text.strip()
        if not text:
            return None
        self._turn_sequence += 1
        material = (
            self.session_id
            + "\0"
            + str(self._turn_sequence)
            + "\0"
            + transcript.observed_at.astimezone(timezone.utc).isoformat()
            + "\0"
            + text
        )
        digest = hashlib.sha256(
            material.encode("utf-8")
        ).hexdigest()
        event_id = "voice:" + digest[:32]
        return InputSourceEnvelope(
            event_id=event_id,
            surface=self.surface,
            source_type="voice.transcription",
            principal_hint=self.principal_hint,
            audience_scope=self.audience_scope,
            context_space=self.context_space,
            # ASR output is sensor-derived and must not directly mutate
            # authoritative memory even on an authenticated owner device.
            trust_class=TrustClass.AUDIO_OBSERVATION,
            taint=(Taint.TRANSIENT_SENSOR,),
            eligible_for_memory=False,
            correlation_id="voice-session:" + self.session_id,
            observed_at=transcript.observed_at,
            payload_type="application/x-xiaoyu-voice-turn+json",
            payload={
                "text": text,
                "confidence": transcript.confidence,
                "language": transcript.language,
                "final": True,
                "raw_audio_retained": False,
            },
        )


@dataclass(frozen=True)
class PipecatFrameTypes:
    user_started: type
    user_stopped: type
    transcription: type
    interim_transcription: type
    interruption: type
    bot_started: Optional[type] = None
    bot_stopped: Optional[type] = None


def load_pipecat_frame_types() -> PipecatFrameTypes:
    try:
        from pipecat.frames.frames import (  # type: ignore
            BotStartedSpeakingFrame,
            BotStoppedSpeakingFrame,
            InterimTranscriptionFrame,
            InterruptionFrame,
            TranscriptionFrame,
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )
    except ImportError as exc:
        raise OptionalVoiceDependencyUnavailable(
            "pipecat-ai is not installed"
        ) from exc
    return PipecatFrameTypes(
        user_started=UserStartedSpeakingFrame,
        user_stopped=UserStoppedSpeakingFrame,
        transcription=TranscriptionFrame,
        interim_transcription=InterimTranscriptionFrame,
        interruption=InterruptionFrame,
        bot_started=BotStartedSpeakingFrame,
        bot_stopped=BotStoppedSpeakingFrame,
    )


class PipecatFrameAdapter:
    """Translate Pipecat frames into XiaoYu turn/control events."""

    def __init__(
        self,
        bridge: VoiceTurnBridge,
        *,
        frame_types: Optional[PipecatFrameTypes] = None,
        clock=None,
    ) -> None:
        self.bridge = bridge
        self.frame_types = frame_types or load_pipecat_frame_types()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def handle(self, frame: Any) -> VoiceFrameResult:
        types = self.frame_types
        if isinstance(frame, types.user_started):
            return VoiceFrameResult(self.bridge.user_started())
        if isinstance(frame, types.user_stopped):
            return VoiceFrameResult(self.bridge.user_stopped())
        if types.bot_started is not None and isinstance(
            frame, types.bot_started
        ):
            return VoiceFrameResult(self.bridge.assistant_started())
        if types.bot_stopped is not None and isinstance(
            frame, types.bot_stopped
        ):
            return VoiceFrameResult(self.bridge.assistant_stopped())
        if isinstance(frame, types.interruption):
            return VoiceFrameResult(self.bridge.cancel())
        if isinstance(frame, types.interim_transcription):
            return VoiceFrameResult(
                VoiceControl(self.bridge.state),
                None,
            )
        if isinstance(frame, types.transcription):
            observed_at = getattr(frame, "timestamp", None)
            if not isinstance(observed_at, datetime):
                observed_at = self.clock()
            confidence = getattr(frame, "confidence", None)
            if confidence is not None:
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = None
            transcript = VoiceTranscript(
                text=str(getattr(frame, "text", "") or ""),
                final=True,
                observed_at=observed_at,
                confidence=confidence,
                language=getattr(frame, "language", None),
            )
            return VoiceFrameResult(
                VoiceControl(self.bridge.state),
                self.bridge.final_transcript(transcript),
            )
        return VoiceFrameResult(
            VoiceControl(self.bridge.state),
            None,
        )


class VoiceRuntimeLease:
    """Resource lease for the external Pipecat voice pipeline."""

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
        lease = self.broker.reserve(
            self.lease_id,
            self.request,
        )
        self._active = True
        return lease

    def stop(self) -> bool:
        released = self.broker.release(self.lease_id)
        self._active = False
        return released

    @property
    def active(self) -> bool:
        return self._active
