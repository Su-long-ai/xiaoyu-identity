# -*- coding: utf-8 -*-
"""Local OpenAI-compatible proxy backed by XiaoYu's capped DeepSeek gateway.

External benchmark/framework code points at loopback and receives no real
provider credential. Paid calls remain governed by research_api.py.

Cost controls:
- every external client must use Authorization: Bearer local-budget-proxy:<tag>;
- tags become durable budget scopes for rolling circuit breakers;
- smoke-phase completion size is capped by policy;
- streaming/tools remain disabled.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from research_api import ResearchApiBudget, ResearchBudgetError, _PROXY_AUTH_SENTINEL


_TAG_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_RUN_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def research_purpose_from_headers(headers, *, require_tag: bool = False) -> tuple[str, str]:
    """Return (purpose, budget_scope) from the local non-secret proxy key."""
    auth = str(headers.get("Authorization") or "")
    prefix = "Bearer local-budget-proxy:"
    if auth.startswith(prefix):
        tag = auth[len(prefix):].strip()
        if _TAG_RE.fullmatch(tag):
            base = f"proxy:{tag}"
            run = str(headers.get("X-XiaoYu-Research-Run") or "").strip()
            if run:
                if not _RUN_RE.fullmatch(run):
                    raise ResearchBudgetError(
                        "Invalid X-XiaoYu-Research-Run; use 1-64 letters, digits, dot, underscore or hyphen")
                scope=f"{base}:{run}"
                return scope, scope
            return base, base
        raise ResearchBudgetError(
            "Invalid local proxy tag; use 1-64 letters, digits, dot, underscore or hyphen"
        )
    if require_tag:
        raise ResearchBudgetError(
            "Tagged local proxy key required: Authorization: Bearer local-budget-proxy:<tag>"
        )
    return "OpenAI-compatible benchmark proxy", "proxy:legacy-untagged"


def enforce_allowed_proxy_scope(scope: str, guard: dict) -> None:
    allowed = guard.get("allowed_proxy_tags") or []
    if not allowed:
        return
    tail = scope.split(":", 1)[1] if scope.startswith("proxy:") else ""
    tag = tail.split(":",1)[0]
    if tag not in {str(x) for x in allowed}:
        raise ResearchBudgetError(
            f"Proxy tag '{tag}' is not registered in paid-research policy"
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "XiaoYuResearchProxy/1.1"

    def log_message(self, fmt, *args):
        # Do not log request bodies or authorization headers.
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") not in ("", "/health", "/v1/health"):
            self._json(404, {"error": {"message": "not found", "type": "not_found_error"}})
            return
        b = ResearchApiBudget()
        try:
            self._json(200, {"ok": True, "budget": b.status()})
        finally:
            b.close()

    def do_POST(self):
        if self.path.rstrip("/") not in ("/chat/completions", "/v1/chat/completions"):
            self._json(404, {"error": {"message": "not found", "type": "not_found_error"}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 2_000_000:
            self._json(
                400,
                {"error": {"message": "invalid request size", "type": "invalid_request_error"}},
            )
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(
                400,
                {"error": {"message": "invalid JSON", "type": "invalid_request_error"}},
            )
            return
        if body.get("stream"):
            self._json(
                400,
                {
                    "error": {
                        "message": "streaming disabled by research proxy",
                        "type": "invalid_request_error",
                    }
                },
            )
            return
        if body.get("tools") or body.get("functions"):
            self._json(
                400,
                {
                    "error": {
                        "message": "tools disabled by research proxy",
                        "type": "invalid_request_error",
                    }
                },
            )
            return
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self._json(
                400,
                {
                    "error": {
                        "message": "messages must be a non-empty list",
                        "type": "invalid_request_error",
                    }
                },
            )
            return
        try:
            max_tokens = int(
                body.get("max_tokens") or body.get("max_completion_tokens") or 1024
            )
        except (TypeError, ValueError):
            self._json(
                400,
                {"error": {"message": "invalid max_tokens", "type": "invalid_request_error"}},
            )
            return
        if not 1 <= max_tokens <= 32768:
            self._json(
                400,
                {
                    "error": {
                        "message": "max_tokens outside research proxy range",
                        "type": "invalid_request_error",
                    }
                },
            )
            return
        response_format = body.get("response_format")
        if response_format is not None and response_format != {"type": "json_object"}:
            self._json(
                400,
                {
                    "error": {
                        "message": "only response_format json_object is supported",
                        "type": "invalid_request_error",
                    }
                },
            )
            return
        model = str(body.get("model") or "")
        budget = ResearchApiBudget()
        try:
            cfg = budget._cfg()
            guard = budget._guard_cfg()
            require_tag = bool(guard.get("require_proxy_tag", False))
            purpose, scope = research_purpose_from_headers(
                self.headers, require_tag=require_tag
            )
            enforce_allowed_proxy_scope(scope, guard)
            if cfg.get("active_phase") == "smoke":
                completion_cap = int(
                    guard.get("max_proxy_completion_tokens_smoke") or 0
                )
                if completion_cap > 0 and max_tokens > completion_cap:
                    raise ResearchBudgetError(
                        f"Proxy smoke max_tokens {max_tokens} exceeds cap {completion_cap}"
                    )

            provider_model = __import__("model_adapter").load_provider(budget.root)["model"]
            if model and model != provider_model:
                self._json(
                    400,
                    {
                        "error": {
                            "message": "model must match frozen research provider",
                            "type": "invalid_request_error",
                        }
                    },
                )
                return
            content, usage, call_id = budget.chat(
                messages,
                max_tokens=max_tokens,
                purpose=purpose,
                budget_scope=scope,
                response_format=response_format,
                _proxy_auth=_PROXY_AUTH_SENTINEL,
            )
            created = int(time.time())
            self._json(
                200,
                {
                    "id": call_id,
                    "object": "chat.completion",
                    "created": created,
                    "model": provider_model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": usage,
                },
            )
        except ResearchBudgetError as exc:
            self._json(
                429,
                {"error": {"message": str(exc), "type": "budget_error"}},
            )
        except Exception as exc:
            self._json(
                502,
                {
                    "error": {
                        "message": f"provider call failed: {type(exc).__name__}",
                        "type": "provider_error",
                    }
                },
            )
        finally:
            budget.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18081)
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Research proxy may bind only to loopback")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        json.dumps(
            {"ready": True, "base_url": f"http://{args.host}:{args.port}/v1"},
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
