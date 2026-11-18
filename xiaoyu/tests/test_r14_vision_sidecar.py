from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import TrustClass, Taint
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import (
    CapturedVisionFrame,
    SidecarProcessSupervisor,
    VisionAnalysis,
    VisionSidecar,
)


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)


class FakeProcess:
    def __init__(self, *, timeout_once=False):
        self.alive = True
        self.terminated = False
        self.killed = False
        self.wait_calls = 0
        self.timeout_once = timeout_once

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.alive = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.timeout_once and self.wait_calls == 1:
            raise TimeoutError("synthetic stubborn process")
        self.alive = False
        return 0


class R14VisionSidecarTests(unittest.TestCase):
    def _frame(self, content=b"frame-A", at=T0):
        return CapturedVisionFrame(
            source_id="screen:primary",
            content=content,
            captured_at=at,
            surface="desktop.vision",
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            privacy_class="OWNER_PRIVATE",
        )

    def test_off_never_captures_or_analyzes(self):
        calls = {"capture": 0, "analyze": 0}

        def capture():
            calls["capture"] += 1
            return self._frame()

        def analyze(raw, frame):
            calls["analyze"] += 1
            return VisionAnalysis("should-not-run", 1.0, {})

        sidecar = VisionSidecar(capture, analyze)
        self.assertIsNone(sidecar.poll(T0))
        self.assertEqual(calls, {"capture": 0, "analyze": 0})
        self.assertFalse(sidecar.state(T0).enabled)

    def test_min_interval_bounds_capture(self):
        calls = []

        def capture():
            calls.append("capture")
            return self._frame()

        sidecar = VisionSidecar(
            capture,
            lambda raw, frame: VisionAnalysis("first", 0.8, {}),
            min_capture_interval_s=5.0,
        )
        sidecar.enable()
        self.assertIsNotNone(sidecar.poll(T0))
        self.assertIsNone(
            sidecar.poll(T0 + timedelta(seconds=1))
        )
        self.assertEqual(calls, ["capture"])
        self.assertIsNone(
            sidecar.poll(T0 + timedelta(seconds=5))
        )
        self.assertEqual(calls, ["capture", "capture"])

    def test_static_screen_suppresses_repeated_analyzer_calls(self):
        analyzer_calls = []

        def analyze(raw, frame):
            analyzer_calls.append(bytes(raw))
            return VisionAnalysis("static desktop", 0.9, {})

        sidecar = VisionSidecar(
            lambda: self._frame(b"same-screen"),
            analyze,
            min_capture_interval_s=0,
        )
        sidecar.enable()
        first = sidecar.poll(T0)
        second = sidecar.poll(T0 + timedelta(seconds=1))
        third = sidecar.poll(T0 + timedelta(seconds=2))
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNone(third)
        self.assertEqual(analyzer_calls, [b"same-screen"])

    def test_changed_frame_emits_untrusted_observation_without_raw_media(self):
        frames = [
            self._frame(b"secret-raw-image-bytes", T0),
            self._frame(
                b"very-different-frame-content",
                T0 + timedelta(seconds=2),
            ),
        ]

        def capture():
            return frames.pop(0)

        sidecar = VisionSidecar(
            capture,
            lambda raw, frame: VisionAnalysis(
                "A settings window is visible.",
                0.72,
                {"objects": ["window"]},
            ),
            min_capture_interval_s=0,
        )
        sidecar.enable()
        first = sidecar.poll(T0)
        second = sidecar.poll(T0 + timedelta(seconds=2))

        for observation in (first, second):
            self.assertIsNotNone(observation)
            self.assertEqual(
                observation.envelope.trust_class,
                TrustClass.VISION_OBSERVATION,
            )
            self.assertIn(
                Taint.TRANSIENT_SENSOR,
                observation.envelope.taint,
            )
            self.assertIn(
                Taint.MODEL_INFERRED,
                observation.envelope.taint,
            )
            self.assertFalse(
                observation.envelope.eligible_for_memory
            )
            self.assertEqual(
                observation.envelope.payload["evidence_class"],
                "UNTRUSTED_OBSERVATION",
            )
            encoded = json.dumps(
                observation.envelope.to_dict(),
                ensure_ascii=False,
            )
            self.assertNotIn(
                "secret-raw-image-bytes",
                encoded,
            )
            self.assertNotIn(
                "very-different-frame-content",
                encoded,
            )
            self.assertEqual(
                observation.evidence.retention_class,
                "TRANSIENT_RAW",
            )

    def test_external_analyzer_metadata_cannot_retain_raw_frame_copy(self):
        secret=b"SYNTHETIC_OWNER_PRIVATE_RAW_FRAME"
        sidecar = VisionSidecar(
            lambda: self._frame(secret, T0),
            lambda raw, frame: VisionAnalysis(
                "A private frame was analyzed.",
                0.91,
                {
                    "debug_raw_frame": bytes(raw).decode("ascii"),
                    "backend_trace": "prefix-" + bytes(raw).decode("ascii"),
                },
            ),
            min_capture_interval_s=0,
        )
        sidecar.enable()
        observation=sidecar.poll(T0)
        self.assertIsNotNone(observation)
        encoded=json.dumps(
            observation.envelope.to_dict(),
            ensure_ascii=False,
        )
        self.assertNotIn(secret.decode("ascii"), encoded)
        sidecar.close()

    def test_small_change_can_be_suppressed_by_change_selector(self):
        frames = [
            self._frame(bytes([0] * 100 + [255] * 100), T0),
            self._frame(
                bytes([0] * 99 + [1] + [255] * 100),
                T0 + timedelta(seconds=1),
            ),
        ]
        calls = []
        sidecar = VisionSidecar(
            lambda: frames.pop(0),
            lambda raw, frame: (
                calls.append(1)
                or VisionAnalysis("changed", 0.8, {})
            ),
            min_capture_interval_s=0,
            change_threshold=0.02,
        )
        sidecar.enable()
        self.assertIsNotNone(sidecar.poll(T0))
        self.assertIsNone(
            sidecar.poll(T0 + timedelta(seconds=1))
        )
        self.assertEqual(len(calls), 1)

    def test_disable_during_analysis_discards_inflight_private_observation(self):
        holder = {}

        def analyze(raw, frame):
            holder["sidecar"].disable()
            return VisionAnalysis(
                "SYNTHETIC_PRIVATE_INFLIGHT_OBSERVATION",
                0.95,
                {},
            )

        sidecar = VisionSidecar(
            lambda: self._frame(
                b"SYNTHETIC_PRIVATE_FRAME_DURING_DISABLE",
                T0,
            ),
            analyze,
            min_capture_interval_s=0,
        )
        holder["sidecar"] = sidecar
        sidecar.enable()
        observation = sidecar.poll(T0)
        self.assertIsNone(observation)
        state = sidecar.state(T0)
        self.assertFalse(state.enabled)
        self.assertIsNone(state.last_observation)
        self.assertIsNone(state.last_content_digest)

    def test_sensor_state_expires_by_ttl(self):
        sidecar = VisionSidecar(
            lambda: self._frame(),
            lambda raw, frame: VisionAnalysis("visible", 0.9, {}),
            min_capture_interval_s=0,
            sensor_ttl_s=5,
        )
        sidecar.enable()
        self.assertIsNotNone(sidecar.poll(T0))
        live = sidecar.state(T0 + timedelta(seconds=4))
        self.assertIsNotNone(live.last_observation)
        self.assertIsNotNone(live.last_content_digest)

        expired = sidecar.state(T0 + timedelta(seconds=5))
        self.assertTrue(expired.enabled)
        self.assertIsNone(expired.last_observation)
        self.assertIsNone(expired.last_content_digest)
        self.assertIsNone(expired.expires_at)

    def test_disable_stops_capture_and_worker(self):
        process = FakeProcess()
        supervisor = SidecarProcessSupervisor(lambda: process)
        calls = []
        sidecar = VisionSidecar(
            lambda: calls.append("capture") or self._frame(),
            lambda raw, frame: VisionAnalysis("visible", 1.0, {}),
            min_capture_interval_s=0,
            process_supervisor=supervisor,
        )
        sidecar.enable()
        self.assertTrue(supervisor.running)
        sidecar.poll(T0)
        self.assertEqual(calls, ["capture"])
        self.assertTrue(sidecar.disable())
        self.assertTrue(process.terminated)
        self.assertFalse(supervisor.running)
        self.assertIsNone(
            sidecar.poll(T0 + timedelta(seconds=1))
        )
        self.assertEqual(calls, ["capture"])

    def test_stubborn_worker_is_killed_no_orphan_process(self):
        process = FakeProcess(timeout_once=True)
        supervisor = SidecarProcessSupervisor(lambda: process)
        self.assertTrue(supervisor.start())
        self.assertTrue(supervisor.running)
        self.assertTrue(supervisor.stop(timeout_s=0.01))
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertFalse(supervisor.running)

    def test_vision_poll_does_not_mutate_semantic_database(self):
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

            sidecar = VisionSidecar(
                lambda: self._frame(),
                lambda raw, frame: VisionAnalysis(
                    "untrusted visible text",
                    0.6,
                    {},
                ),
                min_capture_interval_s=0,
            )
            sidecar.enable()
            observation = sidecar.poll(T0)
            self.assertIsNotNone(observation)
            sidecar.close()

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
