from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaoyu.core.export import NativeCanonicalExporter, adapt_native_export
from xiaoyu.persistence import Database, apply_migrations


class _FactOnlyAdapter:
    adapter_id = "test.fact-only"

    def convert(self, native_bundle):
        return {
            "identity_id": native_bundle["identity_id"],
            "facts": native_bundle["data"]["temporal_facts"],
        }


class NativeCanonicalExportTests(unittest.TestCase):
    def test_native_export_is_deterministic_excludes_runtime_provider_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = Database(root / "identity.sqlite3")
            apply_migrations(db)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO provider_registry(
                           provider_id,capability,descriptor_json,artifact_digest,
                           descriptor_digest,interface_digest,tool_schema_digest,
                           lifecycle_state,health_state_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "provider-secret",
                        "chat",
                        '{"api_key":"DO_NOT_EXPORT"}',
                        None,
                        "sha256:d",
                        "sha256:i",
                        None,
                        "ACTIVE",
                        "{}",
                        "2026-11-18T00:00:00+00:00",
                    ),
                )

            exporter = NativeCanonicalExporter(db)
            first = exporter.write(root / "one.json", identity_id="fish-1")
            second = exporter.write(root / "two.json", identity_id="fish-1")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertNotIn(b"DO_NOT_EXPORT", first.read_bytes())
            self.assertNotIn(b"provider-secret", first.read_bytes())

            bundle = exporter.build(identity_id="fish-1")
            self.assertIn(
                "authority_cutover_state",
                bundle["data"],
            )
            portable = adapt_native_export(bundle, _FactOnlyAdapter())
            self.assertEqual(portable["adapter_id"], "test.fact-only")
            self.assertEqual(
                portable["source_bundle_digest"], bundle["bundle_digest"]
            )
            self.assertEqual(portable["payload"]["identity_id"], "fish-1")

    def test_projection_rows_are_not_exported_as_canonical_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = Database(root / "identity.sqlite3")
            apply_migrations(db)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO projections(
                           identity_id,projection_key,projection_type,value_json,
                           source_fact_ids_json,builder_version,built_at,
                           source_revision,erasure_generation
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        "fish-1",
                        "summary",
                        "PROFILE_SUMMARY",
                        '{"hallucinated":"value"}',
                        "[]",
                        "old-builder",
                        "2026-11-18T00:00:00+00:00",
                        0,
                        0,
                    ),
                )

            bundle = NativeCanonicalExporter(db).build(identity_id="fish-1")
            self.assertNotIn("projections", bundle["data"])
            self.assertNotIn("hallucinated", str(bundle))


if __name__ == "__main__":
    unittest.main()
