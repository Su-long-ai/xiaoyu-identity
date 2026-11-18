from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from xiaoyu.guardian import (
    GuardianFinding,
    GuardianInputs,
    GuardianSeverity,
    GuardianStateStore,
    GuardianThresholds,
    IndependentGuardian,
    OpenTelemetryGuardianSink,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.release.authority import (
    ReleaseAuthority,
    ReleaseManifest,
    ReleaseSmokeEvidence,
)
from xiaoyu.runtime import HostResourceSnapshot


UTC = timezone.utc
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class FakeCounter:
    def __init__(self):
        self.calls = []

    def add(self, value, attributes):
        self.calls.append((value, dict(attributes)))


class FakeMeter:
    def __init__(self):
        self.counters = {}

    def create_counter(self, name, **kwargs):
        counter = FakeCounter()
        self.counters[name] = counter
        return counter


class FakeSpan:
    def __init__(self):
        self.attributes = {}
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def add_event(self, name, attributes=None):
        self.events.append((name, dict(attributes or {})))


class FakeTracer:
    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name):
        span = FakeSpan()
        self.spans.append((name, span))
        return span


class R19GuardianTests(unittest.TestCase):
    def _db(self, root):
        db = Database(Path(root) / "identity.sqlite3")
        apply_migrations(db)
        return db

    @staticmethod
    def _codes(report):
        return {finding.code for finding in report.findings}

    def test_healthy_database_is_observable_without_product_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            report = IndependentGuardian().check(
                GuardianInputs(identity_db_path=db.path),
                observed_at=NOW,
            )
            self.assertTrue(report.healthy)
            self.assertEqual(report.findings, ())

    def test_corrupt_db_and_failed_component_are_both_observable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corrupt = root / "identity.sqlite3"
            corrupt.write_bytes(b"not-a-sqlite-database")
            state_path = root / "guardian-state.json"
            store = GuardianStateStore(state_path)
            store.heartbeat(
                "companion",
                observed_at=NOW - timedelta(minutes=10),
            )
            for seconds in (40, 30, 20, 10):
                store.record_restart(
                    "provider-worker",
                    observed_at=NOW - timedelta(seconds=seconds),
                )

            report = IndependentGuardian(
                thresholds=GuardianThresholds(
                    heartbeat_timeout_s=60,
                    restart_window_s=300,
                    max_restarts_in_window=4,
                )
            ).check(
                GuardianInputs(
                    identity_db_path=corrupt,
                    state_path=state_path,
                ),
                observed_at=NOW,
            )
            codes = self._codes(report)
            self.assertIn("DB_INTEGRITY_FAILED", codes)
            self.assertIn("COMPONENT_HEARTBEAT_STALE", codes)
            self.assertIn("RESTART_LOOP", codes)
            self.assertFalse(report.healthy)

    def test_current_release_supplies_expected_provider_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO provider_registry(
                           provider_id,capability,descriptor_json,
                           artifact_digest,descriptor_digest,
                           interface_digest,tool_schema_digest,
                           lifecycle_state,health_state_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "qwen",
                        "chat.completion",
                        "{}",
                        "sha256:artifact",
                        "sha256:actual",
                        "sha256:interface",
                        None,
                        "ACTIVE",
                        "{}",
                        NOW.isoformat(),
                    ),
                )
            release_path = root / "release-authority.json"
            authority = ReleaseAuthority(release_path)
            authority.register_candidate(
                ReleaseManifest(
                    release_id="r1",
                    core_commit="commit-r1",
                    schema_version=1,
                    max_schema_version=99,
                    migration_version=1,
                    contract_digest="sha256:contract",
                    release_digest="sha256:release",
                    provider_digests={
                        "qwen": "sha256:expected"
                    },
                    model_digests={
                        "qwen3.8-flash": "sha256:model"
                    },
                    tokenizer_digests={
                        "qwen3.8-flash": "sha256:tokenizer"
                    },
                    config_digest="sha256:config",
                    skills_digest="sha256:skills",
                    sidecars_digest="sha256:sidecars",
                    test_evidence_digest="sha256:tests",
                )
            )
            authority.activate(
                "r1",
                ReleaseSmokeEvidence(True, True, True, True),
            )

            report = IndependentGuardian().check(
                GuardianInputs(
                    identity_db_path=db.path,
                    release_authority_path=release_path,
                ),
                observed_at=NOW,
            )
            self.assertIn(
                "PROVIDER_DIGEST_DRIFT",
                self._codes(report),
            )
            self.assertNotIn(
                "CURRENT_RELEASE_BINDINGS_INCOMPLETE",
                self._codes(report),
            )

    def test_provider_digest_drift_is_metadata_only(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO provider_registry(
                           provider_id,capability,descriptor_json,
                           artifact_digest,descriptor_digest,
                           interface_digest,tool_schema_digest,
                           lifecycle_state,health_state_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "qwen",
                        "chat.completion",
                        "{}",
                        "sha256:artifact",
                        "sha256:actual",
                        "sha256:interface",
                        None,
                        "ACTIVE",
                        "{}",
                        NOW.isoformat(),
                    ),
                )
            report = IndependentGuardian().check(
                GuardianInputs(
                    identity_db_path=db.path,
                    expected_provider_digests={
                        "qwen": "sha256:expected"
                    },
                ),
                observed_at=NOW,
            )
            finding = next(
                item
                for item in report.findings
                if item.code == "PROVIDER_DIGEST_DRIFT"
            )
            self.assertEqual(
                finding.attributes["provider_id"], "qwen"
            )
            self.assertNotIn(
                "sha256:actual",
                json.dumps(dict(finding.attributes)),
            )
            self.assertNotIn(
                "sha256:expected",
                json.dumps(dict(finding.attributes)),
            )

    def test_backup_age_identity_and_digest_are_checked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            backup = root / "backup.sqlite3"
            backup.write_bytes(b"backup-bytes")
            digest = "sha256:" + hashlib.sha256(
                backup.read_bytes()
            ).hexdigest()
            manifest = {
                "version": 1,
                "identity_id": "fish-1",
                "creation_time": (
                    NOW - timedelta(days=2)
                ).isoformat(),
                "db_sha256": digest,
            }
            Path(str(backup) + ".manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            guardian = IndependentGuardian(
                thresholds=GuardianThresholds(
                    backup_max_age_s=24 * 3600,
                )
            )
            report = guardian.check(
                GuardianInputs(
                    identity_db_path=db.path,
                    identity_id="fish-1",
                    backup_path=backup,
                ),
                observed_at=NOW,
            )
            self.assertIn("BACKUP_STALE", self._codes(report))

            backup.write_bytes(b"tampered")
            report = guardian.check(
                GuardianInputs(
                    identity_db_path=db.path,
                    identity_id="fish-2",
                    backup_path=backup,
                ),
                observed_at=NOW,
            )
            codes = self._codes(report)
            self.assertIn("BACKUP_IDENTITY_MISMATCH", codes)
            self.assertIn("BACKUP_DIGEST_MISMATCH", codes)

    def test_repeated_denials_are_counted_without_resource_payload(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            with db.transaction(immediate=True) as conn:
                for index in range(8):
                    conn.execute(
                        """INSERT INTO authorization_decisions(
                               decision_id,identity_id,principal_id,
                               actor_id,purpose_id,action_class,
                               resource_json,decision,reason_code,created_at
                           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            "deny-%d" % index,
                            "fish-1",
                            "owner",
                            "tool:test",
                            None,
                            "filesystem.write",
                            json.dumps(
                                {
                                    "path":
                                        "D:/secret/private-file.txt"
                                }
                            ),
                            "DENY",
                            "NO_DELEGATION",
                            (
                                NOW - timedelta(seconds=index)
                            ).isoformat(),
                        ),
                    )
            report = IndependentGuardian(
                thresholds=GuardianThresholds(
                    denied_effect_threshold=8,
                    denied_window_s=300,
                )
            ).check(
                GuardianInputs(identity_db_path=db.path),
                observed_at=NOW,
            )
            finding = next(
                item
                for item in report.findings
                if item.code == "REPEATED_DENIED_EFFECTS"
            )
            self.assertEqual(finding.attributes["count"], 8)
            self.assertEqual(
                finding.attributes["top_action_class"],
                "filesystem.write",
            )
            encoded = json.dumps(dict(finding.attributes))
            self.assertNotIn("private-file", encoded)
            self.assertNotIn("D:/secret", encoded)

    def test_resource_runaway_is_observable_from_external_sampler(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            report = IndependentGuardian(
                thresholds=GuardianThresholds(
                    cpu_fraction=0.90,
                    gpu_fraction=0.90,
                    min_ram_available_mb=512,
                    min_vram_available_mb=256,
                )
            ).check(
                GuardianInputs(
                    identity_db_path=db.path,
                    resource_snapshot=HostResourceSnapshot(
                        cpu_fraction=0.95,
                        ram_available_mb=128,
                        gpu_fraction=0.96,
                        vram_available_mb=64,
                    ),
                ),
                observed_at=NOW,
            )
            self.assertEqual(
                self._codes(report),
                {
                    "CPU_RUNAWAY",
                    "GPU_RUNAWAY",
                    "RAM_PRESSURE",
                    "VRAM_PRESSURE",
                },
            )

    def test_malformed_sidecar_and_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            state = root / "guardian.json"
            state.write_text("[]", encoding="utf-8")
            backup = root / "backup.sqlite3"
            backup.write_bytes(b"backup")
            Path(str(backup) + ".manifest.json").write_text(
                "[]",
                encoding="utf-8",
            )
            report = IndependentGuardian().check(
                GuardianInputs(
                    identity_db_path=db.path,
                    backup_path=backup,
                    state_path=state,
                ),
                observed_at=NOW,
            )
            codes = self._codes(report)
            self.assertIn("GUARDIAN_STATE_CORRUPT", codes)
            self.assertIn("BACKUP_MANIFEST_INVALID", codes)

    def test_sink_failure_does_not_blind_guardian(self):
        class BrokenSink:
            def emit(self, report):
                raise RuntimeError("exporter down")

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            report = IndependentGuardian(
                sinks=(BrokenSink(),)
            ).check(
                GuardianInputs(identity_db_path=db.path),
                observed_at=NOW,
            )
            self.assertIn(
                "TELEMETRY_SINK_FAILED",
                self._codes(report),
            )
            self.assertTrue(report.healthy)

    def test_state_sidecar_writes_only_component_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "guardian.json"
            store = GuardianStateStore(path)
            store.heartbeat("companion", observed_at=NOW)
            store.record_restart("provider-worker", observed_at=NOW)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(payload),
                {"version", "heartbeats", "restarts"},
            )
            self.assertNotIn("memory", json.dumps(payload).lower())
            self.assertNotIn("prompt", json.dumps(payload).lower())

    def test_otel_sink_exports_only_allowlisted_metadata(self):
        meter = FakeMeter()
        tracer = FakeTracer()
        sink = OpenTelemetryGuardianSink(
            meter=meter,
            tracer=tracer,
            required_api_version=None,
        )
        report = type("Report", (), {})()
        from xiaoyu.guardian import GuardianReport

        report = GuardianReport(
            NOW,
            (
                GuardianFinding(
                    "REPEATED_DENIED_EFFECTS",
                    GuardianSeverity.WARNING,
                    "authorization",
                    {
                        "count": 9,
                        "top_action_class": "filesystem.write",
                        "prompt": "do not export this",
                        "memory_text": "private memory",
                    },
                ),
            ),
        )
        sink.emit(report)

        finding_calls = meter.counters[
            "xiaoyu.guardian.findings"
        ].calls
        self.assertEqual(len(finding_calls), 1)
        attrs = finding_calls[0][1]
        self.assertEqual(attrs["guardian.count"], 9)
        self.assertEqual(
            attrs["guardian.top_action_class"],
            "filesystem.write",
        )
        self.assertNotIn("guardian.prompt", attrs)
        self.assertNotIn("guardian.memory_text", attrs)
        span = tracer.spans[0][1]
        self.assertTrue(span.events)
        self.assertNotIn(
            "do not export this",
            json.dumps(span.events),
        )


if __name__ == "__main__":
    unittest.main()
