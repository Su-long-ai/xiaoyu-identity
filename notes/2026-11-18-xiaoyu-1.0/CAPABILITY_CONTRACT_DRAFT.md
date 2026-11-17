# XiaoYu Capability Contract v0.1 — Design Draft

**Status:** architecture draft, not yet implementation authority.  
**Goal:** define the smallest stable host boundary needed to make capability providers replaceable without turning XiaoYu Kernel into a generic plugin framework.

---

# 1. Contract principles

1. Kernel owns durable semantic truth.
2. Providers own implementation details.
3. A provider is not trusted because it is installed.
4. Discovery does not imply loading.
5. Loading does not imply permission.
6. Health is not a boolean.
7. Capability support is negotiated, not inferred from provider name.
8. One router owns retries/fallbacks.
9. Provider state is ephemeral unless explicitly versioned/exportable.
10. Every production provider must pass conformance tests.

---

# 2. Provider descriptor

Minimum shape:

```json
{
  "id": "qwen3-tts-local",
  "capability": "speech.tts",
  "implementation_version": "0.4.0",
  "contract": {
    "name": "xiaoyu.speech.tts",
    "min_version": "1.1.0",
    "max_exclusive": "2.0.0"
  },
  "isolation": "sidecar",
  "features": {
    "streaming": true,
    "cancel": true,
    "voice_clone": true
  },
  "activation": "on_first_use",
  "permissions_required": ["audio.output"],
  "permissions_optional": [],
  "trust": "first_party",
  "fallback_group": "speech.tts.default"
}
```

---

# 3. Common lifecycle

```
discover
resolve
start
health
capabilities
reconfigure
drain
stop
diagnostics
```

A provider may additionally implement:

```
warmup
cancel
snapshot_runtime_state
restore_runtime_state
```

---

# 4. Common provider states

```
DISCOVERED
INSTALLED
RESOLVED
STARTING
READY
DEGRADED
DRAINING
STOPPING
STOPPED
FAILED
DISABLED
```

State transitions must be explicit and observable.

---

# 5. Common health response

```json
{
  "state": "READY",
  "reason": null,
  "since": "...",
  "features_available": ["streaming", "cancel", "voice_clone"],
  "retry_after_ms": null,
  "details": {}
}
```

DEGRADED providers may remain routable if the request does not require the missing feature.

---

# 6. Invocation context

Every capability call receives host-generated metadata:

```
request_id
turn_id
principal
surface
deadline
cancellation_token
permission_context
trace_context
resource_mode
```

Provider must not invent authorization.

---

# 7. Failure classes

Standardize at least:

```
CANCELLED
TIMEOUT
RATE_LIMIT
AUTHENTICATION
PERMISSION_DENIED
INVALID_CONFIG
UNSUPPORTED_FEATURE
UNSUPPORTED_CONTRACT
RESOURCE_EXHAUSTED
UNAVAILABLE
BAD_INPUT
BAD_OUTPUT
PROVIDER_INTERNAL
EXTERNAL_UNKNOWN_STATE
```

Provider-specific exceptions are mapped at adapter boundary.

---

# 8. Router semantics

Single selection algorithm:

```
eligible providers
  = compatible contract
  ∩ required features
  ∩ permitted
  ∩ enabled
  ∩ health-eligible

then apply:
  explicit user pin
  locality/privacy policy
  resource policy
  cost/latency policy
  quality priority
```

Fallback policy belongs to the capability contract.

---

# 9. Conformance suite

Every capability contract owns tests.

Examples common to all providers:

- descriptor valid
- incompatible version rejected
- required feature advertised accurately
- start/stop idempotence
- health after start
- health after stop
- cancellation
- timeout
- malformed input
- cleanup
- diagnostics does not leak secrets

Provider-specific tests remain separate.

---

# 10. In-process provider rules

Allowed only when:

- trusted first-party;
- no dangerous native crash surface;
- bounded synchronous work or proper async behavior;
- no hidden durable state.

Discovery may use Python entry points.

In-process provider must not import Kernel internals outside its public contract.

---

# 11. Sidecar provider rules

Must support:

- explicit protocol version;
- handshake;
- capability negotiation;
- heartbeat/health;
- graceful shutdown;
- forced cleanup;
- request IDs;
- cancellation.

Preferred local transports:

- stdio for simple child-owned providers;
- Windows named pipe for persistent duplex service.

Avoid unauthenticated localhost TCP by default.

---

# 12. Sidecar supervision

On Windows:

- attach sidecars to a Job Object;
- prefer KILL_ON_JOB_CLOSE semantics;
- capture exit code;
- restart with bounded exponential backoff;
- stop restarting after repeated deterministic failures;
- expose FAILED state and remediation.

---

# 13. Third-party plugin rules

Future third-party code should not automatically receive full Python process privileges.

Preferred future direction:

```
Wasm component / Extism
```

Capabilities exposed through explicit host imports.

Default:

- no filesystem;
- no network;
- no secrets;
- no memory authority;
- no external action.

Grant narrowly.

---

# 14. Upgrade compatibility

Provider installation never replaces the last known good version immediately.

Maintain:

```
current
candidate
last_known_good
```

Candidate must:

- verify artifact;
- pass contract;
- start;
- become healthy;
- pass smoke/conformance;
- optionally shadow.

Then switch.

---

# 15. Hot-swap support declaration

Each contract/provider declares:

```
hot_swap:
  level: H0 | H1 | H2 | H3 | H4
  state_portability: none | ephemeral | versioned
```

The host never assumes hot-swap.

---

# 16. Durable state rule

Provider may cache durable truth but may not own it unless the Kernel contract explicitly delegates authority.

For XiaoYu 1.x the default authority remains Kernel SQLite/event state.

---

# 17. Data classification

Provider descriptor declares what data it may receive:

```
assistant_text
user_text
owner_profile
retrieved_memory
screen_pixels
microphone_audio
camera_pixels
filesystem_content
tool_output
```

The authorization/privacy layer can therefore reject a provider even if it technically implements the capability.

---

# 18. Resource interface

Provider reports measured runtime metrics when possible:

```
rss_mb
vram_mb
cpu_percent
queue_depth
active_requests
startup_ms
last_request_latency_ms
```

Router may use them for resource modes.

---

# 19. Activation rules

Supported triggers:

```
startup
on_first_use
on_surface_enable
on_permission_grant
manual
```

Heavy providers should not default to startup.

---

# 20. Kernel contract freeze rule

Before calling XiaoYu 1.0 final, freeze the first set of public capability contracts and version them.

Internal implementation may continue changing behind those boundaries.

This makes future provider replacement a normal upgrade, not a project-wide refactor.
