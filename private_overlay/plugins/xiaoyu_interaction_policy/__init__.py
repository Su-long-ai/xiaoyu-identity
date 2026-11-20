from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
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
    timer_interval,
)

_ROLE = "XiaoYu"
_CONTROLLER = "proactive_controller"
_STATE_VERSION = 1
_SEEN_LIMIT = 128
_CLASSIFIER_TIMEOUT_SECONDS = 8.0
_MAX_TEXT_CHARS = 500

_CANDIDATE_RE = re.compile(
    r"(安静|静一静|别.{0,8}(说|讲|聊|烦|扰|找|联系|主动|消息|出声)|"
    r"不要.{0,8}(说|讲|聊|烦|扰|找|联系|主动|消息|出声)|"
    r"闭嘴|打扰|主动找|主动联系|恢复|解除|继续.{0,6}(说|聊|找|联系)|"
    r"可以.{0,6}(说|聊|找|联系)|"
    r"quiet|silence|silent|shut\s*up|do\s*not\s*disturb|don't\s*bother|"
    r"stop\s+(talking|messaging|contacting)|resume|speak\s+again|talk\s+again)",
    re.IGNORECASE,
)

_CLASSIFIER_SYSTEM = """You are a conservative interaction-policy classifier.
Decide whether the user's CURRENT message explicitly controls whether the assistant may initiate unsolicited/proactive communication.

Return JSON only:
{"action":"quiet"|"resume"|"none","duration_minutes":null|integer}

Definitions:
- quiet: the user explicitly asks the assistant to be quiet, stop talking, stop bothering/contacting/messaging them proactively, or temporarily stop initiating communication.
- resume: the user explicitly allows the assistant to resume speaking/initiating/contacting after a quiet period.
- none: everything else.

Important distinctions:
- "别说话哦", "你先安静一会", "别主动找我", "先别烦我", "stay quiet", "don't bother me" => quiet.
- "可以说话了", "继续吧，你可以主动找我了", "resume talking" => resume.
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
    previous = state.get("previous_proactive_chat_enabled")
    state["previous_proactive_chat_enabled"] = previous if isinstance(previous, bool) else None
    until = state.get("quiet_until")
    state["quiet_until"] = float(until) if isinstance(until, (int, float)) and not isinstance(until, bool) else None
    return state


def parse_classifier_output(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        return {"action": "none", "duration_minutes": None}
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
            return {"action": "none", "duration_minutes": None}
        try:
            value = json.loads(match.group(0))
        except Exception:
            return {"action": "none", "duration_minutes": None}
    if not isinstance(value, dict):
        return {"action": "none", "duration_minutes": None}
    action = str(value.get("action") or "none").strip().lower()
    if action not in {"quiet", "resume", "none"}:
        action = "none"
    duration = value.get("duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int) or not (1 <= duration <= 1440):
        duration = None
    if action != "quiet":
        duration = None
    return {"action": action, "duration_minutes": duration}


def candidate_needs_semantic_check(text: str) -> bool:
    return bool(isinstance(text, str) and _CANDIDATE_RE.search(text[:_MAX_TEXT_CHARS]))


def should_run_semantic_check(text: str, *, quiet: bool) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(quiet or candidate_needs_semantic_check(text))


def _extract_event(record: Any) -> dict[str, Any]:
    if hasattr(record, "dump") and callable(record.dump):
        try:
            raw = record.dump()
        except Exception:
            raw = {}
    else:
        raw = record
    return dict(raw) if isinstance(raw, dict) else {}


@neko_plugin
class XiaoYuInteractionPolicyPlugin(NekoPluginBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.logger = self.enable_file_logging(log_level="INFO")
        self._lock = asyncio.Lock()
        self._state_path: Path | None = None

    @lifecycle(id="startup")
    async def startup(self, **_):
        self._state_path = self.data_path("state.json")
        state = self._load_state()

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
    def shutdown(self, **_):
        return Ok({"status": "shutdown"})

    @plugin_entry(
        id="get_state",
        name="XiaoYu interaction policy state",
        description="Read the private hard quiet/resume state without user message content.",
        metadata={"agent_hidden": True},
    )
    async def get_state(self, **_):
        return Ok(self._public_state(self._load_state()))

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
                if not should_run_semantic_check(text, quiet=bool(state["quiet"])):
                    continue

                decision = await self._classify(text[:_MAX_TEXT_CHARS])
                action = decision["action"]
                if action == "quiet":
                    state = await self._set_quiet(state, decision.get("duration_minutes"))
                    decisions += 1
                elif action == "resume":
                    state = await self._resume(state, reason="user")
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
                return {"action": "none", "duration_minutes": None}
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
            return {"action": "none", "duration_minutes": None}

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

    async def _expire_if_needed(self, state: dict[str, Any]) -> dict[str, Any]:
        until = state.get("quiet_until")
        if state["quiet"] and isinstance(until, (int, float)) and time.time() >= float(until):
            return await self._resume(state, reason="expired")
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
            "quiet_until": state.get("quiet_until"),
            "last_action": state.get("last_action"),
            "seen_event_count": len(state.get("seen_event_ids") or []),
        }
