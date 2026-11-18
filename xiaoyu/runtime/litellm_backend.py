from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import urlsplit, urlunsplit


class LiteLLMBackendUnavailable(RuntimeError):
    pass


def _api_base_from_chat_url(url: str) -> str:
    parsed = urlsplit(str(url))
    path = parsed.path.rstrip("/")
    suffix = "/chat/completions"
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path.rstrip("/"), "", "")
    )


def _litellm_model(config: dict) -> str:
    explicit = str(config.get("litellm_model") or "").strip()
    if explicit:
        return explicit
    provider = str(config.get("provider") or "").lower()
    model = str(config.get("model") or "").strip()
    if provider == "openai":
        return "openai/" + model
    if provider == "deepseek":
        return "deepseek/" + model
    if provider == "ollama":
        return "ollama_chat/" + model
    # Qwen/custom/deepseek_web are OpenAI-compatible endpoints here.
    return "openai/" + model


def _usage_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    try:
        return dict(value)
    except Exception:
        return {}


def _response_parts(response: Any) -> tuple[str, dict]:
    if isinstance(response, dict):
        choices = response.get("choices") or []
        usage = _usage_dict(response.get("usage"))
        if not choices:
            raise RuntimeError("LiteLLM returned no choices")
        message = choices[0].get("message") or {}
        content = str(message.get("content") or "").strip()
    else:
        choices = getattr(response, "choices", None) or []
        usage = _usage_dict(getattr(response, "usage", None))
        if not choices:
            raise RuntimeError("LiteLLM returned no choices")
        message = getattr(choices[0], "message", None)
        content = str(getattr(message, "content", "") or "").strip()
    if not content:
        raise RuntimeError("LiteLLM returned an empty response")
    return content, usage


class LiteLLMCompletionBackend:
    """Optional external provider compatibility layer.

    Cross-provider routing deliberately stays outside LiteLLM. XiaoYu performs
    privacy/freshness/runtime admission for every attempt and calls this backend
    only after a concrete provider has been selected.
    """

    def __init__(
        self,
        completion_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        if completion_fn is None:
            try:
                import litellm  # type: ignore
            except ImportError as exc:
                raise LiteLLMBackendUnavailable(
                    "LiteLLM is not installed; install it only when this "
                    "optional backend is selected"
                ) from exc
            completion_fn = litellm.completion
        self._completion = completion_fn

    def complete(
        self,
        config: dict,
        messages: list[dict],
        max_tokens: int,
        timeout: float,
        on_dispatched=None,
        *,
        api_key: str = "",
    ) -> tuple[str, dict]:
        kwargs = {
            "model": _litellm_model(config),
            "messages": messages,
            "max_tokens": int(max_tokens),
            "timeout": timeout,
            "stream": False,
            # Critical: fallback/retry authority belongs to XiaoYu RuntimeHost.
            "max_retries": 0,
        }
        provider = str(config.get("provider") or "").lower()
        if provider != "openai" or str(config.get("url") or ""):
            api_base = _api_base_from_chat_url(
                str(config.get("url") or "")
            )
            if api_base:
                kwargs["api_base"] = api_base
        if api_key:
            kwargs["api_key"] = api_key

        if config.get("temperature") is not None:
            kwargs["temperature"] = float(config["temperature"])
        if config.get("top_p") is not None:
            kwargs["top_p"] = float(config["top_p"])
        response_format = config.get("response_format")
        if response_format is not None:
            kwargs["response_format"] = response_format
        effort = str(config.get("reasoning_effort") or "").strip().lower()
        if effort:
            kwargs["reasoning_effort"] = effort

        extra_body = {}
        if isinstance(config.get("enable_thinking"), bool):
            extra_body["enable_thinking"] = config["enable_thinking"]
        thinking = str(config.get("thinking") or "").strip().lower()
        if thinking in {"enabled", "disabled"}:
            extra_body["thinking"] = {"type": thinking}
        if extra_body:
            kwargs["extra_body"] = extra_body

        # LiteLLM does not expose XiaoYu's exact socket-output hook. Calling the
        # disclosure callback immediately before library invocation is
        # conservative: it may mark a call dispatched slightly early, never late.
        if on_dispatched is not None:
            on_dispatched()
        try:
            response = self._completion(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                "LiteLLM provider call failed: %s" % type(exc).__name__
            ) from exc
        return _response_parts(response)
