import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "migration" / "normalize_legacy_owner_alias.py"
spec = importlib.util.spec_from_file_location("normalize_legacy_owner_alias", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class FakePersonaManager:
    @staticmethod
    def _invalidate_token_count_cache(entry):
        entry["token_count"] = None
        entry["token_count_text_sha256"] = None
        entry["token_count_tokenizer"] = None

    @staticmethod
    def _invalidate_embedding_cache(entry):
        entry["embedding"] = None
        entry["embedding_text_sha256"] = None
        entry["embedding_model_id"] = None


class NormalizeLegacyOwnerAliasTests(unittest.TestCase):
    def test_only_external_neko_fact_is_normalized_and_caches_invalidated(self):
        persona = {
            "neko": {
                "facts": [
                    {
                        "id": "legacy",
                        "text": "小鱼尊重碳基生物的选择。",
                        "source": "external_import",
                        "embedding": [1.0],
                        "embedding_text_sha256": "old",
                        "embedding_model_id": "model",
                        "token_count": 7,
                        "token_count_text_sha256": "old",
                        "token_count_tokenizer": "tok",
                        "version_history": [],
                        "last_refine_cluster_hash": "cluster",
                        "last_refine_at": "now",
                    },
                    {
                        "id": "manual",
                        "text": "碳基生物只是历史词。",
                        "source": "manual",
                    },
                ]
            },
            "master": {
                "facts": [
                    {
                        "id": "rename",
                        "text": "改名记录: 曾用名「碳基生物」，现在的名字是「主人」。",
                        "source": "character_card",
                    }
                ]
            },
        }

        changed = mod.normalize_legacy_owner_alias_entries(persona, FakePersonaManager)
        self.assertEqual(changed, ["legacy"])
        legacy = persona["neko"]["facts"][0]
        self.assertEqual(legacy["text"], "小鱼尊重主人的选择。")
        self.assertIsNone(legacy["embedding"])
        self.assertIsNone(legacy["embedding_text_sha256"])
        self.assertIsNone(legacy["embedding_model_id"])
        self.assertIsNone(legacy["token_count"])
        self.assertIsNone(legacy["last_refine_cluster_hash"])
        self.assertEqual(len(legacy["version_history"]), 1)
        self.assertIn("碳基生物", legacy["version_history"][0]["text"])
        self.assertIn("碳基生物", persona["neko"]["facts"][1]["text"])
        self.assertIn("碳基生物", persona["master"]["facts"][0]["text"])

    def test_empty_persona_is_noop(self):
        self.assertEqual(mod.find_legacy_owner_alias_entries({}), [])


if __name__ == "__main__":
    unittest.main()
