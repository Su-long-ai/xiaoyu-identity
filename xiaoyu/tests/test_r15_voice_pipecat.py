from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import TrustClass, Taint
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import (
    PipecatPipelinePolicy,
    PipecatUnavailable,
    PipecatVoiceBinding,
    ResourceBroker,
    ResourceMode,
    ResourceUnavailable,
    VoiceLatencyBudget,
    VoiceMetrics,
    VoiceResourceBudget,
    VoiceResourceSample,
    VoiceRuntimeLease,
    VoiceSessionController,
    build_pipecat_params,
    evaluate_voice_gate,
    pipecat_api_status,
)


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)


class FakeWorker:
    def __init__(self):
        self.finished = False
        self.cancel_calls = 0

    def has_finished(self):
        return self.finished

    async def cancel(self):
        self.cancel_calls += 1
        self.finished = True


class R15VoicePipecatTests(unittest.IsolatedAsyncioTestCase):
    def test_silence_is_not_a_semantic_turn(self):
        controller = VoiceSessionController(
            principal_hint="owner"
        )
        token = controller.begin_user_turn(T0)
        turn = controller.final_transcript(
            token,
            "   \n  ",
            T0 + timedelta(seconds=1),
        )
        self.assertIsNone(turn)

    def test_stale_asr_token_is_ignored_after_newer_user_turn(self):
        controller = VoiceSessionController(
            principal_hint="owner"
        )
        old = controller.begin_user_turn(T0)
        new = controller.begin_user_turn(
            T0 + timedelta(seconds=1)
        )
        self.assertIsNone(
            controller.final_transcript(
                old,
                "stale transcript",
                T0 + timedelta(seconds=2),
            )
        )
        fresh = controller.final_transcript(
            new,
            "fresh transcript",
            T0 + timedelta(seconds=2),
        )
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.transcript, "fresh transcript")

    def test_valid_transcript_is_untrusted_audio_observation(self):
        controller = VoiceSessionController(
            surface="desktop.voice",
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
        )
        token = controller.begin_user_turn(T0)
        turn = controller.final_transcript(
            token,
            "  你好， 小鱼  ",
            T0 + timedelta(milliseconds=800),
        )
        self.assertIsNotNone(turn)
        self.assertEqual(turn.transcript, "你好， 小鱼")
        envelope = turn.envelope
        self.assertEqual(
            envelope.trust_class,
            TrustClass.AUDIO_OBSERVATION,
        )
        self.assertIn(Taint.TRANSIENT_SENSOR, envelope.taint)
        self.assertIn(Taint.MODEL_INFERRED, envelope.taint)
        self.assertFalse(envelope.eligible_for_memory)
        self.assertEqual(
            envelope.payload["evidence_class"],
            "UNTRUSTED_OBSERVATION",
        )
        self.assertEqual(
            envelope.payload["voice_turn_generation"],
            token.generation,
        )
        self.assertFalse(envelope.payload["raw_audio_retained"])
        self.assertNotIn("raw_audio", envelope.payload)
        self.assertNotIn("audio_bytes", envelope.payload)
        self.assertEqual(
            envelope.principal_hint,
            "owner",
        )

    def test_tts_is_presentation_only_and_interrupts_once(self):
        controller = VoiceSessionController()
        calls = []

        presentation = controller.begin_tts(
            "tts-1",
            "hello",
            lambda: calls.append("cancel"),
        )
        self.assertFalse(presentation.durable_mutation)
        self.assertTrue(controller.interrupt_output())
        self.assertEqual(calls, ["cancel"])
        self.assertFalse(controller.interrupt_output())
        self.assertEqual(calls, ["cancel"])

    def test_new_user_turn_barge_in_cancels_active_tts(self):
        controller = VoiceSessionController()
        calls = []
        controller.begin_tts(
            "tts-1",
            "long answer",
            lambda: calls.append("cancel"),
        )
        token = controller.begin_user_turn(T0)
        self.assertEqual(calls, ["cancel"])
        self.assertEqual(token.generation, 1)

    def test_voice_latency_and_resource_gate(self):
        good = VoiceMetrics(
            speech_started_ms=0,
            transcript_final_ms=700,
            llm_first_output_ms=1700,
            tts_first_audio_ms=2200,
        )
        resources = VoiceResourceSample(
            ram_mb=600,
            vram_mb=200,
            cpu_fraction=0.2,
            gpu_fraction=0.1,
        )
        result = evaluate_voice_gate(good, resources)
        self.assertTrue(result.passed)
        self.assertEqual(result.reasons, ())

        bad = VoiceMetrics(
            speech_started_ms=0,
            transcript_final_ms=2200,
            llm_first_output_ms=5100,
            tts_first_audio_ms=6800,
        )
        overloaded = VoiceResourceSample(
            ram_mb=2000,
            vram_mb=1500,
            cpu_fraction=0.8,
            gpu_fraction=0.6,
        )
        result = evaluate_voice_gate(
            bad,
            overloaded,
            latency=VoiceLatencyBudget(),
            resource=VoiceResourceBudget(),
        )
        self.assertFalse(result.passed)
        for expected in (
            "asr_latency_exceeded",
            "llm_first_latency_exceeded",
            "tts_first_latency_exceeded",
            "end_to_first_audio_latency_exceeded",
            "ram_budget_exceeded",
            "vram_budget_exceeded",
            "cpu_budget_exceeded",
            "gpu_budget_exceeded",
        ):
            self.assertIn(expected, result.reasons)

    def test_metrics_reject_non_monotonic_timestamps(self):
        with self.assertRaises(ValueError):
            VoiceMetrics(
                speech_started_ms=10,
                transcript_final_ms=5,
                llm_first_output_ms=20,
                tts_first_audio_ms=30,
            )

    async def test_pipecat_worker_binding_is_cancellable(self):
        controller = VoiceSessionController()
        binding = PipecatVoiceBinding(controller)
        worker = FakeWorker()
        binding.attach_worker(worker)
        self.assertTrue(binding.running)
        self.assertTrue(await binding.cancel())
        self.assertEqual(worker.cancel_calls, 1)
        self.assertFalse(binding.running)
        self.assertFalse(await binding.cancel())

    async def test_pipecat_cancel_invalidates_active_asr_turn(self):
        controller = VoiceSessionController(
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
        )
        token = controller.begin_user_turn(T0)
        binding = PipecatVoiceBinding(controller)
        worker = FakeWorker()
        binding.attach_worker(worker)

        self.assertTrue(await binding.cancel())
        late = controller.final_transcript(
            token,
            "SYNTHETIC_PRIVATE_LATE_TRANSCRIPT",
            T0 + timedelta(seconds=2),
        )
        self.assertIsNone(late)

    def test_pipecat_barge_in_invalidates_previous_asr_turn(self):
        controller = VoiceSessionController(
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
        )
        old = controller.begin_user_turn(T0)
        binding = PipecatVoiceBinding(controller)

        binding.on_user_started_speaking()
        late = controller.final_transcript(
            old,
            "SYNTHETIC_PRIVATE_STALE_BARGE_IN_TRANSCRIPT",
            T0 + timedelta(seconds=1),
        )
        self.assertIsNone(late)

    def test_pipecat_binding_rejects_wrong_worker_shape(self):
        binding = PipecatVoiceBinding(
            VoiceSessionController()
        )
        with self.assertRaises(TypeError):
            binding.attach_worker(object())

    def test_pipecat_policy_uses_current_worker_defaults(self):
        policy = PipecatPipelinePolicy()
        self.assertEqual(policy.audio_in_sample_rate, 16000)
        self.assertEqual(policy.audio_out_sample_rate, 24000)
        self.assertTrue(policy.enable_metrics)
        self.assertTrue(policy.enable_usage_metrics)

        status = pipecat_api_status()
        self.assertEqual(
            status["engine"],
            "PIPECAT_PIPELINE_WORKER",
        )
        self.assertEqual(status["worker"], "PipelineWorker")
        if status["available"]:
            params = build_pipecat_params(policy)
            self.assertEqual(params.audio_in_sample_rate, 16000)
            self.assertEqual(params.audio_out_sample_rate, 24000)
            self.assertTrue(params.enable_metrics)
            self.assertTrue(params.enable_usage_metrics)
        else:
            with self.assertRaises(PipecatUnavailable):
                build_pipecat_params(policy)


    def test_voice_worker_uses_existing_resource_broker_policy(self):
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

    def test_voice_session_mechanics_do_not_mutate_semantic_db(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            with db.transaction() as conn:
                before = {
                    table: conn.execute(
                        "SELECT COUNT(*) FROM %s" % table
                    ).fetchone()[0]
                    for table in (
                        "canonical_events",
                        "claims",
                        "temporal_facts",
                        "relationship_state",
                        "promises",
                        "purposes",
                        "effects",
                    )
                }

            controller = VoiceSessionController(
                principal_hint="owner"
            )
            token = controller.begin_user_turn(T0)
            turn = controller.final_transcript(
                token,
                "hello",
                T0 + timedelta(seconds=1),
            )
            self.assertIsNotNone(turn)
            controller.begin_tts(
                "tts-1",
                "reply",
                lambda: None,
            )
            controller.interrupt_output()

            with db.transaction() as conn:
                after = {
                    table: conn.execute(
                        "SELECT COUNT(*) FROM %s" % table
                    ).fetchone()[0]
                    for table in before
                }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
