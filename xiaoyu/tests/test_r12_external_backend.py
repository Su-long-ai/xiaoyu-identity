from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import model_adapter

from xiaoyu.contracts import ProviderHealth
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import LiteLLMCompletionBackend, RuntimeHost


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def ready_health():
    return ProviderHealth(
        liveness="UP",
        readiness="READY",
        capability_health={"chat.completion": "READY"},
        reason=None,
        since=NOW,
        retry_after_ms=None,
        details={},
    )


def config(provider: str, *, fallbacks=()):
    spec = model_adapter.PROVIDERS[provider]
    result = {
        "provider": provider,
        "url": spec["url"],
        "model": spec["model"],
        "key_env": spec.get("key_env", ""),
        "fallbacks": list(fallbacks),
    }
    for key in (
        "key_file",
        "enable_thinking",
        "reasoning_effort",
        "data_boundary",
    ):
        if key in spec:
            result[key] = spec[key]
    return result


class R12ExternalBackendTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _register(self, host, cfg):
        host.register_provider(
            model_adapter.capability_descriptor_for_config(cfg),
            ready_health(),
        )

    def test_litellm_backend_executes_one_attempt_without_internal_fallback(self):
        observed = []
        dispatched = []

        def fake_completion(**kwargs):
            observed.append(kwargs)
            self.assertEqual(dispatched, ["before-call"])
            return {
                "choices": [
                    {"message": {"content": "ok"}}
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                },
            }

        backend = LiteLLMCompletionBackend(fake_completion)
        answer, usage = backend.complete(
            {
                "provider": "qwen",
                "url": (
                    "https://dashscope.aliyuncs.com/"
                    "compatible-mode/v1/chat/completions"
                ),
                "model": "qwen3.8-flash",
                "enable_thinking": False,
            },
            [{"role": "user", "content": "hello"}],
            128,
            30,
            lambda: dispatched.append("before-call"),
            api_key="synthetic-key",
        )

        self.assertEqual(answer, "ok")
        self.assertEqual(usage["prompt_tokens"], 3)
        self.assertEqual(len(observed), 1)
        request = observed[0]
        self.assertEqual(request["max_retries"], 0)
        self.assertNotIn("fallbacks", request)
        self.assertNotIn("default_fallbacks", request)
        self.assertEqual(
            request["api_base"],
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertEqual(request["model"], "openai/qwen3.8-flash")
        self.assertEqual(
            request["extra_body"],
            {"enable_thinking": False},
        )

    def test_litellm_backend_wraps_external_exception_for_xiaoyu_fallback(self):
        class ProviderFailure(Exception):
            pass

        def failing(**kwargs):
            raise ProviderFailure("synthetic")

        backend = LiteLLMCompletionBackend(failing)
        with self.assertRaisesRegex(
            RuntimeError,
            "LiteLLM provider call failed: ProviderFailure",
        ):
            backend.complete(
                {
                    "provider": "openai",
                    "url": (
                        "https://api.openai.com/v1/chat/completions"
                    ),
                    "model": "gpt-test",
                },
                [{"role": "user", "content": "hello"}],
                32,
                10,
                api_key="synthetic",
            )

    def test_xiaoyu_not_litellm_owns_cross_provider_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            primary = config("deepseek", fallbacks=("qwen",))
            fallback = config("qwen")
            self._register(host, primary)
            self._register(host, fallback)

            attempts = []

            class Backend:
                def complete(
                    self,
                    cfg,
                    messages,
                    max_tokens,
                    timeout,
                    on_dispatched,
                    *,
                    api_key="",
                ):
                    attempts.append(cfg["provider"])
                    if cfg["provider"] == "deepseek":
                        raise RuntimeError("primary unavailable")
                    return "qwen-ok", {"backend": "external"}

            answer, usage = model_adapter.chat(
                primary,
                [{"role": "user", "content": "hello"}],
                runtime_host=host,
                required_data_class="PUBLIC",
                transport_backend=Backend(),
            )

            self.assertEqual(answer, "qwen-ok")
            self.assertEqual(usage["backend"], "external")
            self.assertEqual(attempts, ["deepseek", "qwen"])

    def test_runtime_host_rejects_provider_before_external_backend_is_called(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            host = RuntimeHost(db)
            primary = config("deepseek")
            # Deliberately do not register the provider in RuntimeHost.
            calls = []

            class Backend:
                def complete(self, *args, **kwargs):
                    calls.append("called")
                    return "should-not-run", {}

            with self.assertRaisesRegex(
                RuntimeError,
                "runtime host rejected provider",
            ):
                model_adapter.chat(
                    primary,
                    [{"role": "user", "content": "hello"}],
                    runtime_host=host,
                    required_data_class="PUBLIC",
                    transport_backend=Backend(),
                )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
