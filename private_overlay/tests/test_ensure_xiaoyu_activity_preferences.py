from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from private_overlay.tools import ensure_xiaoyu_activity_preferences as mod


class EnsureXiaoYuActivityPreferencesTests(unittest.TestCase):
    def _root(self, td: str, global_entry: dict) -> Path:
        root = Path(td)
        cfg = root / "config"
        cfg.mkdir(parents=True)
        (cfg / "user_preferences.json").write_text(
            json.dumps(
                [
                    {"model_path": "/static/example.model3.json", "scale": {"x": 1}},
                    {"model_path": "__global_conversation__", **global_entry},
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return root

    def test_sets_only_native_activity_probability_and_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td,
                {
                    "proactiveMiniGameInviteEnabled": True,
                    "activity": {
                        "skip_probability_overrides": {"competitive": 0.5},
                    },
                },
            )
            result = mod.ensure_private_activity_preferences(root)
            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])

            payload = json.loads(
                (root / "config" / "user_preferences.json").read_text(encoding="utf-8")
            )
            global_entry = next(
                x for x in payload if x.get("model_path") == "__global_conversation__"
            )
            self.assertTrue(global_entry["proactiveMiniGameInviteEnabled"])
            self.assertEqual(
                global_entry["activity"]["work_break_game_invite_probability"],
                0.0,
            )
            self.assertEqual(
                global_entry["activity"]["skip_probability_overrides"],
                {"competitive": 0.5},
            )

    def test_verify_only_rejects_default_without_mutating(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, {"proactiveMiniGameInviteEnabled": True})
            path = root / "config" / "user_preferences.json"
            before = path.read_bytes()
            result = mod.ensure_private_activity_preferences(root, verify_only=True)
            self.assertFalse(result["ok"])
            self.assertEqual(path.read_bytes(), before)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td,
                {
                    "activity": {
                        "work_break_game_invite_probability": 0.0,
                    }
                },
            )
            result = mod.ensure_private_activity_preferences(root)
            self.assertTrue(result["ok"])
            self.assertFalse(result["changed"])


if __name__ == "__main__":
    unittest.main()
