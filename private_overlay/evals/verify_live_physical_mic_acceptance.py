from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_STORAGE_ROOT = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_LOG_NAME = "N.E.K.O_Main_20261119.log"

AUDIO_START_RE = re.compile(
    r"(?:Voice lifecycle received action=start_session.*|start_session: input_mode=audio)"
)
TRANSCRIPT_RE = re.compile(
    r"voice user_transcript session=(?P<session>\S+) "
    r"ws_connected=(?P<ws>\S+) len=(?P<len>\d+)"
)
REPLY_RE = re.compile(
    r"send_lanlan_response first=True len=(?P<len>\d+) "
    r"ws_state=(?P<ws>\S+)"
)
MIC_RE = re.compile(
    r"microphone route metrics provider=(?P<provider>\S+) "
    r"omni_mic_audio_bytes=(?P<bytes>\d+)"
)
VOICE_END_RE = re.compile(r"Voice lifecycle received action=end_session")
IDLE_TIMEOUT_RE = re.compile(r"response_idle_timeout")
STAMP_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _stamp(line: str) -> datetime | None:
    match = STAMP_RE.search(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def analyze_log_segment(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    starts = [idx for idx, line in enumerate(lines) if AUDIO_START_RE.search(line)]
    transcripts: list[tuple[int, re.Match[str]]] = []
    replies: list[tuple[int, re.Match[str]]] = []
    mic_metrics: list[dict[str, Any]] = []

    for idx, line in enumerate(lines):
        match = TRANSCRIPT_RE.search(line)
        if match and int(match.group("len")) > 0 and match.group("ws") == "True":
            transcripts.append((idx, match))
        match = REPLY_RE.search(line)
        if (
            match
            and int(match.group("len")) > 0
            and "CONNECTED" in match.group("ws")
        ):
            replies.append((idx, match))
        match = MIC_RE.search(line)
        if match:
            mic_metrics.append(
                {
                    "line_index": idx,
                    "provider": match.group("provider"),
                    "bytes": int(match.group("bytes")),
                }
            )

    chosen: dict[str, Any] | None = None
    for transcript_idx, transcript_match in transcripts:
        earlier_starts = [idx for idx in starts if idx < transcript_idx]
        if not earlier_starts:
            continue
        start_idx = earlier_starts[-1]
        transcript_time = _stamp(lines[transcript_idx])

        for reply_idx, reply_match in replies:
            if reply_idx <= transcript_idx:
                continue
            reply_time = _stamp(lines[reply_idx])
            if transcript_time and reply_time:
                delta = (reply_time - transcript_time).total_seconds()
                if delta < 0 or delta > 120:
                    continue
            else:
                delta = None

            timeout_between = any(
                IDLE_TIMEOUT_RE.search(lines[idx])
                for idx in range(transcript_idx + 1, reply_idx + 1)
            )
            if timeout_between:
                continue

            chosen = {
                "audio_session_start_seen": True,
                "audio_session_start_time": (
                    _stamp(lines[start_idx]).isoformat()
                    if _stamp(lines[start_idx])
                    else None
                ),
                "nonempty_user_transcript_seen": True,
                "transcript_session": transcript_match.group("session"),
                "transcript_length": int(transcript_match.group("len")),
                "transcript_time": (
                    transcript_time.isoformat() if transcript_time else None
                ),
                "model_reply_after_transcript_seen": True,
                "model_reply_length": int(reply_match.group("len")),
                "model_reply_time": reply_time.isoformat() if reply_time else None,
                "reply_delay_seconds": delta,
                "response_idle_timeout_between_transcript_and_reply": False,
            }
            break
        if chosen:
            break

    if chosen is None:
        chosen = {
            "audio_session_start_seen": bool(starts),
            "audio_session_start_time": (
                _stamp(lines[starts[-1]]).isoformat() if starts and _stamp(lines[starts[-1]]) else None
            ),
            "nonempty_user_transcript_seen": bool(transcripts),
            "transcript_session": (
                transcripts[-1][1].group("session") if transcripts else None
            ),
            "transcript_length": (
                int(transcripts[-1][1].group("len")) if transcripts else 0
            ),
            "transcript_time": (
                _stamp(lines[transcripts[-1][0]]).isoformat()
                if transcripts and _stamp(lines[transcripts[-1][0]])
                else None
            ),
            "model_reply_after_transcript_seen": False,
            "model_reply_length": 0,
            "model_reply_time": None,
            "reply_delay_seconds": None,
            "response_idle_timeout_between_transcript_and_reply": None,
        }

    chosen["voice_end_seen"] = any(VOICE_END_RE.search(line) for line in lines)
    chosen["mic_route_metrics_seen"] = bool(mic_metrics)
    chosen["max_mic_audio_bytes"] = (
        max(item["bytes"] for item in mic_metrics) if mic_metrics else 0
    )
    chosen["mic_route_providers"] = sorted(
        {item["provider"] for item in mic_metrics}
    )
    chosen["examined_line_count"] = len(lines)
    return chosen


def _default_log_path(storage_root: Path) -> Path:
    logs = storage_root / "logs"
    candidates = sorted(logs.glob("N.E.K.O_Main_*.log"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No N.E.K.O main log under {logs}")
    return candidates[-1]


def _state_path(storage_root: Path) -> Path:
    return storage_root / ".runtime" / "xiaoyu_physical_mic_acceptance_arm.json"


def arm(storage_root: Path, log_path: Path | None = None) -> dict[str, Any]:
    log_path = log_path or _default_log_path(storage_root)
    stat = log_path.stat()
    doc = {
        "schema_version": 1,
        "arm_id": uuid.uuid4().hex,
        "armed_at_local": datetime.now().astimezone().isoformat(),
        "log_name": log_path.name,
        "baseline_offset_bytes": stat.st_size,
        "baseline_mtime_ns": stat.st_mtime_ns,
        "privacy": {
            "microphone_audio_recorded_by_verifier": False,
            "transcript_text_recorded_by_verifier": False,
            "model_reply_text_recorded_by_verifier": False,
        },
    }
    path = _state_path(storage_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def verify(
    storage_root: Path,
    *,
    user_attested: bool,
    evidence_root: Path | None = None,
) -> tuple[dict[str, Any], Path | None]:
    state_path = _state_path(storage_root)
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    log_path = storage_root / "logs" / state["log_name"]
    baseline = int(state["baseline_offset_bytes"])
    current_size = log_path.stat().st_size
    if current_size < baseline:
        raise RuntimeError("N.E.K.O log rotated/truncated after arm; arm again")

    with log_path.open("rb") as handle:
        handle.seek(baseline)
        raw = handle.read()
    segment = raw.decode("utf-8", errors="replace")
    observed = analyze_log_segment(segment)

    passed = bool(
        user_attested
        and observed["audio_session_start_seen"]
        and observed["nonempty_user_transcript_seen"]
        and observed["model_reply_after_transcript_seen"]
    )
    doc = {
        "schema_version": 1,
        "observed_at_local": datetime.now().astimezone().isoformat(),
        "arm_id": state["arm_id"],
        "user_attested_physical_microphone_utterance": bool(user_attested),
        "runtime_log_name": log_path.name,
        "baseline_offset_bytes": baseline,
        "examined_new_bytes": len(raw),
        "privacy": {
            "microphone_audio_recorded_by_verifier": False,
            "transcript_text_recorded": False,
            "model_reply_text_recorded": False,
            "only_lengths_timestamps_and_runtime_markers_recorded": True,
        },
        "observed": observed,
        "verdict": "PASS" if passed else "NOT_YET_PASS",
    }

    written: Path | None = None
    if evidence_root is not None:
        evidence_root.mkdir(parents=True, exist_ok=True)
        date = datetime.now().astimezone().date().isoformat()
        filename = (
            f"{date}-live-physical-mic-acceptance.json"
            if passed
            else f"{date}-live-physical-mic-latest-attempt.json"
        )
        written = evidence_root / filename
        written.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return doc, written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Privacy-minimized XiaoYu physical microphone acceptance verifier. "
            "It never opens the microphone and never stores transcript/reply text."
        )
    )
    parser.add_argument(
        "--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT
    )
    sub = parser.add_subparsers(dest="command", required=True)

    arm_parser = sub.add_parser("arm")
    arm_parser.add_argument("--log-path", type=Path)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument(
        "--user-attested",
        action="store_true",
        help="Assert that the new voice turn was spoken by the user into a physical microphone.",
    )
    verify_parser.add_argument("--evidence-root", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "arm":
        doc = arm(args.storage_root, args.log_path)
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    doc, written = verify(
        args.storage_root,
        user_attested=args.user_attested,
        evidence_root=args.evidence_root,
    )
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    if written is not None:
        print(f"evidence_path={written}")
    return 0 if doc["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
