# -*- coding: utf-8 -*-
"""Replaceable chat-completion adapter. Provider settings stay OUTSIDE identity archives."""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

PROVIDERS = {
    "deepseek": {"url":"https://api.deepseek.com/chat/completions",
                 "model":"deepseek-flash","key_env":"DEEPSEEK_API_KEY"},
    "openai": {"url":"https://api.openai.com/v1/chat/completions",
               "model":"gpt-4.1-mini","key_env":"OPENAI_API_KEY"},
    "ollama": {"url":"http://127.0.0.1:11434/v1/chat/completions",
               "model":"qwen3:8b","key_env":""},
    "custom": {"url":"https://example.invalid/v1/chat/completions",
               "model":"","key_env":"FISH_CUSTOM_API_KEY"}
}

class ProviderConfigError(RuntimeError): pass

def load_provider(home):
    path=Path(home)/"provider.json"
    raw=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(raw,dict):
        raise ProviderConfigError("Invalid provider config")
    provider=str(raw.get("provider","deepseek")).lower()
    if provider not in PROVIDERS:
        raise ProviderConfigError("Unsupported provider: "+provider)
    base=PROVIDERS[provider]
    config={"provider":provider,
            "url":str(raw.get("url") or base["url"]).strip(),
            "model":str(raw.get("model") or base["model"]).strip(),
            "key_env":str(raw.get("key_env") if "key_env" in raw else base["key_env"]).strip()}
    return config

def save_provider(home, provider, model="", url="", key_env=""):
    if provider not in PROVIDERS:
        raise ProviderConfigError("Unknown provider")
    spec=PROVIDERS[provider]
    config={"provider":provider,
            "model":(model or spec["model"]).strip(),
            "url":(url or spec["url"]).strip(),
            "key_env":key_env.strip() if provider=="custom" else spec["key_env"]}
    validate(config)
    home=Path(home)
    path=home/"provider.json"
    temp=path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(path)
    return config

def validate(config):
    provider=config["provider"]
    url=config["url"]
    parsed=urlsplit(url)
    if not config["model"] or not url:
        raise ProviderConfigError("Model and URL required")
    if parsed.username or parsed.password or parsed.fragment:
        raise ProviderConfigError("Credentials and fragments not allowed in endpoint URL")
    if parsed.scheme=="https" and parsed.hostname:
        pass
    elif (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1")
          and provider in ("ollama","custom")):
        pass
    else:
        raise ProviderConfigError("Only HTTPS or local HTTP endpoints allowed")
    if parsed.path.rstrip("/") not in ("/chat/completions","/v1/chat/completions"):
        raise ProviderConfigError("Only chat/completions-compatible endpoints supported")
    if provider in ("deepseek","openai") and url!=PROVIDERS[provider]["url"]:
        raise ProviderConfigError("Use custom provider for nonstandard endpoints")
    if len(config.get("key_env",""))>70:
        raise ProviderConfigError("Invalid key env var")

def chat(config, messages, max_tokens=500, timeout=75):
    """OpenAI-compatible messages; no key ever persisted to the companion archive."""
    validate(config)
    envvar=config.get("key_env","")
    key=os.getenv(envvar,"").strip() if envvar else ""
    if envvar and not key:
        raise ProviderConfigError(f"请先在系统环境变量中配置 {envvar}，不要把密钥输入聊天记录。")
    body={"model":config["model"], "messages":messages,
          "max_tokens":max_tokens, "stream":False}
    thinking=str(config.get("thinking") or "").strip().lower()
    if thinking in ("enabled","disabled"):
        body["thinking"]={"type":thinking}
    effort=str(config.get("reasoning_effort") or "").strip().lower()
    if effort in ("none","low","high","max"):
        body["reasoning_effort"]=effort
    if config.get("temperature") is not None:
        body["temperature"]=float(config["temperature"])
    if config.get("top_p") is not None:
        body["top_p"]=float(config["top_p"])
    response_format=config.get("response_format")
    if response_format is not None:
        if response_format != {"type":"json_object"}:
            raise ProviderConfigError("Unsupported response_format")
        body["response_format"]={"type":"json_object"}
    payload=json.dumps(body,ensure_ascii=False).encode("utf-8")
    headers={"Content-Type":"application/json"}
    if key:
        headers["Authorization"]="Bearer "+key
    req=urllib.request.Request(config["url"],data=payload,headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            result=json.loads(resp.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Never surface provider response body; it might echo sensitive data.
        if e.code==402:
            raise RuntimeError(f"{config['provider']} API 返回 402：账户余额或计费不可用。") from None
        raise RuntimeError(f"{config['provider']} API 返回 HTTP {e.code}。") from None
    except urllib.error.URLError:
        raise RuntimeError(f"无法连接 {config['provider']} 模型服务。") from None
    except TimeoutError:
        raise RuntimeError("模型调用超时。") from None
    choices=result.get("choices") or []
    if not choices: raise RuntimeError("模型服务没有返回有效回答。")
    msg=choices[0].get("message") or {}
    response=str(msg.get("content") or "").strip()
    if not response:
        raise RuntimeError("模型返回空回复。")
    return response,result.get("usage") or {}
