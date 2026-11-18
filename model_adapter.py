# -*- coding: utf-8 -*-
"""Replaceable chat-completion adapter. Provider settings stay OUTSIDE identity archives."""
from __future__ import annotations
import hashlib
import http.client
import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from xiaoyu.contracts import (
    CapabilityDescriptor,
    IsolationMode,
    ProviderLifecycle,
)
from xiaoyu.runtime.credentials import (
    KeyringCredentialRef,
    OptionalCredentialStoreUnavailable,
    SystemKeyringCredentialStore,
)
from xiaoyu.runtime.provider_registry import (
    PrivacyClass,
    ProviderDescriptor,
    evaluate_provider,
    fallback_audit,
    stable_digest,
)

DEFAULT_ALLOWED_DATA_CLASSES = {
    "deepseek_web": ("PUBLIC", "OWNER_PRIVATE"),
    "deepseek": ("PUBLIC", "OWNER_PRIVATE"),
    "openai": ("PUBLIC", "OWNER_PRIVATE"),
    "qwen": ("PUBLIC", "OWNER_PRIVATE"),
    "ollama": ("PUBLIC", "OWNER_PRIVATE", "LOCAL_ONLY"),
    "custom": ("PUBLIC",),
}

ADAPTER_ARTIFACT_DIGEST=(
    "sha256:"+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
)

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
               "model":"qwen3:8b","key_env":"","data_boundary":"LOCAL"},
    "custom": {"url":"https://example.invalid/v1/chat/completions",
               "model":"","key_env":"FISH_CUSTOM_API_KEY"}
}

class ProviderConfigError(RuntimeError): pass

class ProviderDispatchUncertain(RuntimeError):
    """The request may have been partially disclosed; automatic fallback is unsafe."""
    pass

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
    for name in ("keyring_service","keyring_username"):
        value=raw.get(name) if name in raw else base.get(name)
        if value:
            config[name]=str(value).strip()
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
    """Release freshness only after the complete request body is dispatched."""
    def __init__(self,*args,on_dispatched=None,**kwargs):
        self._on_dispatched=on_dispatched
        self._dispatch_started=False
        super().__init__(*args,**kwargs)

    def send(self,data):
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise http.client.NotConnected()
        self._dispatch_started=True
        return super().send(data)

    def request(self,*args,**kwargs):
        self._dispatch_started=False
        try:
            result=super().request(*args,**kwargs)
        except Exception as exc:
            if self._dispatch_started:
                raise ProviderDispatchUncertain(
                    "provider request may have been partially dispatched"
                ) from exc
            raise
        callback=self._on_dispatched
        self._on_dispatched=None
        if callback is not None:
            callback()
        return result


class _DispatchHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS equivalent with the same complete-body dispatch boundary."""
    def __init__(self,*args,on_dispatched=None,**kwargs):
        self._on_dispatched=on_dispatched
        self._dispatch_started=False
        super().__init__(*args,**kwargs)

    def send(self,data):
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise http.client.NotConnected()
        self._dispatch_started=True
        return super().send(data)

    def request(self,*args,**kwargs):
        self._dispatch_started=False
        try:
            result=super().request(*args,**kwargs)
        except Exception as exc:
            if self._dispatch_started:
                raise ProviderDispatchUncertain(
                    "provider request may have been partially dispatched"
                ) from exc
            raise
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


def _keyring_ref(config):
    service=str(config.get("keyring_service") or "").strip()
    username=str(config.get("keyring_username") or "").strip()
    provider=str(config.get("provider") or "").strip().lower()
    if not service and provider in (
        "deepseek_web", "deepseek", "openai", "qwen"
    ):
        service="XiaoYu Provider API"
    if service and not username:
        username=provider or "default"
    if not service or not username:
        return None
    return KeyringCredentialRef(service=service,username=username)


def _keyring_provider_key(config):
    ref=_keyring_ref(config)
    if ref is None:
        return ""
    try:
        value=SystemKeyringCredentialStore().get(ref)
    except OptionalCredentialStoreUnavailable:
        return ""
    except Exception:
        # A broken optional OS-keyring integration must not break legacy
        # environment/file credentials. If no fallback exists, _provider_key
        # below still fails closed with a user-facing configuration error.
        return ""
    return value or ""


def _provider_key(config):
    envvar=config.get("key_env","")
    key=os.getenv(envvar,"").strip() if envvar else ""
    if key:
        return key
    key=_keyring_provider_key(config)
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
        raise ProviderConfigError(
            f"凭据不可用：系统凭据库无可用项，且本地凭据文件不可用：{key_file}"
        )
    if envvar or _keyring_ref(config) is not None:
        target=envvar or str(config.get("provider") or "provider")
        raise ProviderConfigError(
            f"请在系统环境变量 {target} 或 Windows 凭据库中配置模型密钥，不要把密钥输入聊天记录。"
        )
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

def _provider_allows_data_class(config, required_data_class):
    if not required_data_class:
        return True
    explicit=config.get("allowed_data_classes")
    if explicit is not None:
        allowed={str(x).strip().upper() for x in explicit}
    else:
        allowed=set(DEFAULT_ALLOWED_DATA_CLASSES.get(
            str(config.get("provider") or "").lower(),
            ("PUBLIC",),
        ))
    return str(required_data_class).upper() in allowed


def _clone_messages(messages):
    return json.loads(json.dumps(messages,ensure_ascii=False))


def _provider_descriptor(config):
    provider=str(config.get("provider") or "unknown").lower()
    explicit=config.get("allowed_data_classes")
    if explicit is not None:
        allowed=tuple(sorted({str(x).strip().upper() for x in explicit}))
    else:
        allowed=tuple(sorted(DEFAULT_ALLOWED_DATA_CLASSES.get(provider,("PUBLIC",))))
    privacy=[]
    for value in allowed:
        try:
            privacy.append(PrivacyClass(value))
        except ValueError:
            continue
    parsed=urlsplit(str(config.get("url") or ""))
    declared_boundary=str(
        config.get("data_boundary")
        or PROVIDERS.get(provider,{}).get("data_boundary")
        or "REMOTE"
    ).upper()
    endpoint_scope=(
        "LOCAL"
        if (
            declared_boundary=="LOCAL"
            and parsed.hostname in ("localhost","127.0.0.1","::1")
        )
        else "REMOTE"
    )
    session_mode=str(
        config.get("session_mode")
        or PROVIDERS.get(provider,{}).get("session_mode")
        or "STATELESS"
    ).upper()
    capability_digest=stable_digest({
        "provider":provider,
        "model":str(config.get("model") or ""),
        "capability":"chat.completion",
    })
    implementation_digest=stable_digest({
        "adapter":"model_adapter",
        "artifact_digest":ADAPTER_ARTIFACT_DIGEST,
        "provider":provider,
        "url":str(config.get("url") or ""),
    })
    descriptor_digest=stable_digest({
        "provider":provider,
        "url":str(config.get("url") or ""),
        "model":str(config.get("model") or ""),
        "privacy_classes":[x.value for x in privacy],
        "endpoint_scope":endpoint_scope,
        "session_mode":session_mode,
        "capability_digest":capability_digest,
        "implementation_digest":implementation_digest,
        "policy_version":2,
    })
    return ProviderDescriptor(
        provider_id=provider,
        capability="chat.completion",
        descriptor_digest=descriptor_digest,
        capability_digest=capability_digest,
        implementation_digest=implementation_digest,
        endpoint_scope=endpoint_scope,
        privacy_classes=tuple(privacy),
        session_mode=session_mode,
    )



def capability_descriptor_for_config(config):
    """Bridge adapter config into XiaoYu's public capability contract."""
    runtime_descriptor=_provider_descriptor(config)
    interface_digest=stable_digest({
        "contract":"openai.chat.completions",
        "request":{
            "messages":"list",
            "max_tokens":"int",
            "stream":False,
        },
        "response":{
            "choices.message.content":"str",
            "usage":"object",
        },
        "adapter_policy_version":2,
    })
    isolation=(
        IsolationMode.SIDECAR
        if runtime_descriptor.endpoint_scope=="LOCAL"
        else IsolationMode.REMOTE
    )
    return CapabilityDescriptor(
        provider_id=runtime_descriptor.provider_id,
        capability=runtime_descriptor.capability,
        implementation_version="model-adapter-v2",
        contract_name="openai.chat.completions",
        contract_min_version="1.0",
        contract_max_exclusive="2.0",
        artifact_digest=ADAPTER_ARTIFACT_DIGEST,
        descriptor_digest=runtime_descriptor.descriptor_digest,
        interface_digest=interface_digest,
        tool_schema_digest=None,
        isolation=isolation,
        features={
            "capability_digest":runtime_descriptor.capability_digest,
            "implementation_digest":
                runtime_descriptor.implementation_digest,
            "endpoint_scope":runtime_descriptor.endpoint_scope,
            "session_mode":runtime_descriptor.session_mode,
            "model":str(config.get("model") or ""),
            "fallback_capable":True,
        },
        data_classes=tuple(
            value.value
            for value in runtime_descriptor.privacy_classes
        ),
        permissions_required=(
            ("network",)
            if runtime_descriptor.endpoint_scope!="LOCAL"
            else ()
        ),
        fallback_group="chat.completion",
        lifecycle=ProviderLifecycle.ACTIVE,
        resource_profile={},
    )


def chat(
    config,
    messages,
    max_tokens=500,
    timeout=75,
    on_dispatched=None,
    attempt_guard=None,
    required_data_class=None,
    attempt_audit=None,
    provider_health=None,
    runtime_host=None,
    required_features=(),
    transport_backend=None,
):
    """OpenAI-compatible messages with ordered provider fallback.

    Every concrete provider attempt gets a fresh eligibility decision, fresh
    message object, and (when supplied) a fresh authority/freshness guard.
    """
    if not str(required_data_class or "").strip():
        raise ProviderConfigError(
            "required_data_class must be explicit for every provider attempt"
        )
    fired=False
    def dispatch_once():
        nonlocal fired
        if fired:
            return
        fired=True
        if on_dispatched is not None:
            on_dispatched()

    chain=[None]
    # Every provider boundary requires an explicit payload classification.
    # Once classified, fallback candidates are independently revalidated.
    for provider in config.get("fallbacks",[]):
        if provider in PROVIDERS and provider!=config.get("provider"):
            chain.append(provider)

    errors=[]
    for fallback_provider in chain:
        candidate=(
            dict(config)
            if fallback_provider is None
            else _fallback_config(fallback_provider)
        )
        name=candidate.get("provider","unknown")
        guard=attempt_guard(candidate) if attempt_guard is not None else None
        if guard is None:
            class _NoopGuard:
                def __enter__(self):
                    return self
                def __exit__(self,*args):
                    return False
            guard=_NoopGuard()

        with guard:
            descriptor=_provider_descriptor(candidate)
            health=(
                provider_health(descriptor)
                if provider_health is not None else None
            )
            if runtime_host is not None:
                runtime_admission=runtime_host.admit_provider(
                    descriptor,
                    required_data_class=required_data_class,
                    required_features=tuple(required_features or ()),
                    live_health=health,
                )
                if not runtime_admission.allowed:
                    errors.append((
                        name,
                        "runtime host rejected provider: "
                        + ",".join(runtime_admission.reasons),
                    ))
                    continue
            context_builder=getattr(guard,"provider_attempt_context",None)
            if context_builder is not None:
                attempt_context=context_builder(descriptor,required_data_class)
                eligibility=evaluate_provider(
                    descriptor,attempt_context,health
                )
                if attempt_audit is not None:
                    attempt_audit(fallback_audit(attempt_context,eligibility))
                if not eligibility.allowed:
                    errors.append((
                        name,
                        "provider ineligible: "+",".join(eligibility.reasons),
                    ))
                    continue
            else:
                if not _provider_allows_data_class(candidate,required_data_class):
                    errors.append((
                        name,
                        f"provider not eligible for {required_data_class}",
                    ))
                    continue
                if (
                    health is not None
                    and str(health.readiness).upper()!="READY"
                ):
                    errors.append((name,"provider not ready"))
                    continue

            message_builder=getattr(guard,"messages_for_attempt",None)
            attempt_messages=(
                message_builder(messages)
                if message_builder is not None
                else _clone_messages(messages)
            )
            per_attempt=getattr(guard,"on_dispatched",None)
            def dispatched():
                if per_attempt is not None:
                    per_attempt()
                dispatch_once()
            callback=(
                dispatched
                if (per_attempt is not None or on_dispatched is not None)
                else None
            )
            try:
                if transport_backend is None:
                    result=_chat_once(
                        candidate,attempt_messages,max_tokens,timeout,callback
                    )
                else:
                    result=transport_backend.complete(
                        candidate,
                        attempt_messages,
                        max_tokens,
                        timeout,
                        callback,
                        api_key=_provider_key(candidate),
                    )
            except ProviderDispatchUncertain:
                # Some bytes may already have crossed the provider boundary,
                # but the complete request was not confirmed dispatched.
                # Never replay the same private context to another provider.
                raise
            except ProviderConfigError as exc:
                errors.append((name,str(exc)))
                continue
            except RuntimeError as exc:
                # External SDK/backend exception text is untrusted: it may
                # include Authorization headers, request payloads or secrets.
                # Preserve the concrete provider identity, never raw text.
                if transport_backend is not None:
                    errors.append((name,"external transport backend failed"))
                else:
                    errors.append((name,str(exc)))
                continue

            on_response=getattr(guard,"on_response",None)
            if on_response is not None:
                on_response()

            # Re-evaluate provider policy/health after the request returns.
            # A result that crossed the wire under one privacy/capability
            # contract is not silently accepted after that contract changes.
            fresh_descriptor=_provider_descriptor(candidate)
            if fresh_descriptor.descriptor_digest != descriptor.descriptor_digest:
                raise RuntimeError(
                    "provider descriptor changed after dispatch"
                )
            fresh_health=(
                provider_health(fresh_descriptor)
                if provider_health is not None else None
            )
            if runtime_host is not None:
                fresh_runtime_admission=runtime_host.admit_provider(
                    fresh_descriptor,
                    required_data_class=required_data_class,
                    required_features=tuple(required_features or ()),
                    live_health=fresh_health,
                )
                if not fresh_runtime_admission.allowed:
                    raise RuntimeError(
                        "runtime host eligibility changed after dispatch: "
                        + ",".join(fresh_runtime_admission.reasons)
                    )
            if context_builder is not None:
                fresh_context=context_builder(
                    fresh_descriptor,required_data_class
                )
                fresh_eligibility=evaluate_provider(
                    fresh_descriptor,fresh_context,fresh_health
                )
                if not fresh_eligibility.allowed:
                    raise RuntimeError(
                        "provider eligibility changed after dispatch: "
                        + ",".join(fresh_eligibility.reasons)
                    )
            else:
                if not _provider_allows_data_class(
                    candidate,required_data_class
                ):
                    raise RuntimeError(
                        "provider privacy eligibility changed after dispatch"
                    )
                if (
                    fresh_health is not None
                    and str(fresh_health.readiness).upper()!="READY"
                ):
                    raise RuntimeError(
                        "provider health changed after dispatch"
                    )
            return result

    if len(errors)==1:
        raise RuntimeError(errors[0][1])
    names=" -> ".join(name for name,_ in errors)
    raise RuntimeError(f"模型主路由及后备路由均不可用（{names}）。")
