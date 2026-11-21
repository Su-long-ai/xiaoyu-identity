import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "migration" / "seed_native_persona.py"
spec = importlib.util.spec_from_file_location("seed_native_persona", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class IdentitySeedImportTests(unittest.TestCase):
    def test_seed_extracts_only_persona_bullets(self):
        text = (ROOT / "identity" / "persona.md").read_text(encoding="utf-8")
        rows = mod.extract_seed_candidates(text)
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["target"] == "persona" for row in rows))
        self.assertTrue(all(row["entity"] == "neko" for row in rows))
        self.assertTrue(all(row["source_file"] == "identity/persona.md" for row in rows))
        joined = "\n".join(row["text"] for row in rows)
        self.assertNotIn("Name: XiaoYu", joined)
        self.assertNotIn("second memory database", joined)
        self.assertNotIn("runtime infrastructure", joined)

    def test_extractor_ignores_unknown_sections_and_prose(self):
        text = """# Title
Preamble.
Stable identity:
- Keep me.
Runtime:
- Do not import me.
Growth:
- Grow me.
"""
        rows = mod.extract_seed_candidates(text)
        self.assertEqual([row["text"] for row in rows], ["Keep me.", "Grow me."])


if __name__ == "__main__":
    unittest.main()
