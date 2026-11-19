import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import verify_live_physical_mic_acceptance as verifier


class PhysicalMicAcceptanceTests(unittest.TestCase):
    def test_accepts_ordered_audio_transcript_then_model_reply(self):
        text = """2026-11-19 19:20:00 - x - INFO - start_session: input_mode=audio, new=False
2026-11-19 19:20:02 - x - INFO - [XiaoYu] voice user_transcript session=OmniRealtimeClient ws_connected=True len=8
2026-11-19 19:20:03 - x - INFO - [XiaoYu] send_lanlan_response first=True len=12 ws_state=WebSocketState.CONNECTED
2026-11-19 19:20:05 - x - INFO - [XiaoYu] microphone route metrics provider=blocked omni_mic_audio_bytes=384000
"""
        got = verifier.analyze_log_segment(text)
        self.assertTrue(got["audio_session_start_seen"])
        self.assertTrue(got["nonempty_user_transcript_seen"])
        self.assertTrue(got["model_reply_after_transcript_seen"])
        self.assertEqual(got["transcript_length"], 8)
        self.assertEqual(got["model_reply_length"], 12)
        self.assertEqual(got["max_mic_audio_bytes"], 384000)

    def test_rejects_reply_that_precedes_user_transcript(self):
        text = """2026-11-19 19:20:00 - x - INFO - start_session: input_mode=audio, new=False
2026-11-19 19:20:01 - x - INFO - [XiaoYu] send_lanlan_response first=True len=12 ws_state=WebSocketState.CONNECTED
2026-11-19 19:20:02 - x - INFO - [XiaoYu] voice user_transcript session=OmniRealtimeClient ws_connected=True len=8
"""
        got = verifier.analyze_log_segment(text)
        self.assertTrue(got["nonempty_user_transcript_seen"])
        self.assertFalse(got["model_reply_after_transcript_seen"])

    def test_rejects_idle_timeout_between_transcript_and_reply(self):
        text = """2026-11-19 19:20:00 - x - INFO - start_session: input_mode=audio, new=False
2026-11-19 19:20:02 - x - INFO - [XiaoYu] voice user_transcript session=OmniRealtimeClient ws_connected=True len=8
2026-11-19 19:25:02 - x - ERROR - response_idle_timeout
2026-11-19 19:25:03 - x - INFO - [XiaoYu] send_lanlan_response first=True len=12 ws_state=WebSocketState.CONNECTED
"""
        got = verifier.analyze_log_segment(text)
        self.assertFalse(got["model_reply_after_transcript_seen"])


if __name__ == "__main__":
    unittest.main()
