from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from xiaoyu.contracts import Taint, TrustClass
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import (
    PipecatFrameAdapter,
    PipecatFrameTypes,
    ResourceBroker,
    ResourceMode,
    ResourceUnavailable,
    VoiceLatencyGate,
    VoiceLatencySample,
    VoiceRuntimeLease,
    VoiceSessionState,
    VoiceTranscript,
    VoiceTurnBridge,
)


T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class UserStarted:
    pass


class UserStopped:
    pass


class BotStarted:
    pass


class BotStopped:
    pass


class Interrupted:
    pass


class Interim:
    def __init__(self, text):
        self.text = text


class Final:
    def __init__(self, text, *, timestamp=T0, confidence=0.9, language="zh"):
        self.text = text
        self.timestamp = timestamp
        self.confidence = confidence
        self.language = language


FRAME_TYPES = PipecatFrameTypes(
    user_started=UserStarted,
    user_stopped=UserStopped,
    transcription=Final,
    interim_transcription=Interim,
    interruption=Interrupted,
    bot_started=BotStarted,
    bot_stopped=BotStopped,
)


class R15VoiceSpikeTests(unittest.TestCase):
    def test_silence_and_interim_do_not_create_turns(self):
        bridge = VoiceTurnBridge(session_id="voice-1")
        self.assertIsNone(
            bridge.final_transcript(
                VoiceTranscript(
                    text="   ",
                    final=True,
                    observed_at=T0,
                )
            )
        )
        self.assertIsNone(
            bridge.final_transcript(
                VoiceTranscript(
                    text="partial",
                    final=False,
                    observed_at=T0,
                )
            )
        )

        adapter = PipecatFrameAdapter(
            bridge,
            frame_types=FRAME_TYPES,
            clock=lambda: T0,
        )
        result = adapter.handle(Interim("还没说完"))
        self.assertIsNone(result.envelope)

    def test_final_transcription_becomes_untrusted_canonical_input_without_raw_audio(self):
        bridge = VoiceTurnBridge(
            session_id="voice-2",
            principal_hint="owner",
        )
        envelope = bridge.final_transcript(
            VoiceTranscript(
                text="  明天提醒我交报告  ",
                final=True,
                observed_at=T0,
                confidence=0.93,
                language="zh",
            )
        )
        self.assertIsNotNone(envelope)
        self.assertEqual(
            envelope.trust_class,
            TrustClass.AUDIO_OBSERVATION,
        )
        self.assertIn(Taint.TRANSIENT_SENSOR, envelope.taint)
        self.assertFalse(envelope.eligible_for_memory)
        self.assertEqual(
            envelope.payload["text"],
            "明天提醒我交报告",
        )
        self.assertEqual(envelope.payload["confidence"], 0.93)
        self.assertFalse(envelope.payload["raw_audio_retained"])
        self.assertNotIn("raw_audio", envelope.payload)
        self.assertNotIn("audio_bytes", envelope.payload)
        self.assertFalse(
            any(
                isinstance(value, (bytes, bytearray, memoryview))
                for value in envelope.payload.values()
            )
        )

    def test_user_barge_in_interrupts_assistant_generation_and_tts(self):
        bridge = VoiceTurnBridge(session_id="voice-3")
        bridge.assistant_started()
        self.assertEqual(
            bridge.state,
            VoiceSessionState.ASSISTANT_SPEAKING,
        )
        control = bridge.user_started()
        self.assertTrue(control.cancel_tts)
        self.assertTrue(control.cancel_generation)
        self.assertEqual(
            control.state,
            VoiceSessionState.USER_SPEAKING,
        )

    def test_pipecat_frame_adapter_maps_turn_and_transcription_frames(self):
        bridge = VoiceTurnBridge(session_id="voice-4")
        adapter = PipecatFrameAdapter(
            bridge,
            frame_types=FRAME_TYPES,
            clock=lambda: T0,
        )

        self.assertEqual(
            adapter.handle(UserStarted()).control.state,
            VoiceSessionState.USER_SPEAKING,
        )
        final = adapter.handle(Final("你好小鱼"))
        self.assertIsNotNone(final.envelope)
        self.assertEqual(final.envelope.payload["text"], "你好小鱼")
        self.assertEqual(
            adapter.handle(UserStopped()).control.state,
            VoiceSessionState.IDLE,
        )
        self.assertEqual(
            adapter.handle(BotStarted()).control.state,
            VoiceSessionState.ASSISTANT_SPEAKING,
        )
        interrupted = adapter.handle(Interrupted())
        self.assertTrue(interrupted.control.cancel_tts)
        self.assertTrue(interrupted.control.cancel_generation)
        self.assertEqual(
            interrupted.control.state,
            VoiceSessionState.CANCELLED,
        )

    def test_voice_resource_lease_respects_resource_mode(self):
        balanced = ResourceBroker(mode=ResourceMode.BALANCED)
        lease = VoiceRuntimeLease(
            balanced,
            lease_id="voice-balanced",
        )
        acquired = lease.start()
        self.assertEqual(acquired.lease_id, "voice-balanced")
        self.assertTrue(lease.active)
        self.assertTrue(lease.stop())
        self.assertFalse(lease.active)

        sleeping = ResourceBroker(mode=ResourceMode.SLEEP)
        with self.assertRaises(ResourceUnavailable):
            VoiceRuntimeLease(
                sleeping,
                lease_id="voice-sleep",
            ).start()

    def test_voice_latency_gate_is_measured_not_assumed(self):
        sample = VoiceLatencySample(
            transcript_final_at=T0,
            tts_first_audio_at=T0 + timedelta(milliseconds=420),
        )
        self.assertEqual(sample.first_audio_ms, 420.0)
        self.assertTrue(
            VoiceLatencyGate(500).allowed(sample)
        )
        self.assertFalse(
            VoiceLatencyGate(300).allowed(sample)
        )

    def test_voice_bridge_never_writes_semantic_database_by_itself(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)

            def counts():
                with db.transaction() as conn:
                    return {
                        name: conn.execute(
                            "SELECT COUNT(*) FROM %s" % name
                        ).fetchone()[0]
                        for name in (
                            "canonical_events",
                            "claims",
                            "temporal_facts",
                            "purposes",
                            "effects",
                        )
                    }

            before = counts()
            bridge = VoiceTurnBridge(session_id="voice-5")
            adapter = PipecatFrameAdapter(
                bridge,
                frame_types=FRAME_TYPES,
                clock=lambda: T0,
            )
            adapter.handle(UserStarted())
            result = adapter.handle(Final("记住这句话"))
            self.assertIsNotNone(result.envelope)
            adapter.handle(UserStopped())
            self.assertEqual(counts(), before)


if __name__ == "__main__":
    unittest.main()
