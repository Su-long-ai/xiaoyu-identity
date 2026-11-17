# XiaoYu Replaceable-Module Architecture · Saturated External Survey

**Date:** 2026-11-18  
**Question:** What happens if every implementation-facing module in XiaoYu is replaceable?  
**Conclusion:** This is a strong direction, but only if XiaoYu separates **stable semantic authority** from **replaceable capability implementations** and uses multiple isolation classes instead of one universal plugin mechanism.

---

# 1. The core architectural conclusion

The mature systems surveyed converge on the same pattern:

1. define a stable host/kernel contract;
2. discover implementations declaratively;
3. negotiate capabilities before use;
4. activate lazily;
5. isolate failures according to risk;
6. support unload/reload/reconfigure;
7. version the contract independently from implementation versions;
8. verify compatibility with contract tests;
9. keep durable state owned by the host when possible;
10. make permissions explicit and revocable.

For XiaoYu this means:

```
XiaoYu Kernel
  identity semantics
  event semantics
  memory authority
  temporal truth
  canonical turn
  purpose lifecycle
  authorization semantics
  capability registry
          │
          ▼
Capability Providers
  reasoning
  retrieval
  vision capture
  vision understanding
  ASR
  VAD
  TTS
  avatar/body
  messaging surfaces
  tools
  scheduler
  computer use
  sync
  telemetry
```

The **provider implementations** are replaceable.

The **kernel semantics** are not plugins.

---

# 2. What should stay inside the Kernel

These define what XiaoYu *is*, not how a function is implemented:

- identity authority
- event ledger semantics
- memory authority rules
- temporal truth / supersession semantics
- canonical turn ordering
- purpose lifecycle
- authorization policy semantics
- external-effect receipts
- capability registry itself

These may be refactored internally, but an external module cannot redefine their meaning.

Otherwise two providers can disagree on:

- who XiaoYu is;
- which memory is current;
- whether a purpose is cancelled;
- whether an action is authorized.

That creates split-brain behavior.

---

# 3. Four isolation classes instead of one plugin system

## Class A — Trusted in-process provider

Best for:

- pure Python;
- lightweight;
- low crash risk;
- low native dependency risk;
- frequent calls.

Examples:

- lexical retriever;
- profile projection;
- lightweight reranker;
- local formatting/normalization.

Discovery can use Python entry points or a simple explicit registry.

A hook manager such as pluggy is a mature option if multiple ordered hooks are ever needed.

### Advantage

Lowest latency and simplest state sharing.

### Risk

A crash, memory leak or blocking call can affect Core.

### XiaoYu rule

Only first-party trusted providers may run in-process.

---

## Class B — Local sidecar process

Best for:

- GPU models;
- native libraries;
- Node services;
- heavy runtimes;
- components likely to leak/crash;
- components needing independent upgrade/restart.

Examples:

- dsh-see-now;
- Qwen3-TTS;
- GPT-SoVITS;
- local vision model;
- heavy ASR runtime;
- future browser/computer-use controller.

HashiCorp's battle-tested go-plugin architecture demonstrates the main benefit of the subprocess/RPC model: plugin crashes do not crash the host, and plugin processes can be independently upgraded/reattached.

### XiaoYu rule

Heavy or unstable capability implementations should default to sidecars.

---

## Class C — Sandboxed WebAssembly plugin

Best future use:

- third-party transforms;
- small tools;
- parsers;
- scoring/ranking extensions;
- deterministic skill helpers;
- user-installed plugins that should not get host-level process access.

The WebAssembly Component Model's WIT "world" model is especially attractive because a component explicitly declares what it exports and what it imports. If a component is not given a filesystem/network/secret import, it cannot directly access that capability.

Extism adds practical embedding features:

- per-plugin memory limits;
- HTTP host allowlists;
- filesystem path allowlists;
- hash verification;
- execution limits/cancellation;
- Python host SDK.

### XiaoYu rule

Do not use Wasm for 1.0. Keep it as the preferred future sandbox for genuinely third-party code.

---

## Class D — Remote provider

Best for:

- cloud LLM;
- cloud vision;
- remote speech;
- future remote sync/compute.

Remote providers are inherently process-isolated but add:

- privacy boundary;
- network failure;
- latency;
- API compatibility;
- billing.

They still implement the same XiaoYu capability contract at the host boundary.

---

# 4. Capability contract vs implementation

Every provider has two independent versions:

```
contract_version
implementation_version
```

Example:

```
Capability: speech.tts
Contract: 1.2
Implementation: qwen3-tts-adapter 0.4.3
Model: Qwen3-TTS-0.6B revision ...
```

Why separate them:

A new model build should not imply the XiaoYu interface changed.

A contract change should be explicit and independently testable.

Semantic Versioning is appropriate for stable capability contracts:

- MAJOR = incompatible interface/semantic change
- MINOR = backward-compatible feature addition
- PATCH = compatible bug fix/clarification

---

# 5. Capability negotiation

Do not identify providers by implementation name in product logic.

Bad:

```
if provider == "qwen3_tts":
    enable_streaming()
```

Good:

```
if provider.supports("streaming"):
    ...
```

MCP and the WebAssembly Component Model both reinforce this design:

- establish protocol/interface compatibility first;
- advertise provided features;
- consume only negotiated features.

Example feature set:

```json
{
  "streaming": true,
  "cancel": true,
  "voice_clone": true,
  "emotion": false,
  "timestamps": true
}
```

This avoids lowest-common-denominator interfaces.

---

# 6. Capability manifest

Recommended manifest fields:

```yaml
id: qwen3-tts-local
capability: speech.tts
implementation_version: 0.4.0
contract:
  name: xiaoyu.speech.tts
  versions: ">=1.1,<2.0"

isolation: sidecar
entrypoint: ...

provides:
  streaming: true
  cancellation: true
  voice_clone: true

requires:
  os: windows
  python: ">=3.11"
  gpu: optional

activation:
  - on_first_use

permissions:
  - audio.output

data_access:
  input:
    - assistant_text
  output:
    - synthesized_audio

resources:
  expected_ram_mb: ...
  expected_vram_mb: ...

health:
  startup_timeout_ms: ...
  heartbeat: ...

fallback_group: speech.tts.default
priority: 100
```

For third-party plugins also record:

- source;
- artifact hash;
- signature;
- license;
- install time;
- requested permissions;
- current grants.

---

# 7. Lifecycle state machine

Borrow the strongest ideas from OSGi, VS Code and Home Assistant.

Recommended provider states:

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

Core lifecycle methods:

```
probe()
start()
health()
capabilities()
reconfigure()
drain()
stop()
diagnostics()
```

Optional:

```
warmup()
snapshot_runtime_state()
restore_runtime_state()
```

Home Assistant's integration quality model strongly supports two product requirements:

1. providers should unload/reload without restarting the whole product;
2. credentials/settings should be reauthenticated/reconfigured without deleting/recreating the integration and losing state.

---

# 8. Lazy activation

VS Code's activation-event architecture is a strong model.

Heavy capabilities should not all start with XiaoYu.

Examples:

```
speech.tts       -> on first spoken response
perception.screen -> when watch/peek enabled
vision.reasoning -> only when an image needs interpretation
computer.use     -> explicit task
retrieval.gpu    -> only when non-empty authorized corpus requires it
```

This reduces:

- startup time;
- idle RAM;
- idle VRAM;
- background failure surface.

Current XiaoYu's “no memories -> do not start retrieval worker” is exactly this philosophy.

---

# 9. Permission-on-demand

Browser WebExtensions provide an excellent precedent:

- baseline permissions are declared;
- optional permissions are requested only at runtime;
- denial is survivable;
- grants can be inspected/revoked.

XiaoYu provider manifests should therefore separate:

```
required_permissions
optional_permissions
```

Example screen module:

```
required: []
optional:
  - screen.capture
  - microphone.capture
```

A provider may install and remain usable in reduced mode if the optional permission is denied.

---

# 10. Dependency model

Do not let arbitrary plugin code import arbitrary other plugins.

Use explicit dependency metadata:

```
requires_capabilities:
  - audio.playback >=1
optional_capabilities:
  - avatar.lipsync >=1
```

Home Assistant's distinction between required `dependencies` and optional `after_dependencies` is useful:

- required dependency: provider cannot start without it;
- optional dependency: if present, initialize first, but provider still works without it.

Reject dependency cycles at manifest validation time.

---

# 11. Routing is a separate subsystem

A replaceable architecture needs two layers:

```
Capability Registry
        ↓
Capability Router
```

Registry answers:

> what providers exist and what can they do?

Router answers:

> which healthy provider should serve this request?

Selection inputs may include:

- user pin;
- required features;
- permissions;
- trust;
- health;
- local/cloud preference;
- latency;
- cost;
- VRAM availability;
- quality profile;
- current mode ECO/BALANCED/FULL.

---

# 12. Retry ownership must be singular

LiteLLM's routing architecture has an important lesson:

> one layer owns retries.

It explicitly disables nested provider retries so a request does not multiply retries at several stack levels.

XiaoYu should follow the same rule.

Bad:

```
Core retries 3
  × provider adapter retries 3
  × SDK retries 2
= potentially many duplicated attempts
```

Good:

```
Capability Router owns retry/fallback policy
Provider adapters expose failure type and Retry-After
Underlying SDK automatic retries disabled where possible
```

---

# 13. Typed failure classes

Do not route every failure the same way.

Examples:

- AUTH_ERROR -> no retry; request reauthentication
- RATE_LIMIT -> retry/cooldown/fallback
- TIMEOUT -> bounded retry/fallback
- UNSUPPORTED_FEATURE -> choose another provider
- CONTEXT_TOO_LARGE -> appropriate model fallback
- OUT_OF_MEMORY -> unload/cooldown or choose lighter local provider
- INVALID_CONFIG -> DEGRADED/FAILED until reconfigured
- USER_DENIED_PERMISSION -> do not repeatedly ask
- CANCELLED -> no fallback unless policy says otherwise

LiteLLM's separation between retries, fallbacks and cooldowns is a useful reference.

---

# 14. Health states

Every provider needs separate:

```
process_alive
ready
healthy
capability_available
```

A process can be alive but not usable.

gRPC's standard health checking model demonstrates why clients should stop sending traffic to a provider that reports unhealthy and resume when it becomes healthy.

Recommended health result:

```json
{
  "state": "DEGRADED",
  "reason": "gpu_oom",
  "capabilities_available": ["basic_tts"],
  "capabilities_unavailable": ["voice_clone"],
  "retry_after_ms": 5000
}
```

---

# 15. Hot replacement levels

Not every provider can be hot-swapped equally.

## H0 — restart required

Use for:

- Kernel storage migration;
- authority semantics;
- major contract upgrade.

## H1 — stop/start replacement

Provider stops, new provider starts.

Good for:

- capture engine;
- avatar renderer;
- some native providers.

## H2 — drain-and-switch

Old provider stops accepting new work; in-flight work finishes/cancels; new provider warms; registry pointer changes.

Good for:

- TTS;
- ASR;
- vision;
- scheduler sidecar.

## H3 — request-level routing

Provider chosen independently per request.

Good for:

- LLM;
- remote vision;
- embeddings;
- rerankers.

## H4 — automatic fallback

Router switches providers on typed failure.

Good only where semantic continuity is safe.

---

# 16. Safe hot-swap algorithm

Recommended procedure:

```
1 discover candidate
2 validate manifest + permissions
3 verify contract compatibility
4 run provider conformance tests
5 start candidate
6 warm up
7 health check
8 optionally shadow-test
9 mark old provider DRAINING
10 stop new requests to old provider
11 finish/cancel in-flight requests
12 atomically switch registry route
13 observe health/error/latency window
14 stop old provider
15 retain rollback metadata
```

If the new provider fails during observation:

```
route back to old provider
```

Do not overwrite provider config before successful cutover.

---

# 17. State ownership determines replaceability

The easiest modules to replace are stateless.

Hardest modules are those that privately own durable state.

Therefore:

> durable user state should stay in XiaoYu Kernel whenever practical.

Preferred provider-owned state:

- caches;
- compiled models;
- temporary streaming buffers;
- health counters;
- ephemeral sessions.

Kernel-owned state:

- identity;
- memory;
- purpose;
- permissions;
- skill definitions;
- external-effect receipts.

This sharply lowers migration cost.

---

# 18. Provider-specific state

Sometimes state is unavoidable.

Examples:

- voice-clone embedding;
- local ASR adaptation;
- provider session cache.

Then require:

```
state_schema_version
export_state()
import_state()
```

or explicitly declare:

```
state_portability: none
```

The host must never silently assume portability.

---

# 19. Contract tests

Every provider should pass a shared conformance suite before registration as READY.

This is the capability equivalent of consumer/provider contract testing.

Example TTS conformance:

- valid text returns audio;
- empty input behavior;
- cancellation;
- streaming order;
- health;
- timeout;
- malformed config;
- unsupported feature response;
- resource cleanup.

A provider-specific test suite is still required for implementation details.

The common conformance suite verifies the shared XiaoYu contract.

---

# 20. Contract compatibility matrix

Maintain:

```
provider implementation
× capability contract version
× operating system
× runtime
× model revision
```

Do not say “supports TTS” as a single boolean.

Example:

```
qwen3-tts-adapter 0.4.0
  xiaoyu.speech.tts 1.2 PASS
  Windows 11 PASS
  RTX 4060 Laptop PASS
  model rev X PASS
```

---

# 21. Dynamic discovery

For first-party Python providers, Python package entry points are a standard discovery mechanism.

A package can advertise:

```
[project.entry-points."xiaoyu.capabilities"]
qwen3_tts = "xiaoyu_qwen_tts:provider"
```

XiaoYu can discover via `importlib.metadata.entry_points()`.

However:

**Do not auto-load every discovered provider.**

Discovery is metadata-only.

Load only after:

- allowlist;
- compatibility;
- permission;
- selection.

---

# 22. Why not make everything pluggy hooks

pluggy is excellent for trusted in-process extension hooks and has proven scale through pytest.

It is not a security boundary.

Therefore use pluggy only if XiaoYu later needs multiple ordered first-party callbacks such as:

- pre-turn enrichers;
- diagnostic sinks;
- policy observers.

Do not use it for untrusted modules, GPU models or crash-prone native runtimes.

---

# 23. Why not use MCP as the universal internal bus

MCP contributes useful ideas:

- discovery;
- version negotiation;
- capability negotiation;
- lifecycle;
- tool/resource semantics.

But XiaoYu should not force every internal capability through MCP.

Reasons:

- TTS audio streams are not naturally tool calls;
- high-frequency frame/audio data should not be repeatedly serialized as generic JSON-RPC;
- internal providers often need lower-latency typed APIs;
- Core-owned semantics should not be exposed as arbitrary tools.

Recommended rule:

- external/general tools -> MCP is appropriate;
- XiaoYu internal capabilities -> XiaoYu Capability Contract;
- borrow MCP's negotiation/lifecycle principles.

---

# 24. Sidecar IPC on Windows

For simple child sidecars:

- stdin/stdout framed messages are sufficient.

For persistent duplex local services:

- Windows named pipes are a strong option;
- ACLs can restrict callers;
- use local/session-scoped naming.

Do not expose a localhost TCP port by default unless the component needs it.

For large media payloads:

- pass a bounded local file/shared-memory handle where appropriate rather than base64 JSON repeatedly.

---

# 25. Sidecar process ownership

Windows Job Objects are especially useful for XiaoYu.

With `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, closing the owning job handle terminates associated processes.

This fits:

- Vision sidecar;
- TTS sidecar;
- ASR worker;
- browser/computer-use worker.

Goal:

> closing XiaoYu or disabling a capability cannot leave orphan GPU/Node/Python processes behind.

---

# 26. Resource budgets belong in provider metadata

A provider should declare approximate requirements:

```
ram
vram
cpu_class
gpu_required
startup_latency
idle_residency
```

The runtime then can implement product modes:

## ECO
prefer lightweight / unload aggressively

## BALANCED
normal local capability set

## FULL
prefer best-quality local providers

Resource data is advisory; measured telemetry overrides manifest hints.

---

# 27. Provider ranking

Recommended route order:

```
1 explicit user pin
2 required contract/features
3 permission eligibility
4 compatibility
5 health
6 privacy/locality preference
7 current resource budget
8 latency/cost policy
9 quality ranking
10 fallback priority
```

A “best model” provider that violates a privacy or permission constraint is not eligible.

---

# 28. Configuration ownership

Provider configuration is separate from identity.

Each provider has:

```
provider_config
credential_ref
user_preferences
runtime_state
```

Credential changes should use reauthentication.

Endpoint/model/device changes should use reconfiguration.

Neither should delete XiaoYu identity/history.

This mirrors Home Assistant's mature reauth/reconfigure model.

---

# 29. Upgrade and rollback

Never upgrade the only provider in-place without rollback metadata.

Recommended:

```
current_version
candidate_version
last_known_good
```

Upgrade flow:

- install candidate side-by-side;
- verify artifact hash/signature;
- run conformance;
- warm/test;
- switch;
- retain old version until observation passes.

For in-process Python providers, process restart may still be the safest rollback boundary.

---

# 30. Capability-specific fallback semantics

Fallback is not always semantically safe.

## Safe-ish fallback

- embeddings;
- reranker;
- vision interpretation;
- non-identity LLM response before output begins;
- TTS before audio playback begins.

## Needs care

- mid-stream LLM after text already emitted;
- TTS after partial audio played;
- ASR mid-utterance;
- scheduler handling a durable timer.

## Usually no automatic fallback

- memory authority mutation;
- external financial/social action;
- permission decision;
- identity mutation.

The router needs per-contract fallback policy.

---

# 31. Mid-stream switching

LiteLLM's stream behavior provides a good warning:

once output has been delivered, replay/fallback can duplicate or contradict prior output.

For XiaoYu:

## Text
If no token reached the user -> fallback may restart.

If text already reached user -> prefer fail/degraded state rather than silently regenerate incompatible output unless the protocol explicitly supports continuation.

## TTS
If no audio played -> switch provider freely.

If audio already played -> cancel current utterance; do not replay from start automatically.

## ASR
Do not merge transcripts from incompatible recognizers unless timestamps/segments support deterministic reconciliation.

---

# 32. Degradation rather than binary failure

A provider may lose only an advanced feature.

Example TTS:

```
READY:
  streaming=true
  cloning=true

DEGRADED:
  streaming=true
  cloning=false
```

The capability registry should route based on required features, not just provider up/down.

---

# 33. Plugin quality scale

Borrow Home Assistant's tier concept.

Suggested XiaoYu provider levels:

## EXPERIMENTAL
works in dev; no stability promise

## BASIC
manifest + conformance + clean stop

## RELIABLE
error handling + health + reload + >95% adapter test coverage target

## PRODUCT
reauth/reconfigure + diagnostics + resource telemetry + recovery + compatibility matrix

## TRUSTED
signed/pinned supply chain + security review + long soak + no unresolved critical negatives

Core production routes should prefer PRODUCT/TRUSTED providers.

---

# 34. Security model

Replaceability increases supply-chain risk.

Every provider needs:

- identity;
- source;
- exact version;
- artifact hash;
- permissions;
- data classes;
- isolation class;
- trust level.

Third-party modules get least privilege.

Browser extension architecture demonstrates why optional runtime permissions are superior to requesting broad access upfront.

Wasm/WIT demonstrates why capability-based imports are stronger than trusting plugin code to “behave.”

---

# 35. Observability

Standard fields for every provider invocation:

```
capability
provider_id
implementation_version
contract_version
request_id
latency
result
failure_class
fallback_from
fallback_to
resource snapshot
```

Map later to OpenTelemetry GenAI conventions where applicable.

OpenTelemetry now distinguishes areas including:

- agent;
- memory;
- retrieval;
- streaming;
- tools;
- MCP.

Do not invent incompatible telemetry names unless XiaoYu needs data not represented there.

---

# 36. The cost of modularity

Benefits:

- independent upgrades;
- fault isolation;
- A/B testing;
- fallback;
- model independence;
- hardware evolution;
- clearer tests;
- reduced rewrite risk.

Costs:

- more interfaces;
- serialization;
- lifecycle complexity;
- compatibility matrix;
- versioning;
- routing bugs;
- observability burden;
- state migration complexity.

Therefore:

> only abstract a boundary when replacement/failure/isolation value exceeds the coordination cost.

---

# 37. The "two implementation" rule

Default:

Do not create a generalized contract until at least one is true:

1. two real implementations exist or are imminent;
2. isolation is independently valuable;
3. security boundary requires it;
4. external ecosystem integration requires it.

Immediate contracts justified now:

- LLM provider
- vision provider
- vision capture
- TTS
- ASR
- VAD
- surface/messaging
- tool/MCP
- retrieval
- body adapter

Later contracts:

- sync backend
- general computer-use backend
- third-party sandbox

Do not abstract every internal helper.

---

# 38. Final XiaoYu modular architecture

```
                         XiaoYu Kernel
┌──────────────────────────────────────────────────────────┐
│ Identity Authority                                       │
│ Event Ledger                                              │
│ Memory / Temporal Truth                                   │
│ Canonical Turn                                            │
│ Purpose                                                   │
│ Authorization                                             │
│ External Effect Ledger                                    │
│ Capability Registry + Router                              │
└──────────────────────────┬───────────────────────────────┘
                           │
          Capability Contract / Negotiation
                           │
     ┌─────────────┬───────┼────────┬────────────┐
     ▼             ▼       ▼        ▼            ▼
Reasoning       Retrieval Vision   Voice       Surfaces
remote/inproc   inproc    sidecar  sidecar     inproc/sidecar
     │             │       │        │            │
DeepSeek        lexical  SeeNow   Qwen3-TTS     QQ
Qwen            BGE      DXcam    GPT-SoVITS    Desktop
Future          Future   Future   Future        Mobile
                           │
                           ▼
                         Action
                   MCP / native / future CU
```

Future third-party small capability modules may run as Wasm.

---

# 39. Final verdict

Making **implementation-facing modules replaceable** is a major net positive for XiaoYu.

Making **everything** a plugin is not.

The correct target is:

> **Stable semantic kernel + versioned capability contracts + replaceable providers + risk-tiered isolation.**

That structure gives XiaoYu:

- personality continuity;
- capability continuity;
- provider independence;
- hardware independence;
- graceful degradation;
- easier adoption of future external projects;
- controlled plugin security.

The most important practical rule is:

> **State stays with XiaoYu; capability implementations come and go.**

---

# High-value external references

- Visual Studio Code Extension Host / Activation Events
- Home Assistant Integration Quality Scale / unload / reauth / reconfigure
- HashiCorp go-plugin
- Python Packaging plugin entry points
- pluggy
- MCP lifecycle, versioning and capability negotiation
- WebAssembly Component Model / WIT worlds
- Extism
- WebExtension runtime permissions
- LiteLLM Router reliability and fallback model
- gRPC Health Checking
- Semantic Versioning
- Pact contract testing
- OpenTelemetry GenAI semantic conventions
- Windows Job Objects / Named Pipes


---

# 40. Final saturation pass: failure modes and anti-patterns

The final survey pass did not reveal a better top-level architecture. It mainly exposed failure modes that confirm the need for the design above.

## Python in-process hot reload is not a reliable product upgrade mechanism

Python's own `importlib.reload()` documentation warns that:

- old object references are not rebound automatically;
- old class instances keep old method definitions;
- extension modules may not support repeated initialization;
- module dictionaries retain old names/state;
- reload is not thread-safe.

Therefore:

**Do not promise true hot-upgrade for in-process Python providers.**

Use:

- restart Core for trusted in-process provider upgrades;
- sidecar drain-and-switch for heavy/runtime providers;
- request-level routing for remote/stateless providers.

## Runtime permissions should be just-in-time

Browser extension permission systems reinforce that optional capabilities should be requested only when needed and should survive denial gracefully.

For XiaoYu:

- installing a Vision provider does not imply screen permission;
- installing an ASR provider does not imply microphone permission;
- installing a Tool provider does not imply filesystem/network permission.

Installation, capability availability and permission are separate states.

## Integration quality is more than “it loads”

Home Assistant's quality model confirms that mature integrations need:

- setup;
- unload/reload;
- reauthentication;
- reconfiguration;
- diagnostics;
- failure handling;
- tests.

Therefore XiaoYu's provider quality tier should evaluate lifecycle and product recoverability, not only capability correctness.

## Provider upgrade should not destroy configuration or identity state

Home Assistant's reauthentication/reconfiguration flows preserve the existing integration identity while credentials/endpoints change.

XiaoYu should follow the same principle:

```
provider credentials change
provider endpoint changes
model changes
device changes
```

must not force:

```
delete provider identity
recreate XiaoYu state
rebuild personal history
```

## Permissions should be explicit capabilities

WebAssembly WIT worlds and Extism manifests show a stronger model than “plugin runs and promises not to touch things”:

- network can be absent;
- filesystem can be absent;
- secret access can be absent;
- allowed hosts/paths can be narrow;
- memory/execution can be bounded.

This is the preferred future model for third-party XiaoYu extensions.

## Sidecar ownership must be OS-enforced where practical

On Windows, Job Objects with kill-on-close semantics provide a robust process-tree cleanup mechanism.

For XiaoYu heavy providers:

```
Core owns job
  └─ Vision/TTS/ASR sidecar
      └─ child workers
```

Closing/disabling the capability should terminate the whole owned process tree.

## Local IPC should avoid unnecessary network exposure

For a Windows desktop companion:

- child stdio is simplest for one-owner sidecars;
- named pipes are appropriate for persistent duplex local IPC;
- named-pipe ACLs should restrict callers;
- localhost TCP should be used only when protocol/library constraints justify it.

## Contract tests are more important than framework choice

Pact-style contract testing reinforces a general rule:

> each provider should be independently verifiable against what the Kernel actually consumes.

XiaoYu does not need Pact itself for every internal interface, but it does need provider conformance tests with concrete examples and compatibility results.

## Version everything that evolves independently

OSGi's long experience with versioned bundles/services and SemVer's requirement to declare a clear public API support the same conclusion:

XiaoYu should separately version:

- capability contract;
- provider implementation;
- provider state schema;
- model artifact/revision;
- manifest schema.

Do not collapse all of these into “plugin version”.

---

# 41. Saturation conclusion

Across the final passes, mature systems from different domains converged on the same architecture:

- VS Code: lazy activation and extension-host isolation;
- Home Assistant: declarative manifests, dependencies, unload/reload, reauth/reconfigure, quality tiers;
- HashiCorp go-plugin: subprocess/RPC fault isolation;
- MCP: version and capability negotiation;
- WebAssembly Component Model: explicit imported/exported capabilities;
- Extism: sandbox limits and host-controlled permissions;
- WebExtensions: optional runtime permissions;
- LiteLLM: centralized retry/fallback/cooldown routing;
- gRPC: explicit health semantics;
- SemVer/OSGi: independently versioned contracts;
- Pact: provider/consumer contract verification;
- OpenTelemetry: standardized observability;
- Windows Job Objects/Named Pipes: local process ownership and IPC.

Further external searching is now expected to produce mostly alternate implementations of these same mechanisms.

The architecture is therefore considered **saturated at the design level**.

Future research should be empirical:

1. implement a minimal Capability Registry;
2. wrap two real providers behind one contract;
3. measure overhead;
4. test failure isolation;
5. test replacement/rollback;
6. only then generalize the next interface.
