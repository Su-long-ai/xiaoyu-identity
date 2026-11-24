from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from private_overlay.candidates.execution_plane import (
    probe_a0bb_remaining_core_patch_retirement as probe,
)


class A0bbRemainingCorePatchRetirementProbeTests(unittest.TestCase):
    def test_remaining_targets_are_exactly_the_low_change_second_pass(self) -> None:
        self.assertEqual(
            [target.patch for target in probe.TARGETS],
            [
                "0001-proactive-autostart-idle-gate.patch",
                "0004-native-ingress-activity-before-backpressure.patch",
                "0006-private-speech-output-gate.patch",
                "0009-proactive-interruptibility-gate.patch",
            ],
        )
        self.assertEqual(
            probe.PATCH_0002_NATIVE_SEAMS,
            (
                "frontend/react-neko-chat/src/FullChatSurface.tsx",
                "frontend/react-neko-chat/src/App.test.tsx",
            ),
        )

    def test_series_prefix_reads_only_first_nine_managed_patches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            patch_dir = workspace / "private_overlay" / "patches"
            patch_dir.mkdir(parents=True)
            payload = {
                "patches": [{"file": f"{index:04d}-patch.patch"} for index in range(1, 15)]
            }
            (patch_dir / "series.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            self.assertEqual(
                probe._series_prefix(workspace),
                [f"{index:04d}-patch.patch" for index in range(1, 10)],
            )

    def test_patch_0002_is_never_a_retirement_candidate_by_blob_identity_alone(self) -> None:
        source = Path(probe.__file__).read_text(encoding="utf-8-sig")
        self.assertIn("NO_NATIVE_SEAM_CHANGE_NOT_RETIREMENT_CANDIDATE", source)
        self.assertIn('"retirement_candidate": False', source)
        self.assertIn("_neko_core_retirement_prefix_candidate", source)


if __name__ == "__main__":
    unittest.main()
