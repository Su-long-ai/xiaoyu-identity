from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
import httpx
from datetime import datetime
from pathlib import Path
from typing import Any

from plugin.sdk.plugin import (
    NekoPluginBase,
    Ok,
    Err,
    SdkError,
    lifecycle,
    neko_plugin,
    plugin_entry,
    llm_tool,
    timer_interval,
)

_ROLE = "XiaoYu"
_CONTROLLER = "proactive_controller"
_STATE_VERSION = 3
_SEEN_LIMIT = 128
_CLASSIFIER_TIMEOUT_SECONDS = 8.0
_MAX_TEXT_CHARS = 500
_ACTIVITY_TIMELINE_VERSION = 1
_ACTIVITY_SAMPLE_SECONDS = 10
_ACTIVITY_RETENTION_SECONDS = 24 * 60 * 60
_ACTIVITY_MAX_SEGMENTS = 2000
_ACTIVITY_GAP_SECONDS = _ACTIVITY_SAMPLE_SECONDS * 3

_CANDIDATE_RE = re.compile(
    r"(安静|静一静|别.{0,8}(说|讲|聊|烦|扰|找|联系|主动|消息|出声)|"
    r"不要.{0,8}(说|讲|聊|烦|扰|找|联系|主动|消息|出声|看屏幕|看我屏幕|窥屏)|"
    r"闭嘴|打扰|主动找|主动联系|恢复|解除|继续.{0,6}(说|聊|找|联系)|"
    r"可以.{0,6}(说|聊|找|联系|看屏幕)|别.{0,6}(看屏幕|看我屏幕|窥屏)|"
    r"不要看屏幕|不要看我的屏幕|停止看屏幕|停止窥屏|恢复看屏幕|继续看屏幕|"
    r"quiet|silence|silent|shut\s*up|do\s*not\s*disturb|don't\s*bother|"
    r"stop\s+(talking|messaging|contacting|watching\s+(my\s+)?screen)|"
    r"resume|speak\s+again|talk\s+again|watch\s+(my\s+)?screen\s+again)",
    re.IGNORECASE,
)

_CLASSIFIER_SYSTEM = """You are a conservative interaction-policy classifier.
Decide whether the user's CURRENT message explicitly controls unsolicited/proactive communication, audible assistant speech, and/or autonomous screen viewing.

Return JSON only:
{"action":"quiet"|"resume"|"none","duration_minutes":null|integer,"speech_action":"mute"|"unmute"|"unchanged","vision_action":"block"|"allow"|"restore"|"unchanged"}

Definitions:
- quiet: the user explicitly asks the assistant to be quiet, stop talking, stop bothering/contacting/messaging them proactively, or temporarily stop initiating communication.
- resume: the user explicitly allows the assistant to resume speaking/initiating/contacting after a quiet period.
- none: everything else.
- speech_action=mute only when the user explicitly asks the assistant to make no audible speech/sound (for example 别说话, 安静, 闭嘴, 别出声).
- speech_action=unmute only when the user explicitly allows audible assistant speech again (for example 可以说话了, 继续说话, 解除静音).
- speech_action=unchanged for proactive-only or vision-only controls, and for unrelated messages.
- vision_action=block only when the user explicitly asks the assistant to stop looking at/watching their screen globally (for example 不要看屏幕, 别窥屏).
- vision_action=allow only when the user explicitly permits screen viewing again after blocking it (for example 可以看屏幕了, 继续看屏幕).
- vision_action=restore only for an explicit global reset such as 恢复正常 / 全部恢复; it restores the screen-consent value captured before this plugin blocked it.
- vision_action=unchanged for ordinary visual questions, one-image requests, topic avoidance, and unrelated messages.

Important distinctions:
- "别说话哦", "你先安静一会", "stay quiet", "shut up" => quiet + speech_action=mute.
- "别主动找我", "先别烦我", "don't bother me" => quiet + speech_action=unchanged.
- "可以说话了", "resume talking" => resume + speech_action=unmute.
- "继续吧，你可以主动找我了" => resume + speech_action=unchanged + vision_action=unchanged.
- "不要看屏幕", "别窥屏" => action=none + speech_action=unchanged + vision_action=block.
- "可以看屏幕了", "继续看屏幕" => action=none + speech_action=unchanged + vision_action=allow.
- "恢复正常", "全部恢复" => resume + speech_action=unmute + vision_action=restore.
- "我不想说话" means the USER does not want to talk; unless it also tells the assistant to stop, => none.
- "这个别说/别提这个话题" is topic avoidance, not global interaction control => none.
- "这条不用回复" is one-turn reply suppression, not a persistent proactive-control request => none.
- Negative emotion or silence alone => none.
- Never infer quiet/resume merely from context or politeness; require explicit control intent directed at the assistant.

duration_minutes:
- Only set for an explicit bounded duration (e.g. 10 minutes=10, half an hour=30, 2 hours=120), max 1440.
- Otherwise null. Do not invent a duration.
"""


def _default_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "initialized": False,
        "seen_event_ids": [],
        "quiet": False,
        "speech_muted": False,
        "vision_blocked": False,
        "previous_vision_enabled": None,
        "previous_proactive_chat_enabled": None,
        "quiet_until": None,
        "changed_at": None,
        "last_action": None,
    }


def _normalize_state(raw: Any) -> dict[str, Any]:
    state = _default_state()
    if isinstance(raw, dict):
        for key in state:
            if key in raw:
                state[key] = raw[key]
    state["version"] = _STATE_VERSION
    state["initialized"] = bool(state.get("initialized"))
    seen = state.get("seen_event_ids")
    state["seen_event_ids"] = [
        str(item) for item in (seen if isinstance(seen, list) else [])
        if isinstance(item, str) and item
    ][-_SEEN_LIMIT:]
    state["quiet"] = bool(state.get("quiet"))
    state["speech_muted"] = bool(state.get("speech_muted"))
    state["vision_blocked"] = bool(state.get("vision_blocked"))
    previous_vision = state.get("previous_vision_enabled")
    state["previous_vision_enabled"] = previous_vision if isinstance(previous_vision, bool) else None
    previous = state.get("previous_proactive_chat_enabled")
    state["previous_proactive_chat_enabled"] = previous if isinstance(previous, bool) else None
    until = state.get("quiet_until")
    state["quiet_until"] = float(until) if isinstance(until, (int, float)) and not isinstance(until, bool) else None
    return state


def parse_classifier_output(raw: str) -> dict[str, Any]:
    fallback = {"action": "none", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "unchanged"}
    if not isinstance(raw, str):
        return dict(fallback)
    text = raw.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*" + re.escape(fence) + r"$", "", text)
    try:
        value = json.loads(text)
    except Exception:
        match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
        if not match:
            return dict(fallback)
        try:
            value = json.loads(match.group(0))
        except Exception:
            return dict(fallback)
    if not isinstance(value, dict):
        return dict(fallback)
    action = str(value.get("action") or "none").strip().lower()
    if action not in {"quiet", "resume", "none"}:
        action = "none"
    duration = value.get("duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int) or not (1 <= duration <= 1440):
        duration = None
    if action != "quiet":
        duration = None
    speech_action = str(value.get("speech_action") or "unchanged").strip().lower()
    if speech_action not in {"mute", "unmute", "unchanged"}:
        speech_action = "unchanged"
    vision_action = str(value.get("vision_action") or "unchanged").strip().lower()
    if vision_action not in {"block", "allow", "restore", "unchanged"}:
        vision_action = "unchanged"
    return {"action": action, "duration_minutes": duration, "speech_action": speech_action, "vision_action": vision_action}


def candidate_needs_semantic_check(text: str) -> bool:
    return bool(isinstance(text, str) and _CANDIDATE_RE.search(text[:_MAX_TEXT_CHARS]))


def should_run_semantic_check(text: str, *, quiet: bool, vision_blocked: bool = False) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(quiet or vision_blocked or candidate_needs_semantic_check(text))


_FAST_SPEECH_MUTE = {
    "不说话", "别说话", "不要说话", "先别说话", "先不要说话",
    "安静", "安静一下", "先安静", "闭嘴", "别出声", "不要出声",
}
_FAST_SPEECH_UNMUTE = {
    "可以说话了", "说话吧", "继续说", "继续说话", "恢复说话", "解除静音",
}
_FAST_VISION_BLOCK = {"不要看屏幕", "别看屏幕", "不要看我的屏幕", "别看我的屏幕", "停止看屏幕", "别窥屏", "不要窥屏"}
_FAST_VISION_ALLOW = {"可以看屏幕了", "可以看我的屏幕了", "继续看屏幕", "恢复看屏幕", "允许看屏幕"}
_FAST_FULL_RESUME = {"恢复正常", "全部恢复", "恢复所有", "恢复全部"}
_FAST_CONTROL_STRIP_RE = re.compile(r"[\s，。！？、,.!?;；:：~～…]+")
_FAST_CONTROL_PREFIXES = ("小鱼小鱼", "小鱼", "请", "麻烦")


def _normalize_fast_control(text: str) -> str:
    value = _FAST_CONTROL_STRIP_RE.sub("", str(text or "").strip().lower())
    changed = True
    while changed:
        changed = False
        for prefix in _FAST_CONTROL_PREFIXES:
            if value.startswith(prefix) and len(value) > len(prefix):
                value = value[len(prefix):]
                changed = True
                break
    return value


def fast_speech_control(text: str) -> dict[str, Any] | None:
    value = _normalize_fast_control(text)
    if value in _FAST_SPEECH_MUTE:
        return {"action": "quiet", "duration_minutes": None, "speech_action": "mute"}
    if value in _FAST_SPEECH_UNMUTE:
        return {"action": "resume", "duration_minutes": None, "speech_action": "unmute"}
    return None


def fast_vision_control(text: str) -> str | None:
    value = _normalize_fast_control(text)
    if value in _FAST_VISION_BLOCK:
        return "block"
    if value in _FAST_VISION_ALLOW:
        return "allow"
    return None


def fast_full_resume(text: str) -> bool:
    return _normalize_fast_control(text) in _FAST_FULL_RESUME


def _extract_event(record: Any) -> dict[str, Any]:
    if hasattr(record, "dump") and callable(record.dump):
        try:
            raw = record.dump()
        except Exception:
            raw = {}
    else:
        raw = record
    return dict(raw) if isinstance(raw, dict) else {}


def _default_activity_timeline(now: float | None = None) -> dict[str, Any]:
    ts = float(time.time() if now is None else now)
    return {"version": _ACTIVITY_TIMELINE_VERSION, "created_at": ts, "segments": []}


def _normalize_activity_timeline(raw: Any, *, now: float | None = None) -> dict[str, Any]:
    ts = float(time.time() if now is None else now)
    timeline = _default_activity_timeline(ts)
    if isinstance(raw, dict):
        created = raw.get("created_at")
        if isinstance(created, (int, float)) and not isinstance(created, bool):
            timeline["created_at"] = float(created)
        source = raw.get("segments")
        if isinstance(source, list):
            cleaned: list[dict[str, Any]] = []
            cutoff = ts - _ACTIVITY_RETENTION_SECONDS
            for item in source:
                if not isinstance(item, dict):
                    continue
                start = item.get("start")
                end = item.get("end")
                if (
                    isinstance(start, bool) or isinstance(end, bool)
                    or not isinstance(start, (int, float))
                    or not isinstance(end, (int, float))
                ):
                    continue
                start_f = float(start)
                end_f = max(start_f, float(end))
                if end_f < cutoff:
                    continue
                category = str(item.get("category") or "unknown")[:80]
                app = item.get("app")
                app_value = str(app)[:120] if isinstance(app, str) and app.strip() else None
                privacy = str(item.get("privacy_state") or "visible")[:24]
                samples = item.get("samples")
                sample_count = int(samples) if isinstance(samples, int) and not isinstance(samples, bool) and samples > 0 else 1
                cleaned.append({
                    "start": start_f,
                    "end": end_f,
                    "category": category,
                    "app": app_value,
                    "privacy_state": privacy,
                    "samples": sample_count,
                })
            cleaned.sort(key=lambda item: item["start"])
            timeline["segments"] = cleaned[-_ACTIVITY_MAX_SEGMENTS:]
    timeline["version"] = _ACTIVITY_TIMELINE_VERSION
    return timeline


def _append_activity_sample(
    timeline: dict[str, Any],
    *,
    now: float,
    category: str,
    app: str | None,
    privacy_state: str,
) -> dict[str, Any]:
    normalized = _normalize_activity_timeline(timeline, now=now)
    segments = normalized["segments"]
    sample = {
        "start": float(now),
        "end": float(now),
        "category": str(category or "unknown")[:80],
        "app": str(app)[:120] if isinstance(app, str) and app.strip() else None,
        "privacy_state": str(privacy_state or "unavailable")[:24],
        "samples": 1,
    }
    if segments:
        previous = segments[-1]
        same = (
            previous.get("category") == sample["category"]
            and previous.get("app") == sample["app"]
            and previous.get("privacy_state") == sample["privacy_state"]
            and float(now) - float(previous.get("end") or 0.0) <= _ACTIVITY_GAP_SECONDS
        )
        if same:
            previous["end"] = float(now)
            previous["samples"] = int(previous.get("samples") or 0) + 1
            return normalized
    segments.append(sample)
    normalized["segments"] = segments[-_ACTIVITY_MAX_SEGMENTS:]
    return normalized


def _iso_local(ts: float) -> str:
    value = float(ts)
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return f"epoch:{value:.3f}"


def build_recent_activity_report(
    timeline: dict[str, Any],
    *,
    minutes: int = 60,
    now: float | None = None,
) -> dict[str, Any]:
    current = float(time.time() if now is None else now)
    try:
        lookback = int(minutes)
    except (TypeError, ValueError):
        lookback = 60
    lookback = min(1440, max(1, lookback))
    requested_start = current - lookback * 60
    normalized = _normalize_activity_timeline(timeline, now=current)
    all_segments = normalized["segments"]
    selected = [
        segment for segment in all_segments
        if float(segment["end"]) >= requested_start and float(segment["start"]) <= current
    ]

    rendered: list[dict[str, Any]] = []
    by_app: dict[str, float] = {}
    by_category: dict[str, float] = {}
    observed_seconds = 0.0
    gaps: list[dict[str, Any]] = []
    previous_end: float | None = None
    for segment in selected:
        start = max(requested_start, float(segment["start"]))
        end = min(current, float(segment["end"]))
        if previous_end is not None and start - previous_end > _ACTIVITY_GAP_SECONDS:
            gaps.append({
                "start": _iso_local(previous_end),
                "end": _iso_local(start),
                "seconds": round(start - previous_end, 1),
            })
        previous_end = end if previous_end is None else max(previous_end, end)
        duration = max(float(_ACTIVITY_SAMPLE_SECONDS), end - start)
        observed_seconds += duration
        app = segment.get("app")
        category = str(segment.get("category") or "unknown")
        if isinstance(app, str) and app:
            by_app[app] = by_app.get(app, 0.0) + duration
        by_category[category] = by_category.get(category, 0.0) + duration
        rendered.append({
            "start": _iso_local(start),
            "end": _iso_local(end),
            "duration_seconds": round(duration, 1),
            "category": category,
            "app": app,
            "privacy_state": segment.get("privacy_state"),
        })

    first_observation = float(selected[0]["start"]) if selected else None
    last_observation = float(selected[-1]["end"]) if selected else None
    complete = bool(
        selected
        and first_observation <= requested_start + _ACTIVITY_GAP_SECONDS
        and last_observation >= current - _ACTIVITY_GAP_SECONDS
        and not gaps
    )
    return {
        "requested_minutes": lookback,
        "requested_start": _iso_local(requested_start),
        "requested_end": _iso_local(current),
        "coverage": {
            "first_observation": _iso_local(first_observation) if first_observation is not None else None,
            "last_observation": _iso_local(last_observation) if last_observation is not None else None,
            "complete": complete,
            "observed_seconds_approx": round(observed_seconds, 1),
            "gaps": gaps[:20],
        },
        "summary": {
            "by_app_seconds": {key: round(value, 1) for key, value in sorted(by_app.items(), key=lambda item: item[1], reverse=True)},
            "by_category_seconds": {key: round(value, 1) for key, value in sorted(by_category.items(), key=lambda item: item[1], reverse=True)},
        },
        "segments": rendered[-120:],
        "evidence_policy": (
            "This is a local foreground-activity timeline using N.E.K.O's existing classifier. "
            "It stores canonical app/category only, never raw window titles or screenshots. "
            "Missing coverage or gaps mean UNKNOWN, never inactivity. Do not claim the user did nothing "
            "unless an explicit observed state supports that conclusion."
        ),
    }


@neko_plugin
class XiaoYuInteractionPolicyPlugin(NekoPluginBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.logger = self.enable_file_logging(log_level="INFO")
        self._lock = asyncio.Lock()
        self._state_path: Path | None = None
        self._activity_path: Path | None = None
        self._activity_collector = None

    @lifecycle(id="startup")
    async def startup(self, **_):
        self._state_path = self.data_path("state.json")
        self._activity_path = self.data_path("activity_timeline.json")
        self._save_activity_timeline(self._load_activity_timeline())
        try:
            from main_logic.activity.system_signals import SystemSignalCollector
            self._activity_collector = SystemSignalCollector(poll_interval=5.0)
            await self._activity_collector.start()
        except Exception as exc:
            self._activity_collector = None
            self.logger.warning("recent activity collector failed to start err_type={}", type(exc).__name__)
        state = self._load_state()
        # Persist the normalized schema on startup. Legacy v1 quiet state is
        # preserved, while new fields receive conservative defaults unless the
        # private state file already carries an explicit migration value.
        self._save_state(state)

        controller = await self.plugins.require_enabled(_CONTROLLER)
        if isinstance(controller, Err):
            return Err(SdkError("N.E.K.O proactive_controller is required"))

        records = await self.bus.memory.get(bucket_id=_ROLE, limit=20, timeout=3.0)
        recent_ids = []
        for record in records:
            event = _extract_event(record)
            event_id = str(event.get("event_id") or "")
            if event_id:
                recent_ids.append(event_id)
        if not state["initialized"]:
            state["initialized"] = True
            state["seen_event_ids"] = recent_ids[-_SEEN_LIMIT:]
            self._save_state(state)

        await self._reconcile_state()
        return Ok({"status": "ready", "role": _ROLE})

    @lifecycle(id="shutdown")
    async def shutdown(self, **_):
        collector = self._activity_collector
        self._activity_collector = None
        if collector is not None:
            try:
                await collector.stop()
            except Exception as exc:
                self.logger.debug("recent activity collector stop failed err_type={}", type(exc).__name__)
        return Ok({"status": "shutdown"})

    @plugin_entry(
        id="get_state",
        name="XiaoYu interaction policy state",
        description="Read the private hard quiet/resume state without user message content.",
        metadata={"agent_hidden": True},
    )
    async def get_state(self, **_):
        return Ok(self._public_state(self._load_state()))

    @plugin_entry(
        id="recent_activity",
        name="Recent owner computer activity",
        description=(
            "Query XiaoYu's locally observed foreground activity timeline for the last N minutes. "
            "Use this when the owner asks what they were doing, using, working on, playing, or viewing "
            "over a recent period. The result includes explicit coverage/gaps; missing evidence is UNKNOWN, "
            "never proof that the owner did nothing."
        ),
    )
    async def recent_activity(self, minutes: int = 60, **_):
        return Ok(build_recent_activity_report(self._load_activity_timeline(), minutes=minutes))

    @llm_tool(
        name="xiaoyu_recent_activity",
        description=(
            "Look up the owner's locally observed recent computer activity when they ask what they were "
            "doing/using/working on/playing/viewing over the last minutes or hours. This is retrospective "
            "evidence, unlike the current-screen view. Always respect coverage.complete and gaps: missing "
            "coverage is unknown and must never be described as inactivity. No screenshots or raw window "
            "titles are returned."
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1440,
                    "default": 60,
                    "description": "How many minutes back from now to inspect.",
                },
            },
        },
        timeout=5.0,
        role=_ROLE,
    )
    async def xiaoyu_recent_activity(self, minutes: int = 60, **_):
        return build_recent_activity_report(self._load_activity_timeline(), minutes=minutes)

    @timer_interval(id="sample_recent_activity", seconds=_ACTIVITY_SAMPLE_SECONDS, auto_start=True)
    async def sample_recent_activity(self, **_):
        now = time.time()
        category = "unavailable"
        app: str | None = None
        privacy_state = "unavailable"
        try:
            from utils.preferences import is_privacy_mode_enabled
            if is_privacy_mode_enabled():
                category = "private"
                privacy_state = "private"
            else:
                from main_logic.activity.state_machine import observation_from_system
                collector = self._activity_collector
                system_snapshot = collector.snapshot() if collector is not None else None
                if system_snapshot is not None and bool(getattr(system_snapshot, "os_signals_available", True)):
                    observation = observation_from_system(system_snapshot)
                    privacy_state = "visible"
                    if observation is not None:
                        category = str(getattr(observation, "category", "") or "unknown")
                        if category == "private":
                            privacy_state = "private"
                        else:
                            canonical = getattr(observation, "canonical", None)
                            if isinstance(canonical, str) and canonical.strip():
                                app = canonical.strip()[:120]
                            else:
                                process_name = getattr(system_snapshot, "process_name", None)
                                if isinstance(process_name, str) and process_name.strip():
                                    fallback = process_name.strip()
                                    if fallback.lower().endswith(".exe"):
                                        fallback = fallback[:-4]
                                    app = fallback[:120] or None
                    else:
                        category = "unknown"
                else:
                    category = "unavailable"
        except Exception as exc:
            self.logger.debug("recent activity sample unavailable err_type={}", type(exc).__name__)

        timeline = _append_activity_sample(
            self._load_activity_timeline(),
            now=now,
            category=category,
            app=app,
            privacy_state=privacy_state,
        )
        self._save_activity_timeline(timeline)
        return Ok({"sampled": True, "category": category, "app": app, "privacy_state": privacy_state})

    @timer_interval(id="scan_user_control_intent", seconds=1, auto_start=True)
    async def scan_user_control_intent(self, **_):
        if self._lock.locked():
            return Ok({"busy": True})
        async with self._lock:
            state = await self._expire_if_needed(self._load_state())

            records = await self.bus.memory.get(bucket_id=_ROLE, limit=20, timeout=3.0)
            seen = set(state["seen_event_ids"])
            pending: list[dict[str, Any]] = []
            for record in records:
                event = _extract_event(record)
                event_id = str(event.get("event_id") or "")
                if not event_id or event_id in seen:
                    continue
                if str(event.get("type") or "") != "user_message":
                    continue
                if str(event.get("lanlan") or "") not in {"", _ROLE}:
                    continue
                pending.append(event)

            pending.sort(key=lambda item: float(item.get("_ts") or 0.0))
            decisions = 0
            for event in pending:
                event_id = str(event.get("event_id") or "")
                content = event.get("content")
                text = content.strip() if isinstance(content, str) else ""

                state["seen_event_ids"].append(event_id)
                state["seen_event_ids"] = state["seen_event_ids"][-_SEEN_LIMIT:]
                self._save_state(state)

                if not text:
                    continue

                # Outside quiet mode, keep the cheap lexical prefilter so ordinary
                # conversation does not pay an extra classifier call. Once the hard
                # quiet latch is active, however, every user message is eligible for
                # semantic resume detection: natural phrases such as "好了你正常来吧"
                # should be understood by the model even when they are not in the
                # conservative candidate vocabulary.
                if fast_full_resume(text):
                    decision = {
                        "action": "resume",
                        "duration_minutes": None,
                        "speech_action": "unmute",
                        "vision_action": "restore",
                    }
                else:
                    decision = fast_speech_control(text)
                    if decision is not None:
                        decision["vision_action"] = "unchanged"
                    else:
                        vision_action = fast_vision_control(text)
                        if vision_action is not None:
                            decision = {
                                "action": "none",
                                "duration_minutes": None,
                                "speech_action": "unchanged",
                                "vision_action": vision_action,
                            }
                        else:
                            if not should_run_semantic_check(
                                text,
                                quiet=bool(state["quiet"]),
                                vision_blocked=bool(state["vision_blocked"]),
                            ):
                                continue
                            decision = await self._classify(text[:_MAX_TEXT_CHARS])
                action = decision["action"]
                if action == "quiet":
                    state = await self._set_quiet(state, decision.get("duration_minutes"))
                    decisions += 1
                elif action == "resume":
                    state = await self._resume(state, reason="user")
                    decisions += 1

                speech_action = decision.get("speech_action")
                if speech_action == "mute":
                    state = self._set_speech_muted(state, True, reason="user")
                    decisions += 1
                elif speech_action == "unmute":
                    state = self._set_speech_muted(state, False, reason="user")
                    decisions += 1

                vision_action = decision.get("vision_action")
                if vision_action == "block":
                    state = await self._set_vision_blocked(state, True, reason="user")
                    decisions += 1
                elif vision_action == "allow":
                    state = await self._allow_vision(state, reason="user")
                    decisions += 1
                elif vision_action == "restore":
                    state = await self._restore_vision(state, reason="user")
                    decisions += 1

            await self._enforce_quiet_if_needed(state)
            return Ok({"processed": len(pending), "decisions": decisions, **self._public_state(state)})

    async def _classify(self, text: str) -> dict[str, Any]:
        from utils.config_manager import get_config_manager
        from utils.llm_client import HumanMessage, SystemMessage, create_chat_llm_async

        try:
            cfg = await get_config_manager().aget_model_api_config("emotion")
            model = cfg.get("model")
            api_key = cfg.get("api_key")
            base_url = cfg.get("base_url")
            if not model or not api_key:
                return {"action": "none", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "unchanged"}
            llm = await create_chat_llm_async(
                model,
                base_url,
                api_key,
                temperature=0.0,
                max_completion_tokens=96,
                timeout=_CLASSIFIER_TIMEOUT_SECONDS,
                provider_type=cfg.get("provider_type"),
            )
            async with llm:
                response = await asyncio.wait_for(
                    llm.ainvoke([
                        SystemMessage(content=_CLASSIFIER_SYSTEM),
                        HumanMessage(content=text),
                    ]),
                    timeout=_CLASSIFIER_TIMEOUT_SECONDS,
                )
            raw = getattr(response, "content", "") or ""
            decision = parse_classifier_output(raw if isinstance(raw, str) else str(raw))
            self.logger.info(
                "semantic interaction decision action={} duration_set={} input_chars={}",
                decision["action"],
                decision["duration_minutes"] is not None,
                len(text),
            )
            return decision
        except Exception as exc:
            self.logger.warning(
                "semantic interaction classifier failed err_type={} input_chars={}",
                type(exc).__name__,
                len(text),
            )
            return {"action": "none", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "unchanged"}

    async def _controller_state(self) -> dict[str, Any]:
        result = await self.plugins.call_entry(f"{_CONTROLLER}:get_state")
        if isinstance(result, Err):
            raise RuntimeError("proactive_controller:get_state failed")
        value = result.value
        if not isinstance(value, dict):
            raise RuntimeError("proactive_controller:get_state returned non-object")
        return value

    async def _set_proactive(self, enabled: bool) -> None:
        result = await self.plugins.call_entry(
            f"{_CONTROLLER}:set_settings",
            {"settings": {"proactiveChatEnabled": bool(enabled)}},
        )
        if isinstance(result, Err):
            raise RuntimeError("proactive_controller:set_settings failed")

    async def _current_proactive_enabled(self) -> bool:
        value = await self._controller_state()
        settings = value.get("settings")
        if not isinstance(settings, dict) or not isinstance(settings.get("proactiveChatEnabled"), bool):
            raise RuntimeError("controller state lacks proactiveChatEnabled")
        return bool(settings["proactiveChatEnabled"])

    async def _set_quiet(self, state: dict[str, Any], duration_minutes: int | None) -> dict[str, Any]:
        current = await self._current_proactive_enabled()
        if not state["quiet"]:
            state["previous_proactive_chat_enabled"] = current
        await self._set_proactive(False)
        now = time.time()
        state["quiet"] = True
        state["quiet_until"] = now + duration_minutes * 60 if duration_minutes is not None else None
        state["changed_at"] = now
        state["last_action"] = "quiet"
        self._save_state(state)
        self.logger.info("hard quiet enabled duration_set={}", duration_minutes is not None)
        return state

    async def _resume(self, state: dict[str, Any], *, reason: str) -> dict[str, Any]:
        if state["quiet"]:
            restore = state.get("previous_proactive_chat_enabled")
            if not isinstance(restore, bool):
                restore = True
            await self._set_proactive(restore)
        now = time.time()
        state["quiet"] = False
        state["previous_proactive_chat_enabled"] = None
        state["quiet_until"] = None
        state["changed_at"] = now
        state["last_action"] = f"resume:{reason}"
        self._save_state(state)
        self.logger.info("hard quiet cleared reason={}", reason)
        return state

    async def _write_native_vision_enabled(self, enabled: bool) -> bool | None:
        """CAS-write the native user-owned privacy switch after explicit owner text intent.

        This intentionally uses N.E.K.O's normal user conversation-settings route,
        not proactive_controller (which correctly forbids plugins from changing
        user-owned privacy fields). The semantic adapter is only translating an
        explicit owner message into the same persisted choice the UI writes.
        """
        from config import MAIN_SERVER_PORT

        url = f"http://127.0.0.1:{int(MAIN_SERVER_PORT)}/api/config/conversation-settings"
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            for _attempt in range(3):
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                settings = payload.get("settings") if isinstance(payload, dict) else None
                if not isinstance(settings, dict):
                    raise RuntimeError("native conversation-settings GET returned no settings object")
                previous = settings.get("proactiveVisionEnabled")
                previous_bool = previous if isinstance(previous, bool) else None
                if previous_bool == bool(enabled):
                    return previous_bool
                headers = {}
                etag = response.headers.get("etag")
                if etag:
                    headers["If-Match"] = etag
                saved = await client.post(url, json={"proactiveVisionEnabled": bool(enabled)}, headers=headers)
                if saved.status_code == 412:
                    continue
                saved.raise_for_status()
                saved_payload = saved.json()
                saved_settings = saved_payload.get("settings") if isinstance(saved_payload, dict) else None
                if not isinstance(saved_settings, dict) or saved_settings.get("proactiveVisionEnabled") != bool(enabled):
                    raise RuntimeError("native conversation-settings write did not persist vision choice")
                return previous_bool
        raise RuntimeError("native conversation-settings vision write conflicted repeatedly")

    async def _set_vision_blocked(self, state: dict[str, Any], blocked: bool, *, reason: str) -> dict[str, Any]:
        if not blocked:
            return await self._restore_vision(state, reason=reason)
        previous = await self._write_native_vision_enabled(False)
        if not state.get("vision_blocked"):
            state["previous_vision_enabled"] = previous
        state["vision_blocked"] = True
        state["changed_at"] = time.time()
        state["last_action"] = f"vision_block:{reason}"
        self._save_state(state)
        self.logger.info("native autonomous vision blocked reason={}", reason)
        return state

    async def _allow_vision(self, state: dict[str, Any], *, reason: str) -> dict[str, Any]:
        await self._write_native_vision_enabled(True)
        state["vision_blocked"] = False
        state["previous_vision_enabled"] = None
        state["changed_at"] = time.time()
        state["last_action"] = f"vision_allow:{reason}"
        self._save_state(state)
        self.logger.info("native autonomous vision explicitly allowed reason={}", reason)
        return state

    async def _restore_vision(self, state: dict[str, Any], *, reason: str) -> dict[str, Any]:
        if state.get("vision_blocked"):
            previous = state.get("previous_vision_enabled")
            if isinstance(previous, bool):
                await self._write_native_vision_enabled(previous)
        state["vision_blocked"] = False
        state["previous_vision_enabled"] = None
        state["changed_at"] = time.time()
        state["last_action"] = f"vision_restore:{reason}"
        self._save_state(state)
        self.logger.info("native autonomous vision restored reason={}", reason)
        return state

    def _set_speech_muted(self, state: dict[str, Any], muted: bool, *, reason: str) -> dict[str, Any]:
        state["speech_muted"] = bool(muted)
        state["changed_at"] = time.time()
        state["last_action"] = ("speech_mute:" if muted else "speech_unmute:") + reason
        self._save_state(state)
        self.logger.info("hard speech mute changed muted={} reason={}", bool(muted), reason)
        return state

    async def _expire_if_needed(self, state: dict[str, Any]) -> dict[str, Any]:
        until = state.get("quiet_until")
        if state["quiet"] and isinstance(until, (int, float)) and time.time() >= float(until):
            state = await self._resume(state, reason="expired")
            if state.get("speech_muted"):
                state = self._set_speech_muted(state, False, reason="expired")
        return state

    async def _enforce_quiet_if_needed(self, state: dict[str, Any]) -> None:
        if not state["quiet"]:
            return
        try:
            if await self._current_proactive_enabled():
                await self._set_proactive(False)
                self.logger.info("quiet latch reconciled proactiveChatEnabled back to false")
        except Exception as exc:
            self.logger.warning("quiet reconciliation failed err_type={}", type(exc).__name__)

    async def _reconcile_state(self) -> None:
        async with self._lock:
            state = await self._expire_if_needed(self._load_state())
            await self._enforce_quiet_if_needed(state)

    def _state_file(self) -> Path:
        if self._state_path is None:
            self._state_path = self.data_path("state.json")
        return self._state_path

    def _activity_file(self) -> Path:
        if self._activity_path is None:
            self._activity_path = self.data_path("activity_timeline.json")
        return self._activity_path

    def _load_activity_timeline(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._activity_file().read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        return _normalize_activity_timeline(raw)

    def _save_activity_timeline(self, timeline: dict[str, Any]) -> None:
        path = self._activity_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = _normalize_activity_timeline(timeline)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(normalized, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._state_file().read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        return _normalize_state(raw)

    def _save_state(self, state: dict[str, Any]) -> None:
        path = self._state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(_normalize_state(state), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    @staticmethod
    def _public_state(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "quiet": bool(state.get("quiet")),
            "speech_muted": bool(state.get("speech_muted")),
            "vision_blocked": bool(state.get("vision_blocked")),
            "quiet_until": state.get("quiet_until"),
            "last_action": state.get("last_action"),
            "seen_event_count": len(state.get("seen_event_ids") or []),
        }
