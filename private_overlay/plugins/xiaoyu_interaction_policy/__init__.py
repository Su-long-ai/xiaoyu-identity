from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import httpx
from datetime import datetime, timedelta, timezone
from typing import Any

from plugin.sdk.plugin import (
    NekoPluginBase,
    Ok,
    Err,
    SdkError,
    lifecycle,
    neko_plugin,
    on_event,
    plugin_entry,
    llm_tool,
    timer_interval,
)

_ROLE = "XiaoYu"
_CONTROLLER = "proactive_controller"
_STATE_VERSION = 5
_SEEN_LIMIT = 128
_CLASSIFIER_TIMEOUT_SECONDS = 8.0
_CLASSIFIER_MODEL_USAGE = "interaction_classifier"
_STATE_STORE_KEY = "interaction_state"
_MAX_TEXT_CHARS = 500
_ACTIVITYWATCH_BASE_URL = "http://127.0.0.1:5600/api/0"
_ACTIVITYWATCH_TIMEOUT_SECONDS = 4.0
_ACTIVITYWATCH_COVERAGE_GRACE_SECONDS = 15.0


class _CrossLoopAsyncLock:
    """Process-local async mutex that is not bound to one asyncio loop.

    N.E.K.O plugin lifecycle/timer/custom-event/conversation-watcher callbacks
    may execute through different asyncio.run loops. asyncio.Lock can bind to
    one loop after contention, so use one process-wide thread lock and acquire
    it non-blockingly while yielding to the current loop.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self):
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(0.01)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._lock.release()
        return False

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
        "conversation_cursor_initialized": False,
        "last_conversation_observed_at": None,
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
    state["conversation_cursor_initialized"] = bool(
        state.get("conversation_cursor_initialized")
    )
    observed = state.get("last_conversation_observed_at")
    state["last_conversation_observed_at"] = (
        float(observed)
        if isinstance(observed, (int, float))
        and not isinstance(observed, bool)
        else None
    )
    seen = state.get("seen_event_ids")
    state["seen_event_ids"] = [
        str(item) for item in (seen if isinstance(seen, list) else [])
        if isinstance(item, str) and item
    ][-_SEEN_LIMIT:]
    state["quiet"] = bool(state.get("quiet"))
    # v4 contract: audible speech is no longer independently mutable. Quiet
    # suppresses the whole assistant reply (text + its paired audio); whenever
    # a reply is allowed through, audio remains enabled. Keep this legacy field
    # only for compatibility with older state readers.
    state["speech_muted"] = False
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
    "可以说话了", "可以说了", "你可以说了", "说话吧", "说吧", "你说吧", "那你说吧", "那就说吧",
    "继续说", "继续说吧", "继续说话", "恢复说话", "解除静音",
}
_FAST_VISION_BLOCK = {"不要看屏幕", "别看屏幕", "不要看我的屏幕", "别看我的屏幕", "停止看屏幕", "别窥屏", "不要窥屏"}
_FAST_VISION_ALLOW = {"可以看屏幕了", "可以看我的屏幕了", "继续看屏幕", "恢复看屏幕", "允许看屏幕"}
_FAST_FULL_RESUME = {"恢复正常", "全部恢复", "恢复所有", "恢复全部"}

# Semantic classifiers may recognize novel wording, but they never own hard
# execution.  Every model-proposed persistent control is admitted only when the
# user's literal text contains deterministic evidence of that control.  This
# prevents troubleshooting/preferences such as "语速还是太快了" or "怎么没声音"
# from being promoted into a durable speech mute.
_SEMANTIC_SPEECH_MUTE_RE = re.compile(
    r"(?:"
    r"(?:别|不要|不许|不准|禁止|停止|先别|先不要|暂时别|暂时不要|别再|不要再)"
    r".{0,10}(?:说话|讲话|开口|出声|发声|说|讲)"
    r"|(?:安静|静一静|闭嘴)(?:一下|一会儿?|会儿?)?"
    r"|(?:shut\s*up|be\s+(?:quiet|silent)|(?:do\s*not|don't|stop)\s+(?:talk|talking|speak|speaking|make\s+(?:a\s+)?sound))"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_SPEECH_UNMUTE_RE = re.compile(
    r"(?:"
    r"(?:可以|能|允许|继续|恢复|重新|开始|尽管|现在可以).{0,10}(?:说话|讲话|开口|出声|发声|说|讲)"
    r"|(?:解除|取消).{0,6}(?:静音|禁言)"
    r"|(?:resume|continue|start)\s+(?:talking|speaking)"
    r"|(?:speak|talk)(?:\s+(?:to|with)\s+me)?\s+again"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_PROACTIVE_QUIET_RE = re.compile(
    r"(?:"
    r"(?:别|不要|停止|先别|先不要|暂时别|暂时不要|别再|不要再)"
    r".{0,12}(?:主动|找我|联系我|打扰我|烦我|给我发消息|发消息|消息我)"
    r"|(?:勿扰|免打扰)"
    r"|(?:do\s*not|don't|stop)\s+(?:bother|contact|message|ping)(?:ing)?\s*(?:me)?"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_PROACTIVE_RESUME_RE = re.compile(
    r"(?:"
    r"(?:可以|继续|恢复|重新|允许).{0,12}(?:主动|找我|联系我|打扰我|给我发消息|发消息)"
    r"|(?:恢复正常|正常来吧|正常说吧|正常聊吧|好了.{0,6}正常.{0,4}吧)"
    r"|(?:resume|continue|start)\s+(?:contacting|messaging|pinging)"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_VISION_BLOCK_RE = re.compile(
    r"(?:"
    r"(?:别|不要|停止|先别|先不要|禁止).{0,10}(?:看|观察|盯|窥).{0,6}(?:屏幕|屏|桌面)"
    r"|(?:别|不要|停止|禁止).{0,6}(?:窥屏)"
    r"|(?:do\s*not|don't|stop)\s+(?:watching|looking\s+at|viewing)\s+(?:my\s+)?screen"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_VISION_ALLOW_RE = re.compile(
    r"(?:"
    r"(?:可以|继续|恢复|重新|允许).{0,10}(?:看|观察|盯).{0,6}(?:屏幕|屏|桌面)"
    r"|(?:可以|继续|恢复|允许).{0,6}(?:窥屏)"
    r"|(?:resume|continue|start)\s+(?:watching|viewing)\s+(?:my\s+)?screen"
    r")",
    re.IGNORECASE,
)

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


def gate_semantic_hard_control(text: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Fail closed from model suggestion to persistent interaction control.

    Fast exact commands are handled before this function.  Semantic inference
    remains useful for novel phrasing, but literal command evidence is required
    for every durable hard effect.
    """
    gated = dict(decision or {})
    raw = str(text or "")[:_MAX_TEXT_CHARS]
    action = str(gated.get("action") or "none").strip().lower()
    speech_action = str(gated.get("speech_action") or "unchanged").strip().lower()
    vision_action = str(gated.get("vision_action") or "unchanged").strip().lower()

    speech_mute = bool(_SEMANTIC_SPEECH_MUTE_RE.search(raw))
    speech_unmute = bool(_SEMANTIC_SPEECH_UNMUTE_RE.search(raw))
    proactive_quiet = bool(_SEMANTIC_PROACTIVE_QUIET_RE.search(raw))
    proactive_resume = bool(_SEMANTIC_PROACTIVE_RESUME_RE.search(raw))
    vision_block = bool(_SEMANTIC_VISION_BLOCK_RE.search(raw))
    vision_allow = bool(_SEMANTIC_VISION_ALLOW_RE.search(raw))
    global_resume = fast_full_resume(raw)

    if speech_action == "mute" and not speech_mute:
        gated["speech_action"] = "unchanged"
    elif speech_action == "unmute" and not (speech_unmute or global_resume):
        gated["speech_action"] = "unchanged"

    if action == "quiet" and not (speech_mute or proactive_quiet):
        gated["action"] = "none"
        gated["duration_minutes"] = None
    elif action == "resume" and not (speech_unmute or proactive_resume or global_resume):
        gated["action"] = "none"
        gated["duration_minutes"] = None

    if vision_action == "block" and not vision_block:
        gated["vision_action"] = "unchanged"
    elif vision_action == "allow" and not vision_allow:
        gated["vision_action"] = "unchanged"
    elif vision_action == "restore" and not global_resume:
        gated["vision_action"] = "unchanged"

    if gated.get("action") != "quiet":
        gated["duration_minutes"] = None
    return gated


def _extract_event(record: Any) -> dict[str, Any]:
    if hasattr(record, "dump") and callable(record.dump):
        try:
            raw = record.dump()
        except Exception:
            raw = {}
    else:
        raw = record
    return dict(raw) if isinstance(raw, dict) else {}


def _iso_local(ts: float) -> str:
    value = float(ts)
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return f"epoch:{value:.3f}"


def _parse_activitywatch_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _select_activitywatch_buckets(buckets: Any, hostname: str | None) -> tuple[str | None, str | None]:
    if not isinstance(buckets, dict):
        return None, None
    candidates: dict[str, dict[str, list[tuple[str, dict[str, Any]]]]] = {}
    for bucket_id, meta in buckets.items():
        if not isinstance(meta, dict):
            continue
        host = str(meta.get("hostname") or "")
        kind = str(meta.get("type") or "")
        if not host:
            continue
        role = "window" if kind == "currentwindow" else "afk" if kind == "afkstatus" else ""
        if not role:
            continue
        candidates.setdefault(host, {}).setdefault(role, []).append((str(bucket_id), meta))

    ordered_hosts = []
    if hostname and hostname in candidates:
        ordered_hosts.append(hostname)
    ordered_hosts.extend(host for host in candidates if host not in ordered_hosts)

    def newest(items: list[tuple[str, dict[str, Any]]]) -> str | None:
        if not items:
            return None
        items = sorted(
            items,
            key=lambda item: str(item[1].get("last_updated") or item[1].get("created") or ""),
            reverse=True,
        )
        return items[0][0]

    for host in ordered_hosts:
        roles = candidates[host]
        window = newest(roles.get("window", []))
        afk = newest(roles.get("afk", []))
        if window and afk:
            return window, afk
    return None, None


def _sanitize_activitywatch_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        data = {}
    app = data.get("app")
    app_value = str(app)[:120] if isinstance(app, str) and app.strip() else None
    try:
        duration = max(0.0, float(event.get("duration") or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        timestamp = None
    return {"timestamp": timestamp, "duration_seconds": round(duration, 3), "app": app_value}


def _activitywatch_report_from_result(
    result: Any,
    *,
    minutes: int,
    requested_start: datetime,
    requested_end: datetime,
    version: str | None,
) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    raw = [_sanitize_activitywatch_event(item) for item in payload.get("raw", [])]
    raw = [item for item in raw if item is not None]
    active = [_sanitize_activitywatch_event(item) for item in payload.get("events", [])]
    active = [item for item in active if item is not None]
    apps = [_sanitize_activitywatch_event(item) for item in payload.get("apps", [])]
    apps = [item for item in apps if item is not None]

    first_ts = None
    last_end = None
    gaps: list[dict[str, Any]] = []
    previous_end = None
    for item in raw:
        ts = _parse_activitywatch_timestamp(item.get("timestamp"))
        if ts is None:
            continue
        end = ts + float(item.get("duration_seconds") or 0.0)
        first_ts = ts if first_ts is None else min(first_ts, ts)
        last_end = end if last_end is None else max(last_end, end)
        if previous_end is not None and ts - previous_end > _ACTIVITYWATCH_COVERAGE_GRACE_SECONDS:
            gaps.append({
                "start": _iso_local(previous_end),
                "end": _iso_local(ts),
                "seconds": round(ts - previous_end, 1),
            })
        previous_end = end if previous_end is None else max(previous_end, end)

    start_ts = requested_start.timestamp()
    end_ts = requested_end.timestamp()
    complete = bool(
        raw
        and first_ts is not None
        and last_end is not None
        and first_ts <= start_ts + _ACTIVITYWATCH_COVERAGE_GRACE_SECONDS
        and last_end >= end_ts - _ACTIVITYWATCH_COVERAGE_GRACE_SECONDS
        and not gaps
    )
    by_app = {
        str(item["app"]): round(float(item["duration_seconds"]), 1)
        for item in apps
        if item.get("app")
    }
    try:
        active_seconds = round(float(payload.get("active_seconds") or 0.0), 1)
    except (TypeError, ValueError):
        active_seconds = 0.0

    return {
        "source": "ActivityWatch",
        "source_version": version,
        "requested_minutes": minutes,
        "requested_start": requested_start.astimezone().isoformat(timespec="seconds"),
        "requested_end": requested_end.astimezone().isoformat(timespec="seconds"),
        "coverage": {
            "first_observation": _iso_local(first_ts) if first_ts is not None else None,
            "last_observation": _iso_local(last_end) if last_end is not None else None,
            "complete": complete,
            "gaps": gaps[:20],
        },
        "summary": {
            "active_seconds": active_seconds,
            "by_app_seconds": by_app,
        },
        "segments": active[-120:],
        "evidence_policy": (
            "ActivityWatch is the external local authority for retrospective desktop activity. "
            "XiaoYu queries its canonical window+AFK intersection and returns application names only; "
            "window titles/URLs are never returned to the model. Missing coverage is UNKNOWN, never proof "
            "of inactivity. A period with no active events may mean AFK, not that the owner did nothing."
        ),
    }


async def query_activitywatch_recent(minutes: int = 60, *, base_url: str = _ACTIVITYWATCH_BASE_URL) -> dict[str, Any]:
    try:
        lookback = int(minutes)
    except (TypeError, ValueError):
        lookback = 60
    lookback = min(1440, max(1, lookback))
    requested_end = datetime.now(timezone.utc)
    requested_start = requested_end - timedelta(minutes=lookback)

    try:
        async with httpx.AsyncClient(timeout=_ACTIVITYWATCH_TIMEOUT_SECONDS, trust_env=False) as client:
            info_response = await client.get(f"{base_url}/info")
            info_response.raise_for_status()
            info = info_response.json()
            buckets_response = await client.get(f"{base_url}/buckets/")
            buckets_response.raise_for_status()
            buckets = buckets_response.json()
            hostname = str(info.get("hostname") or "") if isinstance(info, dict) else ""
            window_bucket, afk_bucket = _select_activitywatch_buckets(buckets, hostname)
            if not window_bucket or not afk_bucket:
                raise RuntimeError("ActivityWatch window/AFK bucket pair unavailable")

            query = [
                f'raw = flood(query_bucket("{window_bucket}"));',
                "raw = sort_by_timestamp(raw);",
                "events = raw;",
                f'not_afk = flood(query_bucket("{afk_bucket}"));',
                'not_afk = filter_keyvals(not_afk, "status", ["not-afk"]);',
                "events = filter_period_intersect(events, not_afk);",
                "events = sort_by_timestamp(events);",
                'apps = merge_events_by_keys(events, ["app"]);',
                "apps = sort_by_duration(apps);",
                "active_seconds = sum_durations(events);",
                'RETURN = {"raw": raw, "events": events, "apps": apps, "active_seconds": active_seconds};',
            ]
            period = f"{requested_start.isoformat()}/{requested_end.isoformat()}"
            response = await client.post(
                f"{base_url}/query/",
                json={"timeperiods": [period], "query": query},
            )
            response.raise_for_status()
            values = response.json()
            result = values[0] if isinstance(values, list) and values else {}
            return _activitywatch_report_from_result(
                result,
                minutes=lookback,
                requested_start=requested_start,
                requested_end=requested_end,
                version=str(info.get("version") or "") if isinstance(info, dict) else None,
            )
    except Exception as exc:
        return {
            "source": "ActivityWatch",
            "requested_minutes": lookback,
            "requested_start": requested_start.astimezone().isoformat(timespec="seconds"),
            "requested_end": requested_end.astimezone().isoformat(timespec="seconds"),
            "coverage": {"first_observation": None, "last_observation": None, "complete": False, "gaps": []},
            "summary": {"active_seconds": 0.0, "by_app_seconds": {}},
            "segments": [],
            "unavailable": True,
            "error_type": type(exc).__name__,
            "evidence_policy": "ActivityWatch evidence is unavailable. Treat the requested period as UNKNOWN and do not infer inactivity.",
        }


@neko_plugin
class XiaoYuInteractionPolicyPlugin(NekoPluginBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.logger = self.enable_file_logging(log_level="INFO")
        self._lock = _CrossLoopAsyncLock()
        self._conversation_watcher = None

    @lifecycle(id="startup")
    async def startup(self, **_):
        await self._ensure_store_enabled()
        state = await self._load_state()
        # Persist the normalized schema on startup. Legacy JSON state is
        # imported once into N.E.K.O PluginStore, then the store is authoritative.
        await self._save_state(state)

        controller = await self.plugins.require_enabled(_CONTROLLER)
        if isinstance(controller, Err):
            return Err(SdkError("N.E.K.O proactive_controller is required"))

        if not state["initialized"]:
            state["initialized"] = True
            await self._save_state(state)

        await self._baseline_conversation_cursor()
        await self._start_conversation_watcher()
        # Cover the narrow gap between baseline read and subscription setup.
        # Dedupe keeps this safe if the same record also arrives live.
        await self._conversation_reconcile_fallback()
        await self._reconcile_state()
        return Ok({
            "status": "ready",
            "role": _ROLE,
            "text_control_authority": "N.E.K.O conversations_v2",
            "recent_activity_authority": "ActivityWatch",
        })

    @lifecycle(id="shutdown")
    async def shutdown(self, **_):
        watcher = self._conversation_watcher
        self._conversation_watcher = None
        if watcher is not None:
            try:
                await watcher.stop()
            except Exception as exc:
                self.logger.warning(
                    "conversation watcher shutdown failed err_type={}",
                    type(exc).__name__,
                )
        return Ok({"status": "shutdown"})

    @plugin_entry(
        id="get_state",
        name="XiaoYu interaction policy state",
        description="Read the private hard quiet/resume state without user message content.",
        metadata={"agent_hidden": True},
    )
    async def get_state(self, **_):
        return Ok(self._public_state(await self._load_state()))

    @plugin_entry(
        id="interruptibility_v1",
        name="Interruptibility capability v1",
        description=(
            "Internal shadow provider for proactive interruptibility. "
            "Returns privacy-bounded ActivityWatch evidence and currently abstains from control."
        ),
        metadata={"agent_hidden": True},
    )
    async def interruptibility_v1(
        self,
        activity_state: str = "",
        notification_state: int = -1,
        os_signals_available: bool = False,
        allow_focused_work: bool = False,
        native_block_reason: str = "",
        **_,
    ):
        report = await query_activitywatch_recent(2)
        coverage = report.get("coverage") if isinstance(report, dict) else {}
        summary = report.get("summary") if isinstance(report, dict) else {}
        if not isinstance(coverage, dict):
            coverage = {}
        if not isinstance(summary, dict):
            summary = {}
        try:
            active_seconds = max(0.0, float(summary.get("active_seconds") or 0.0))
        except (TypeError, ValueError):
            active_seconds = 0.0

        # v1 is intentionally evidence-only. It proves the replaceable
        # provider path without duplicating or weakening N.E.K.O's native
        # Windows/activity authority. A future provider may return allow/block
        # after its own product validation; this one always abstains.
        return Ok({
            "contract": "interruptibility.v1",
            "decision": "abstain",
            "reason": "activitywatch_shadow_evidence_only",
            "native": {
                "activity_state": str(activity_state or "")[:64],
                "notification_state": int(notification_state),
                "os_signals_available": bool(os_signals_available),
                "allow_focused_work": bool(allow_focused_work),
                "blocked": bool(native_block_reason),
            },
            "evidence": {
                "source": "ActivityWatch",
                "available": not bool(report.get("unavailable")) if isinstance(report, dict) else False,
                "coverage_complete": bool(coverage.get("complete")),
                "active_seconds": round(active_seconds, 3),
            },
        })

    @plugin_entry(
        id="recent_activity",
        name="Recent owner computer activity",
        description=(
            "Query the owner's ActivityWatch desktop activity for the last N minutes. "
            "Use this when the owner asks what they were doing, using, working on, or playing "
            "over a recent period. Missing coverage is UNKNOWN, never proof that the owner did nothing."
        ),
    )
    async def recent_activity(self, minutes: int = 60, **_):
        return Ok(await query_activitywatch_recent(minutes))

    @llm_tool(
        name="xiaoyu_recent_activity",
        description=(
            "Look up the owner's recent desktop activity from ActivityWatch when they ask what they were "
            "doing/using/working on/playing over the last minutes or hours. This is retrospective evidence, "
            "unlike the current-screen view. Always respect coverage.complete: missing coverage is unknown "
            "and must never be described as inactivity. Only application names/durations are returned; "
            "window titles, URLs and screenshots are not returned."
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
        return await query_activitywatch_recent(minutes)

    async def _apply_control_text(
        self,
        state: dict[str, Any],
        text: str,
        *,
        reason: str,
    ) -> tuple[dict[str, Any], int]:
        if not text:
            return state, 0

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
                        return state, 0
                    decision = await self._classify(text[:_MAX_TEXT_CHARS])
                    decision = gate_semantic_hard_control(text, decision)

        # v4 folds legacy audible-speech intent into the single reply-output
        # authority. "mute" means suppress the entire reply; "unmute" means
        # resume replies. No state may express "text on, audio off".
        speech_action = decision.get("speech_action")
        if speech_action == "mute":
            decision["action"] = "quiet"
        elif speech_action == "unmute":
            decision["action"] = "resume"

        decisions = 0
        action = decision["action"]
        if action == "quiet":
            state = await self._set_quiet(state, decision.get("duration_minutes"))
            decisions += 1
        elif action == "resume":
            state = await self._resume(state, reason=reason)
            decisions += 1

        vision_action = decision.get("vision_action")
        if vision_action == "block":
            state = await self._set_vision_blocked(state, True, reason=reason)
            decisions += 1
        elif vision_action == "allow":
            state = await self._allow_vision(state, reason=reason)
            decisions += 1
        elif vision_action == "restore":
            state = await self._restore_vision(state, reason=reason)
            decisions += 1

        return state, decisions

    @on_event(
        event_type="voice_transcript_observed",
        id="voice_control_intent",
        kind="consumer",
    )
    async def voice_control_intent(
        self,
        transcript: str = "",
        lanlan_name: str = "",
        **_,
    ):
        if str(lanlan_name or "") not in {"", _ROLE}:
            return Ok({"processed": False, "reason": "other_role"})
        text = str(transcript or "").strip()
        if not text:
            return Ok({"processed": False, "reason": "empty"})

        async with self._lock:
            state = await self._expire_if_needed(await self._load_state())
            state, decisions = await self._apply_control_text(state, text, reason="voice")
            await self._enforce_quiet_if_needed(state)
            return Ok({
                "processed": True,
                "decisions": decisions,
                **self._public_state(state),
            })

    async def _baseline_conversation_cursor(self) -> None:
        records = await self.bus.conversations_v2.get(
            character=_ROLE,
            role="user",
            input_source="text",
            max_count=20,
            order="desc",
            since_ts=None,
            timeout=3.0,
        )
        items = tuple(records)
        async with self._lock:
            state = await self._expire_if_needed(await self._load_state())
            if state["conversation_cursor_initialized"]:
                return
            ordered = sorted(
                items,
                key=lambda message: (
                    float(getattr(message, "observed_at", 0.0) or 0.0),
                    str(getattr(message, "id", "") or ""),
                ),
            )
            for message in ordered:
                event_id = str(getattr(message, "id", "") or "")
                if event_id:
                    state["seen_event_ids"].append(event_id)
            state["seen_event_ids"] = state["seen_event_ids"][-_SEEN_LIMIT:]
            if ordered:
                state["last_conversation_observed_at"] = max(
                    float(getattr(message, "observed_at", 0.0) or 0.0)
                    for message in ordered
                )
            state["conversation_cursor_initialized"] = True
            await self._save_state(state)
            self.logger.info(
                "conversation control cursor baselined records={}",
                len(ordered),
            )

    async def _start_conversation_watcher(self) -> bool:
        watcher = self._conversation_watcher
        if watcher is not None and bool(getattr(watcher, "_active", False)):
            return True
        try:
            watcher = self.bus.conversations_v2.watch(
                character=_ROLE,
                role="user",
                input_source="text",
            )
            watcher.subscribe(on="record")(self._conversation_control_record)
            await watcher.start()
            self._conversation_watcher = watcher
            self.logger.info(
                "conversation control watcher started source=conversations_v2 "
                "event=record role=user input_source=text"
            )
            return True
        except Exception as exc:
            self._conversation_watcher = None
            self.logger.warning(
                "conversation control watcher unavailable err_type={}",
                type(exc).__name__,
            )
            return False

    async def _conversation_control_record(self, message) -> None:
        async with self._lock:
            state = await self._expire_if_needed(await self._load_state())
            if not state["conversation_cursor_initialized"]:
                # Startup normally baselines before subscribing. Keep this
                # defensive branch fail-safe if a future host changes ordering.
                event_id = str(getattr(message, "id", "") or "")
                observed_at = float(getattr(message, "observed_at", 0.0) or 0.0)
                if event_id:
                    state["seen_event_ids"].append(event_id)
                    state["seen_event_ids"] = state["seen_event_ids"][-_SEEN_LIMIT:]
                state["last_conversation_observed_at"] = observed_at or None
                state["conversation_cursor_initialized"] = True
                await self._save_state(state)
                return

            decisions = await self._apply_conversation_messages(
                state,
                (message,),
                reason="text",
            )
            await self._enforce_quiet_if_needed(state)
            if decisions:
                self.logger.info(
                    "conversation control applied decisions={}",
                    decisions,
                )

    async def _apply_conversation_messages(
        self,
        state: dict[str, Any],
        messages,
        *,
        reason: str,
    ) -> int:
        seen = set(state["seen_event_ids"])
        watermark = float(state.get("last_conversation_observed_at") or 0.0)
        decisions = 0
        changed = False

        ordered = sorted(
            tuple(messages or ()),
            key=lambda message: (
                float(getattr(message, "observed_at", 0.0) or 0.0),
                str(getattr(message, "id", "") or ""),
            ),
        )
        for message in ordered:
            event_id = str(getattr(message, "id", "") or "")
            observed_at = float(getattr(message, "observed_at", 0.0) or 0.0)
            text = str(getattr(message, "text", "") or "").strip()
            if not event_id or event_id in seen:
                watermark = max(watermark, observed_at)
                continue

            state["seen_event_ids"].append(event_id)
            state["seen_event_ids"] = state["seen_event_ids"][-_SEEN_LIMIT:]
            seen.add(event_id)
            watermark = max(watermark, observed_at)
            changed = True

            if not text:
                continue
            state, added = await self._apply_control_text(
                state,
                text,
                reason=reason,
            )
            decisions += added

        if changed:
            state["last_conversation_observed_at"] = watermark
            await self._save_state(state)
        return decisions

    async def _conversation_reconcile_fallback(self) -> int:
        snapshot = await self._load_state()
        since_ts = snapshot.get("last_conversation_observed_at")
        records = await self.bus.conversations_v2.get(
            character=_ROLE,
            role="user",
            input_source="text",
            max_count=20,
            order="asc",
            since_ts=float(since_ts) if isinstance(since_ts, (int, float)) else None,
            timeout=3.0,
        )
        items = tuple(records)

        async with self._lock:
            state = await self._expire_if_needed(await self._load_state())
            if not state["conversation_cursor_initialized"]:
                ordered = sorted(
                    items,
                    key=lambda message: (
                        float(getattr(message, "observed_at", 0.0) or 0.0),
                        str(getattr(message, "id", "") or ""),
                    ),
                )
                for message in ordered:
                    event_id = str(getattr(message, "id", "") or "")
                    if event_id:
                        state["seen_event_ids"].append(event_id)
                state["seen_event_ids"] = state["seen_event_ids"][-_SEEN_LIMIT:]
                if ordered:
                    state["last_conversation_observed_at"] = max(
                        float(getattr(message, "observed_at", 0.0) or 0.0)
                        for message in ordered
                    )
                state["conversation_cursor_initialized"] = True
                await self._save_state(state)
                await self._enforce_quiet_if_needed(state)
                return 0

            decisions = await self._apply_conversation_messages(
                state,
                items,
                reason="text-reconcile",
            )
            await self._enforce_quiet_if_needed(state)
            return decisions

    @timer_interval(id="reconcile_interaction_state", seconds=30, auto_start=True)
    async def reconcile_interaction_state(self, **_):
        if self._lock.locked():
            return Ok({"busy": True})

        watcher = self._conversation_watcher
        active = watcher is not None and bool(getattr(watcher, "_active", False))
        if not active:
            # Retry the native subscription first. Only fall back to one
            # bounded incremental read if the watcher cannot be restored.
            if await self._start_conversation_watcher():
                await self._conversation_reconcile_fallback()
                await self._reconcile_state()
                return Ok({
                    "watcher": "restarted",
                    **self._public_state(await self._load_state()),
                })
            decisions = await self._conversation_reconcile_fallback()
            return Ok({
                "watcher": "fallback",
                "decisions": decisions,
                **self._public_state(await self._load_state()),
            })

        await self._reconcile_state()
        return Ok({"watcher": "active", **self._public_state(await self._load_state())})

    async def _classify(self, text: str) -> dict[str, Any]:
        """Classify through N.E.K.O's host-managed Plugin SDK model gateway.

        The manifest declares a stable interaction_classifier usage. The host
        owns its provider credentials and model-slot binding; XiaoYu never reads
        either directly. The private installer migrates only the first automatic
        binding to the native agent_small tier and then leaves user changes alone.
        """
        try:
            client = await self.ctx.models.get_client()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=_CLASSIFIER_MODEL_USAGE,
                    messages=[
                        {"role": "system", "content": _CLASSIFIER_SYSTEM},
                        {"role": "user", "content": text},
                    ],
                    temperature=0.0,
                    max_tokens=96,
                ),
                timeout=_CLASSIFIER_TIMEOUT_SECONDS,
            )
            choices = getattr(response, "choices", None)
            message = getattr(choices[0], "message", None) if choices else None
            raw = getattr(message, "content", "") or ""
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
        state["speech_muted"] = False
        state["quiet_until"] = now + duration_minutes * 60 if duration_minutes is not None else None
        state["changed_at"] = now
        state["last_action"] = "quiet"
        await self._save_state(state)
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
        state["speech_muted"] = False
        state["previous_proactive_chat_enabled"] = None
        state["quiet_until"] = None
        state["changed_at"] = now
        state["last_action"] = f"resume:{reason}"
        await self._save_state(state)
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
        await self._save_state(state)
        self.logger.info("native autonomous vision blocked reason={}", reason)
        return state

    async def _allow_vision(self, state: dict[str, Any], *, reason: str) -> dict[str, Any]:
        await self._write_native_vision_enabled(True)
        state["vision_blocked"] = False
        state["previous_vision_enabled"] = None
        state["changed_at"] = time.time()
        state["last_action"] = f"vision_allow:{reason}"
        await self._save_state(state)
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
        await self._save_state(state)
        self.logger.info("native autonomous vision restored reason={}", reason)
        return state

    async def _expire_if_needed(self, state: dict[str, Any]) -> dict[str, Any]:
        until = state.get("quiet_until")
        if state["quiet"] and isinstance(until, (int, float)) and time.time() >= float(until):
            state = await self._resume(state, reason="expired")
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
            state = await self._expire_if_needed(await self._load_state())
            await self._enforce_quiet_if_needed(state)

    async def _ensure_store_enabled(self) -> None:
        """Require N.E.K.O's native PluginStore for durable policy state."""
        if self.store.enabled:
            return
        # Older XiaoYu runtime configs preserve the original manifest default
        # [plugin.store] enabled=false. Move that one required capability onto
        # the host-managed store through the public PluginConfig API.
        await self.config.set("plugin.store.enabled", True, timeout=10.0)
        self.store.enabled = True

    async def _load_state(self) -> dict[str, Any]:
        result = await self.store.get(_STATE_STORE_KEY, None)
        if isinstance(result, Err):
            raise RuntimeError("N.E.K.O PluginStore state read failed") from result.error
        raw = result.value
        if isinstance(raw, dict):
            return _normalize_state(raw)

        # One-time compatibility import. Upgrades preserve the plugin data
        # directory, so the pre-0.6.7 JSON remains available exactly once.
        legacy_path = self.data_path("state.json")
        legacy_raw: dict[str, Any] | None = None
        try:
            candidate = json.loads(legacy_path.read_text(encoding="utf-8-sig"))
            if isinstance(candidate, dict):
                legacy_raw = candidate
        except (OSError, ValueError, TypeError):
            pass

        state = _normalize_state(legacy_raw or {})
        saved = await self.store.set(_STATE_STORE_KEY, state)
        if isinstance(saved, Err):
            raise RuntimeError("N.E.K.O PluginStore legacy-state import failed") from saved.error
        self._sync_reply_gate_projection(state)
        if legacy_raw is not None:
            self.logger.info(
                "migrated legacy interaction state into N.E.K.O PluginStore; "
                "state.json retained only as quiet gate projection"
            )
        return state

    def _sync_reply_gate_projection(self, state: dict[str, Any]) -> None:
        """Publish only the derived quiet bit for N.E.K.O's synchronous output gate.

        PluginStore is the durable authority. The small JSON file remains solely
        because the main chat process must make the final reply-admission decision
        synchronously and patch 0006 intentionally has no private DB/Plugin SDK
        dependency. It can always be rebuilt from PluginStore on plugin startup.
        """
        path = self.data_path("state.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "projection": "xiaoyu_reply_gate.v1",
            "quiet": bool(state.get("quiet")),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    async def _save_state(self, state: dict[str, Any]) -> None:
        normalized = _normalize_state(state)
        result = await self.store.set(_STATE_STORE_KEY, normalized)
        if isinstance(result, Err):
            raise RuntimeError("N.E.K.O PluginStore state write failed") from result.error
        self._sync_reply_gate_projection(normalized)

    @staticmethod
    def _public_state(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "quiet": bool(state.get("quiet")),
            "speech_muted": bool(state.get("speech_muted")),
            "vision_blocked": bool(state.get("vision_blocked")),
            "quiet_until": state.get("quiet_until"),
            "last_action": state.get("last_action"),
            "conversation_cursor_initialized": bool(
                state.get("conversation_cursor_initialized")
            ),
            "last_conversation_observed_at": state.get(
                "last_conversation_observed_at"
            ),
            "seen_event_count": len(state.get("seen_event_ids") or []),
        }
