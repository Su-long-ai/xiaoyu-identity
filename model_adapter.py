# -*- coding: utf-8 -*-
"""Replaceable chat-completion adapter. Provider settings stay OUTSIDE identity archives."""
from __future__ import annotations
import http.client
import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

PROVIDERS = {
    "deepseek_web": {
        "url":"http://127.0.0.1:8787/v1/chat/completions",
        "model":"deepseek-v4-flash",
        "key_env":"",
        "key_file":r"D:\cpod\deepseek-web-api\data\.api-key",
        "reasoning_effort":"none",
        "fallbacks":["qwen","deepseek"],
    },
    "deepseek": {"url":"https://api.deepseek.com/chat/completions",
                 "model":"deepseek-flash","key_env":"DEEPSEEK_API_KEY",
                 "reasoning_effort":"none"},
    "openai": {"url":"https://api.openai.com/v1/chat/completions",
               "model":"gpt-4.1-mini","key_env":"OPENAI_API_KEY"},
    "qwen": {"url":"https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
             "model":"qwen3.8-flash","key_env":"DASHSCOPE_API_KEY",
             "enable_thinking":False},
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
    key_file=raw.get("key_file") if "key_file" in raw else base.get("key_file","")
    if key_file:
        config["key_file"]=str(key_file).strip()
    if "enable_thinking" in base or "enable_thinking" in raw:
        config["enable_thinking"]=bool(raw.get("enable_thinking",base.get("enable_thinking",False)))
    if "reasoning_effort" in base or "reasoning_effort" in raw:
        config["reasoning_effort"]=str(raw.get("reasoning_effort",base.get("reasoning_effort",""))).strip().lower()
    fallbacks=raw.get("fallbacks",base.get("fallbacks",[]))
    if isinstance(fallbacks,list):
        config["fallbacks"]=[str(x).strip().lower() for x in fallbacks
                             if str(x).strip().lower() in PROVIDERS and str(x).strip().lower()!=provider]
    return config

def save_provider(home, provider, model="", url="", key_env=""):
    if provider not in PROVIDERS:
        raise ProviderConfigError("Unknown provider")
    spec=PROVIDERS[provider]
    config={"provider":provider,
            "model":(model or spec["model"]).strip(),
            "url":(url or spec["url"]).strip(),
            "key_env":key_env.strip() if provider=="custom" else spec["key_env"]}
    if spec.get("key_file"):
        config["key_file"]=spec["key_file"]
    if "enable_thinking" in spec:
        config["enable_thinking"]=bool(spec["enable_thinking"])
    if "reasoning_effort" in spec:
        config["reasoning_effort"]=spec["reasoning_effort"]
    if spec.get("fallbacks"):
        config["fallbacks"]=list(spec["fallbacks"])
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
          and provider in ("ollama","custom","deepseek_web")):
        pass
    else:
        raise ProviderConfigError("Only HTTPS or local HTTP endpoints allowed")
    if parsed.path.rstrip("/") not in (
        "/chat/completions",
        "/v1/chat/completions",
        "/compatible-mode/v1/chat/completions",
    ):
        raise ProviderConfigError("Only chat/completions-compatible endpoints supported")
    if provider in ("deepseek","openai","qwen","deepseek_web") and url!=PROVIDERS[provider]["url"]:
        raise ProviderConfigError("Use custom provider for nonstandard endpoints")
    if len(config.get("key_env",""))>70:
        raise ProviderConfigError("Invalid key env var")


class _DispatchHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection that reports the local data-release point exactly once."""
    def __init__(self,*args,on_dispatched=None,**kwargs):
        self._on_dispatched=on_dispatched
        super().__init__(*args,**kwargs)

    def request(self,*args,**kwargs):
        result=super().request(*args,**kwargs)
        callback=self._on_dispatched
        self._on_dispatched=None
        if callback is not None:
            callback()
        return result


class _DispatchHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection equivalent used by urllib's normal HTTPS handler path."""
    def __init__(self,*args,on_dispatched=None,**kwargs):
        self._on_dispatched=on_dispatched
        super().__init__(*args,**kwargs)

    def request(self,*args,**kwargs):
        result=super().request(*args,**kwargs)
        callback=self._on_dispatched
        self._on_dispatched=None
        if callback is not None:
            callback()
        return result


class _DispatchHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self,on_dispatched):
        super().__init__()
        self._on_dispatched=on_dispatched

    def http_open(self,req):
        callback=self._on_dispatched
        def factory(host,timeout=socket._GLOBAL_DEFAULT_TIMEOUT,**kwargs):
            return _DispatchHTTPConnection(
                host,timeout=timeout,on_dispatched=callback,**kwargs
            )
        return self.do_open(factory,req)


class _DispatchHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self,on_dispatched,debuglevel=0,context=None,check_hostname=None):
        super().__init__(debuglevel=debuglevel,context=context,check_hostname=check_hostname)
        self._on_dispatched=on_dispatched

    def https_open(self,req):
        callback=self._on_dispatched
        def factory(host,timeout=socket._GLOBAL_DEFAULT_TIMEOUT,**kwargs):
            return _DispatchHTTPSConnection(
                host,timeout=timeout,on_dispatched=callback,**kwargs
            )
        return self.do_open(
            factory,req,context=self._context,check_hostname=self._check_hostname
        )


def _urlopen_with_dispatch(req,timeout,on_dispatched):
    """Use urllib's normal proxy/error/redirect machinery with one send callback."""
    fired=False
    def once():
        nonlocal fired
        if fired:
            return
        fired=True
        on_dispatched()
    opener=urllib.request.build_opener(
        _DispatchHTTPHandler(once),
        _DispatchHTTPSHandler(once),
    )
    return opener.open(req,timeout=timeout)


def project_history(store, limit=16, fail_closed_current_event_id=None):
    """Project recent dialogue for model input without rewriting stored history.

    A recent user utterance can be the canonical source of a long-term memory.
    If that memory was later corrected, retracted or archived through the product
    UI, the raw utterance remains valid conversation history but must not silently
    compete with current-state memory as an unqualified current fact.

    If memory reconciliation itself failed, callers may pass the just-recorded
    current user event. In that fail-closed mode, older dialogue is withheld from
    model input because its current-memory validity could not be established.
    """
    rows=list(store.latest_dialog(limit))
    if fail_closed_current_event_id is not None:
        current_event_id=int(fail_closed_current_event_id)
        rows=[
            x for x in rows
            if x.get("role")=="user"
            and int(x.get("event_id") or -1)==current_event_id
        ]
    user_ids=[int(x["event_id"]) for x in rows if x.get("role")=="user"]
    states={}
    active_texts={}
    deleted_sources=set()
    if user_ids:
        marks=",".join("?" for _ in user_ids)
        query=(
            "SELECT source_event,status,text FROM memories "
            f"WHERE source_event IN ({marks}) ORDER BY memory_id"
        )
        for row in store.conn.execute(query,user_ids):
            source_event=int(row["source_event"])
            status=str(row["status"])
            states.setdefault(source_event,set()).add(status)
            if status=="active":
                active_texts.setdefault(source_event,[]).append(str(row["text"]))
        # Physical deletion removes the memory row, so lifecycle state alone is
        # insufficient. ProductMemoryBridge records a plaintext-free source tombstone.
        for row in store.conn.execute(
            "SELECT extra FROM events WHERE kind='memory.deleted' ORDER BY event_id"
        ):
            try:
                extra=json.loads(row["extra"] or "{}")
                source_event=int(extra.get("source_event"))
            except Exception:
                continue
            if source_event in user_ids:
                deleted_sources.add(source_event)

    labels={
        "superseded":"【历史用户原话：相关长期事实后来已被用户更正，不能作为当前事实；以系统中的当前已确认长期记忆为准】",
        "retracted":"【历史用户原话：相关长期事实后来已被用户撤回，不能作为当前事实】",
        "archived":"【历史用户原话：相关长期事实后来已被用户归档，不应作为当前事实主动使用】",
        "mixed_changed":"【历史用户原话：这条原话关联的部分长期事实后来已被更正、撤回或归档；整条原话不能直接当作当前状态，当前事实以系统中的已确认长期记忆为准】",
        "partial_deleted":"【历史用户原话：这条原话关联的部分长期事实已被物理删除；为避免已删除内容重新进入模型，仅投影仍有效的已确认长期记忆】",
    }
    out=[]
    for row in rows:
        item={"role":row["role"],"content":str(row["content"])[:1500],
              "event_id":row.get("event_id")}
        if item["role"]=="user":
            event_id=int(item["event_id"])
            if event_id in deleted_sources:
                survivors=active_texts.get(event_id,[])
                item["content"]=labels["partial_deleted"]
                if survivors:
                    item["content"]+="\\n"+"\\n".join(survivors)[:1200]
                item["memory_state_annotation"]="partial_deleted"
                out.append(item)
                continue
            status_set=states.get(event_id,set())
            invalid=[x for x in ("retracted","superseded","archived") if x in status_set]
            if invalid:
                # One user turn can support multiple atomic memories. If one remains
                # active while another was corrected/retracted, leaving the whole raw
                # turn unqualified would leak the stale fact through recent history.
                chosen="mixed_changed" if "active" in status_set else invalid[0]
                item["content"]=labels[chosen]+"\n"+item["content"]
                item["memory_state_annotation"]=chosen
        out.append(item)
    return out


def _provider_key(config):
    envvar=config.get("key_env","")
    key=os.getenv(envvar,"").strip() if envvar else ""
    if key:
        return key
    key_file=str(config.get("key_file") or "").strip()
    if key_file:
        try:
            for line in Path(key_file).read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    return line.strip()
        except OSError:
            pass
        raise ProviderConfigError(f"本地模型凭据文件不可用：{key_file}")
    if envvar:
        raise ProviderConfigError(f"请先在系统环境变量中配置 {envvar}，不要把密钥输入聊天记录。")
    return ""

def _chat_once(config, messages, max_tokens, timeout, on_dispatched):
    validate(config)
    key=_provider_key(config)
    body={"model":config["model"], "messages":messages,
          "max_tokens":max_tokens, "stream":False}
    if isinstance(config.get("enable_thinking"),bool):
        body["enable_thinking"]=config["enable_thinking"]
    thinking=str(config.get("thinking") or "").strip().lower()
    if thinking in ("enabled","disabled"):
        body["thinking"]={"type":thinking}
    effort=str(config.get("reasoning_effort") or "").strip().lower()
    if effort in ("none","low","medium","high","max"):
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
        if on_dispatched is None:
            with urllib.request.urlopen(req,timeout=timeout) as resp:
                result=json.loads(resp.read(2_000_000).decode("utf-8"))
        else:
            with _urlopen_with_dispatch(req,timeout,on_dispatched) as resp:
                result=json.loads(resp.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code==402:
            raise RuntimeError(f"{config['provider']} API 返回 402：账户余额或计费不可用。") from None
        raise RuntimeError(f"{config['provider']} API 返回 HTTP {e.code}。") from None
    except urllib.error.URLError:
        raise RuntimeError(f"无法连接 {config['provider']} 模型服务。") from None
    except TimeoutError:
        raise RuntimeError("模型调用超时。") from None
    choices=result.get("choices") or []
    if not choices:
        raise RuntimeError("模型服务没有返回有效回答。")
    msg=choices[0].get("message") or {}
    response=str(msg.get("content") or "").strip()
    if not response:
        raise RuntimeError("模型返回空回复。")
    return response,result.get("usage") or {}

def _fallback_config(provider):
    spec=PROVIDERS[provider]
    cfg={"provider":provider,"url":spec["url"],"model":spec["model"],
         "key_env":spec.get("key_env","")}
    for name in ("key_file","enable_thinking","reasoning_effort"):
        if name in spec:
            cfg[name]=spec[name]
    return cfg

def chat(config, messages, max_tokens=500, timeout=75, on_dispatched=None):
    """OpenAI-compatible messages with ordered provider fallback.

    Credentials stay outside portable identity archives. The dispatch callback is
    still fired at most once even when a fallback provider is attempted.
    """
    fired=False
    def dispatch_once():
        nonlocal fired
        if fired:
            return
        fired=True
        if on_dispatched is not None:
            on_dispatched()

    chain=[config]
    for provider in config.get("fallbacks",[]):
        if provider in PROVIDERS and provider!=config.get("provider"):
            chain.append(_fallback_config(provider))
    errors=[]
    for candidate in chain:
        try:
            return _chat_once(candidate,messages,max_tokens,timeout,
                              dispatch_once if on_dispatched is not None else None)
        except (ProviderConfigError,RuntimeError) as exc:
            errors.append((candidate.get("provider","unknown"),str(exc)))
    if len(errors)==1:
        raise RuntimeError(errors[0][1])
    names=" -> ".join(name for name,_ in errors)
    raise RuntimeError(f"模型主路由及后备路由均不可用（{names}）。")

