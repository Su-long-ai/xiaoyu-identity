import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "migration" / "retire_stale_persona.py"
spec = importlib.util.spec_from_file_location("retire_stale_persona", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class RetireStalePersonaTests(unittest.TestCase):
    def test_only_external_just_met_fact_is_selected(self):
        persona = {
            "neko": {
                "facts": [
                    {"id": "a", "text": "小鱼与主人刚开始认识彼此。", "source": "external_import"},
                    {"id": "b", "text": "关系不能重置为初始状态。", "source": "external_import"},
                    {"id": "c", "text": "刚开始认识", "source": "character_card"},
                ]
            }
        }
        rows = mod.find_stale_relationship_entries(persona)
        self.assertEqual([row["id"] for row in rows], ["a"])

    def test_empty_or_unrelated_persona_is_noop(self):
        self.assertEqual(mod.find_stale_relationship_entries({}), [])
        self.assertEqual(
            mod.find_stale_relationship_entries(
                {"neko": {"facts": [{"id": "x", "text": "持续身份", "source": "external_import"}]}}
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
