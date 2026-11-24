from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from private_overlay.candidates.execution_plane import probe_a0bb_core_patch_retirement as probe


class A0bbPatchRetirementProbeTests(unittest.TestCase):
    def test_targets_are_narrow_candidate_only_patch_retirement_set(self) -> None:
        self.assertEqual(
            [target.patch for target in probe.TARGETS],
            [
                "0003-qwen38-server-vad-reliability.patch",
                "0005-latest-character-switch-intent-replay.patch",
                "0007-private-first-round-tool-route.patch",
                "0008-qwen-clone-provider-routing.patch",
            ],
        )
        self.assertNotIn("0009-proactive-interruptibility-gate.patch", {x.patch for x in probe.TARGETS})

    def test_test_path_detection_covers_python_node_and_plugin_tests(self) -> None:
        self.assertTrue(probe._is_test_path("tests/unit/test_x.py"))
        self.assertTrue(probe._is_test_path("plugin/tests/unit/test_x.py"))
        self.assertTrue(probe._is_test_path("frontend/react-neko-chat/src/App.test.tsx"))
        self.assertTrue(probe._is_test_path("tests/frontend/chat_avatar_integration.test.cjs"))
        self.assertFalse(probe._is_test_path("main_logic/core/turn.py"))

    def test_probe_one_restores_candidate_after_required_patch_signal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            candidate = root / "candidate"
            patch_dir = workspace / "private_overlay" / "patches"
            patch_dir.mkdir(parents=True)
            (candidate / "tests").mkdir(parents=True)

            self._git(candidate, "init")
            self._git(candidate, "config", "user.email", "probe@example.invalid")
            self._git(candidate, "config", "user.name", "probe")
            (candidate / "runtime.py").write_text("VALUE = 0\n", encoding="utf-8")
            (candidate / "tests" / "test_sample.py").write_text("EXPECTED = 0\n", encoding="utf-8")
            self._git(candidate, "add", ".")
            self._git(candidate, "commit", "-m", "base")

            (candidate / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
            (candidate / "tests" / "test_sample.py").write_text("EXPECTED = 1\n", encoding="utf-8")
            patch_text = subprocess.run(
                ["git", "diff", "--binary"],
                cwd=candidate,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            patch_path = patch_dir / "sample.patch"
            patch_path.write_text(patch_text, encoding="utf-8")

            target = probe.ProbeTarget(
                patch="sample.patch",
                runner="pytest",
                tests=("tests/test_sample.py",),
            )
            baseline_runtime = (candidate / "runtime.py").read_bytes()
            baseline_test = (candidate / "tests" / "test_sample.py").read_bytes()

            command = (
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; import sys; "
                    "sys.exit(1 if 'VALUE = 0' in Path('runtime.py').read_text() else 0)"
                ),
            )
            with mock.patch.object(probe, "_runner_command", return_value=command):
                result = probe._probe_one(
                    workspace=workspace,
                    candidate_root=candidate,
                    target=target,
                    uv_path=sys.executable,
                )

            self.assertEqual(
                result["verdict"],
                "PATCH_STILL_REQUIRED_BY_FOCUSED_ACCEPTANCE",
            )
            self.assertFalse(result["retirement_candidate"])
            self.assertTrue(result["restored"])
            self.assertEqual((candidate / "runtime.py").read_bytes(), baseline_runtime)
            self.assertEqual((candidate / "tests" / "test_sample.py").read_bytes(), baseline_test)

    @staticmethod
    def _git(root: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
