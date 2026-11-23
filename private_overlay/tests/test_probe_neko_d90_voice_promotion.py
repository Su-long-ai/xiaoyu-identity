import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from private_overlay.candidates.voice_upgrade import probe_neko_d90_voice_promotion as mod


class NekoD90VoicePromotionProbeTests(unittest.TestCase):
    def test_candidate_is_fixed_and_product_pin_is_distinct(self):
        self.assertEqual(
            mod.EXPECTED_CANDIDATE_SHA,
            "d90f8371653c5a2a9b01d655c38475414711266a",
        )
        self.assertEqual(
            mod.EXPECTED_PRODUCT_SHA,
            "c3fc33ff0d32e4a79fd905d1add22d45725071f5",
        )
        self.assertNotEqual(mod.EXPECTED_CANDIDATE_SHA, mod.EXPECTED_PRODUCT_SHA)

    def test_native_and_product_tests_cover_distinct_acceptance_layers(self):
        self.assertIn("tests/unit/test_spare_socket.py", mod.NATIVE_TESTS)
        self.assertIn("tests/unit/test_tts_preconnect_providers.py", mod.NATIVE_TESTS)
        self.assertIn("tests/unit/test_qwen_server_close_reporting.py", mod.NATIVE_TESTS)
        self.assertIn("tests/unit/test_qwen_voice_bundle.py", mod.PRODUCT_TESTS)
        self.assertIn("tests/unit/test_tts_handoff_ownership.py", mod.PRODUCT_TESTS)
        self.assertIn(
            "tests/unit/runtime/test_realtime_connection_recovery.py",
            mod.PRODUCT_TESTS,
        )
        self.assertTrue(set(mod.NATIVE_TESTS).isdisjoint(mod.PRODUCT_TESTS))

    def test_series_reads_declared_order_without_inventing_a_patch_list(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "private_overlay" / "patches"
            path.mkdir(parents=True)
            (path / "series.json").write_text(
                json.dumps(
                    {
                        "patches": [
                            {"file": "0002-b.patch"},
                            {"file": "0001-a.patch"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                mod._series(root),
                ["0002-b.patch", "0001-a.patch"],
            )

    def test_result_writer_is_structured_and_utf8(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "result.json"
            payload = {
                "schema_version": 1,
                "candidate_only": True,
                "promotion_ready": False,
                "blockers": [{"kind": "managed_patch_conflict", "detail": "0008.patch"}],
            }
            mod._write_result(path, payload)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                payload,
            )

    def test_tail_bounds_candidate_command_output(self):
        self.assertEqual(mod._tail("abc", 4), "abc")
        self.assertEqual(mod._tail("abcdef", 4), "cdef")


if __name__ == "__main__":
    unittest.main()
