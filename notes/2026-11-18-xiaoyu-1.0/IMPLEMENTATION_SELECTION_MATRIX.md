# XiaoYu Implementation Selection Matrix

**Date:** 2026-11-18  
**Purpose:** turn the saturated architecture survey into concrete implementation choices.  
**Rule:** prefer the smallest component that preserves XiaoYu's own identity/memory authority. External systems may be libraries, sidecars, evaluators or later-stage infrastructure, but not a second brain.

---

# 1. Core runtime

## Recommendation

**KEEP: XiaoYu's existing Python Core.**

Responsibilities stay local:

- identity authority
- event ledger
- memory authority
- profile projection
- canonical turn
- provider routing
- tool runtime
- freshness
- purpose state
- permission gate
- delivery ledger

## Do not migrate to

- Letta as runtime host
- SurfCore / DSH as runtime host
- Open-LLM-VTuber as backend host

Reason: all three would duplicate identity/history/runtime ownership and create a migration whose risk exceeds the value of their peripheral features.

---

# 2. Memory authority

## Recommendation

**KEEP: SQLite + event-sourced provenance as source of truth.**

Extend it rather than replacing it.

Add derived tables:

```
events
memories
temporal_facts
profile_projection
relationships
purpose_events
skills
delivery_receipts
permission_grants
```

## Why not Mem0 as authority

Mem0 is mature and Apache-2.0, but its default OSS architecture adds a vector store plus a separate SQLite history store and defaults to external LLM/embedding providers unless configured otherwise.

That is useful for drop-in application memory, but XiaoYu already has stronger provenance and identity semantics.

Use Mem0 as:

- design reference
- benchmark comparison

Do not use it as canonical truth.

## Why not Hindsight as authority

Hindsight has strong consolidation / learned-memory ideas and MIT licensing, but current architecture centers PostgreSQL/pgvector; even local development uses embedded PostgreSQL.

That is too much storage/runtime infrastructure for a single-user Windows companion whose authoritative state already fits SQLite.

Use Hindsight ideas for:

- consolidation jobs
- reflective memory formation
- maintenance audits

## Why not Graphiti as authority

Graphiti is excellent for temporal knowledge graphs, but current supported production backends require Neo4j/FalkorDB/Neptune; Kuzu is deprecated. FalkorDB embedded mode also requires newer Python than current XiaoYu baseline.

Graphiti ingestion also expects structured-output-capable LLMs and adds graph-database lifecycle complexity.

Therefore:

**Do not install Graphiti into 1.0.**

For 1.x, borrow its bi-temporal model or optionally build a derived graph projection from XiaoYu's own authoritative events.

## Why not Letta as authority

Letta is Apache-2.0 and has very mature stateful-agent concepts, including a git-backed memory filesystem and background dreaming. But it is an entire agent harness with its own identity/memory semantics.

Use Letta ideas for:

- memory doctor
- dreaming/consolidation
- portable agent state
- skill maintenance

Do not migrate Core.

---

# 3. Memory retrieval

## Recommendation

**KEEP current local retrieval worker as baseline.**

Use:

- lexical / source-aware filters
- local semantic embedding
- exact authority filtering before ranking
- outcome-gated reranking only when justified

Do not add a second vector DB just because one is available.

## Hot-path policy

- no authorized documents -> no embedding model
- cold load once
- reuse worker across nearby turns
- idle unload
- data-version invalidation
- exact source/audience/trust filtering before semantic ranking

This fits the current XiaoYu architecture better than Mem0's default Qdrant or Hindsight's PostgreSQL.

---

# 4. Temporal memory

## Recommendation

**Implement bi-temporal semantics in XiaoYu's own schema first.**

Required fields:

```
recorded_at
event_time
valid_from
valid_to
supersedes
contradicts
status
```

Do not introduce a graph database until query patterns prove SQLite projections insufficient.

## Escalation criterion

Only consider Graphiti/FalkorDB if real product queries require multi-hop temporal graph traversal that cannot be implemented cleanly with current relational projections.

---

# 5. User profile

## Recommendation

Maintain a **derived profile projection** separate from raw memories.

Profile sections:

- stable preferences
- context-specific preferences
- habits
- important people
- active projects
- recurring routines
- interaction style
- proactivity preferences

Profile writes must point back to evidence.

Use background consolidation only to propose changes; critical changes remain reviewable.

---

# 6. Purpose / reminders / proactive events

## XiaoYu 1.0

Use a **local SQLite state machine** plus a lightweight persistent scheduler.

Lifecycle:

```
candidate
confirmed
scheduled
active
completed
cancelled
expired
superseded
```

Each event stores:

- event_id
- source event
- due window
- cancellation condition
- retry rule
- delivery policy
- last state change
- receipt

For exact-time scheduling, APScheduler's persistent datastore model is sufficient for 1.0-scale jobs, provided identifiers and serialization are explicit.

## XiaoYu 1.x

For workflows that last hours/days and include external side effects, adopt a real durable-execution engine.

### Preferred candidate: Temporal

Reasons:

- MIT SDK
- mature Python support
- cancellation
- timers
- schedules
- retries
- versioning
- external events
- local single-binary development server
- explicit idempotency guidance
- strong recovery model

### Alternative: Microsoft Durable Task

Technically strong and supports Python 3.11+, durable timers, external events, suspend/resume and retries.

But the current Python path centers Azure Durable Task Scheduler / emulator, so it is less aligned with a local-first personal desktop product.

**Decision:** Temporal is the stronger 1.x candidate; do not add either to 1.0 unless local purpose jobs prove insufficient.

---

# 7. External side effects

Every external action gets an effect record:

```
effect_id
intent_id
idempotency_key
target
request
started_at
external_receipt
verified_at
postcondition
final_state
```

Rules:

- retries must reuse the same logical idempotency key
- never mark success from model narration
- verify postcondition independently
- if provider lacks idempotency, query state before retry

This prevents duplicate QQ messages, duplicate posts, duplicate bookings and repeated destructive actions after crashes.

---

# 8. Authorization

## 1.0 recommendation

**Do not introduce a policy server.**

Implement a small deterministic typed policy layer in Python.

Input:

```
principal
surface
action
resource
audience
risk_tier
reversibility
standing_grants
time
amount
```

Output:

```
ALLOW
ASK
DENY
```

Risk tiers:

- T0 Observe
- T1 Local reversible
- T2 Owner-state mutation
- T3 External/irreversible

LLM may propose an action but cannot override the policy result.

## 1.x candidate: Cedar

Cedar is Apache-2.0, purpose-built for fine-grained authorization, supports RBAC/ABAC, schema validation and deterministic evaluation.

Why not add immediately:

- the primary implementation is Rust
- Python integrations are not yet as first-party/mature as the core
- current single-owner product does not justify another policy runtime yet

Cedar is preferable to OpenFGA/OPA for future local policy embedding because XiaoYu needs per-request attribute policy more than Internet-scale relationship authorization.

## Why not OpenFGA now

OpenFGA is excellent for ReBAC/ABAC and large multi-user systems, but it runs as a service/database and is designed for far more authorization topology than XiaoYu 1.0 needs.

Revisit only if XiaoYu grows into household/group/multi-tenant sharing.

## Why not OPA now

OPA is powerful and mature but Rego + OPA/Wasm introduces unnecessary policy infrastructure for a single-user companion.

Useful later for organization/enterprise deployment, not 1.0.

---

# 9. MCP security

MCP tools are capabilities, not trusted plugins.

Required registry metadata:

```
server_id
source
version
manifest_hash
transport
declared_permissions
actual_allowed_resources
trust_level
installed_at
last_verified
```

Rules:

- explicit allowlist
- pin version/source where possible
- treat descriptions/tool output as untrusted
- restrict filesystem/network scope
- log stdio servers
- never pass tokens through between resources
- resource/audience-bind credentials
- require stronger auth for dangerous operations

This follows the 2026 MCP authorization/security direction.

---

# 10. Vision capture

## Preferred 1.0 strategy

**Use dsh-see-now as the algorithmic substrate, but not as XiaoYu's agent host.**

Two implementation options:

### Option A — Node sidecar using dsh-see-now capture/pipeline

Pros:

- fastest integration
- preserves upstream implementation
- frame-change scoring already solved
- storyboard packing
- region/watch semantics
- Apache-2.0

Cons:

- extra Node process/runtime
- cross-process protocol
- packaging complexity

### Option B — Python-native port using DXcam

DXcam is MIT and uses Windows Desktop Duplication API.

Pros:

- single language/runtime
- fast Windows capture
- easier packaging with XiaoYu Python

Cons:

- we would have to reimplement/test the change detector, queueing and storyboard logic
- greater long-term maintenance burden

## Decision

**Start with Option A.**

Treat dsh-see-now as a bounded local vision sidecar with a narrow JSON/pipe contract.

Only port to Python if measured sidecar overhead or packaging becomes a material problem.

Do not rewrite the algorithm preemptively.

---

# 11. Vision model routing

Text provider and vision provider remain separate.

```
text:
  DeepSeek API
  fallback Qwen

vision:
  independent provider
```

Vision input must be wrapped as observation, not instruction.

Before context injection:

- strip/label OCR instructions
- attach source = screen/camera
- mark trust = untrusted observation
- apply privacy filters
- enforce audience

Raw frame retention defaults to short-lived/transient.

---

# 12. Ambient capture

Do not adopt screenpipe as the default recorder.

Screenpipe demonstrates useful capabilities:

- accessibility tree
- OCR
- audio transcription
- app switches
- local-first history

but current documented resource range is much higher than XiaoYu needs for default operation, and it is source-available rather than a simple permissive embedding dependency.

Use it as:

- architectural reference
- optional future data source
- benchmark/comparison

Default XiaoYu perception remains event-driven bounded watch.

---

# 13. ASR / VAD

## Preferred 1.0 stack

### sherpa-onnx runtime

Apache-2.0, local/offline, Windows/Linux/macOS/mobile support, and exposes:

- ASR
- TTS
- VAD
- speaker features
- language ID

### SenseVoiceSmall model path

Strong Chinese/multilingual fit and already integrated through sherpa-onnx ecosystems.

Important: code and model weights have different licenses; model-card terms must be retained in release inventory.

### VAD

Silero VAD is MIT and is a mature default.

## Why this stack

It is more compact and cross-platform than making full FunASR the mandatory runtime for every device.

---

# 14. TTS

## Preferred candidate: Qwen3-TTS 0.6B

Reasons:

- Apache-2.0 model
- streaming
- Chinese + multilingual
- 3-second voice cloning
- smaller 0.6B option
- clean modern Python package
- API path also exists
- easier long-term licensing story than collecting unrelated voice checkpoints

## Deployment choice

Run TTS as an **isolated voice service/sidecar**, not inside the Core process.

Why:

- TTS dependencies evolve quickly
- Qwen3-TTS currently recommends a newer isolated Python environment
- GPU memory can be reclaimed independently
- allows swapping API/local implementations

## Alternative: GPT-SoVITS

Pros:

- MIT code
- excellent Chinese ecosystem
- mature cloning/fine-tuning workflow

Cons:

- more moving parts
- larger model bundles in common distributions
- some checkpoint formats rely on pickle-based PyTorch artifacts
- more training/data-management complexity

Use GPT-SoVITS only if voice-character quality beats Qwen3-TTS materially in XiaoYu-specific listening tests.

## Alternative: CosyVoice

Strong Apache-2.0 project and excellent Chinese TTS, but Qwen3-TTS currently provides a simpler small-model/streaming/voice-clone fit for first integration.

## Decision

1. Qwen3-TTS 0.6B candidate
2. GPT-SoVITS comparison
3. CosyVoice comparison

Final choice must be made by same-hardware latency/quality tests, not repo reputation.

---

# 15. Voice conversation orchestration

Borrow Open-LLM-VTuber's proven pattern:

```
LLM stream
↓
sentence segmenter
↓
concurrent TTS producers
↓
ordered playback queue
↓
Live2D mouth/expression
```

Requirements:

- faster first sentence
- multiple TTS segments generated concurrently
- ordered playback
- barge-in
- cancel unsent audio
- stop unnecessary LLM continuation after interruption
- VAD / echo handling
- TTS failures isolated per segment

Do not copy its conversation/memory authority.

---

# 16. Live2D / body

Keep current XiaoYu desktop pet.

Define a body-state interface:

```
speaking
listening
thinking
attention_target
expression
gesture
idle_mode
visibility
```

No identity or conversation state lives inside the avatar layer.

This keeps future VRM/Quest/web bodies replaceable.

---

# 17. Cross-device architecture

## 1.0

Single authoritative Core host, multiple thin surfaces.

This avoids premature multi-master state conflicts.

## 1.x

Replicate deltas:

- identity version
- profile projection
- memory changes
- purpose state
- delivery receipts
- skill metadata

Do not replicate raw caches/embeddings by default.

### CRDT candidates

Automerge is MIT and mature for JSON-like concurrent state.

Any/any-sync demonstrates local-first + E2EE + automatic merge at larger system scope.

## Decision

Do not adopt a CRDT database before multi-device offline editing exists.

Start with event/delta replication. If true multi-master offline writes become a requirement, evaluate Automerge or any-sync then.

---

# 18. Portable memory

Implement an export adapter toward the emerging Portable Memory proposal.

Do not make its current draft format XiaoYu's internal schema.

Good concepts to borrow:

- JSONL bundle
- manifest
- checksums
- tombstones
- merge protocol
- deletion-propagation conformance

XiaoYu's native export remains richer and authoritative.

---

# 19. Observability

## 1.0

Keep lightweight local structured events:

- model call
- retrieval
- tool call
- permission result
- external receipt
- verifier
- memory write
- purpose transition

## 1.x

Map these events to OpenTelemetry GenAI semantic conventions.

OTel now has defined operation classes such as:

- invoke_agent
- execute_tool
- retrieval
- embeddings
- generate_content
- invoke_workflow

Do not build a custom observability protocol if standard spans can represent it.

Important:

**Trace != Evidence.**

External receipts and postcondition verification remain separate from telemetry.

---

# 20. UI / operator console

Final settings surface should expose:

## Identity
- current identity version
- persona changes
- provider independence

## Memory
- active memories
- source/provenance
- superseded/archived
- edit/correct/delete
- profile projection

## Proactivity
- normal/off
- quiet hours
- daily cap
- per-category controls
- pending purposes

## Vision
- OFF / peek / bounded watch / ambient
- current capture indicator
- retention
- provider disclosure

## Voice
- voice
- speed
- barge-in
- local/API
- microphone state

## Permissions
- standing grants
- recent asks/denies
- external effects

## Resource
- RAM
- VRAM
- CPU
- API spend
- current workers

Market products already show that proactive controls, quiet hours, visible memory and voice settings are baseline UX, not advanced diagnostics.

---

# 21. Proactivity implementation

## Do not implement

```
timer -> ask LLM whether to message
```

## Implement

```
event/purpose candidate
↓
still valid?
↓
cancelled/superseded?
↓
user-state context
↓
expected value
↓
interruption cost
↓
confidence
↓
risk/permission
↓
delivery dedupe
↓
WAIT / ASK / SPEAK / ACT
```

WAIT is the default.

Evaluation must be base-rate-aware. TactBench demonstrates why balanced benchmark precision can collapse in a real environment where quiet moments dominate.

---

# 22. Proactivity UX

Borrow good product behavior from Kindroid, without copying its architecture:

- quiet hours
- reach-out frequency
- backoff when unanswered
- exact-time requested reminders
- user-requested space
- do not interrupt active conversation
- visible “why I reached out” explanation

XiaoYu should go one step further by making purpose/event state auditable.

---

# 23. Evaluation stack

## Identity
- long-horizon persona probes
- provider switch
- surface switch
- restart
- trajectory continuity

## Memory
- LoCoMo
- LongMemEval-V2 style experienced-agent tasks
- Memora mutation/forgetting
- correction/supersession
- stale-memory penalty

## Proactivity
- ProEvent event creation/cancellation
- AgentAbstain paired act/abstain
- TactBench base-rate simulation
- duplicate delivery tests

## Action
- OSWorld-style postcondition
- MyPCBench-style cross-app personalization
- irreversible-action abstention
- permission-scope tests

## Skills
- SkillsBench-style no-skill vs curated-skill vs self-generated
- skill transfer after provider switch
- stale skill / failed verifier
- rollback

## Product
- crash after external effect
- restart during watch
- offline provider failure
- backup/restore
- memory deletion propagation
- audience leak negative tests

---

# 24. Strong conclusions from external evidence

## Proactivity

ProEvent reports current agents frequently overact and struggle with cancellation; even strong models show substantial redundant assistance and poor cancellation recall.

AgentAbstain finds abstention ability largely independent of task-solving strength.

Therefore XiaoYu cannot outsource “should I act?” entirely to the LLM.

## Skills

SkillsBench reports curated skills improve average task pass rate substantially, but self-generated skills give no average benefit and some tasks regress.

Therefore:

**XiaoYu may generate skill candidates, but only verified skills enter the SkillBank.**

## Personal computer use

MyPCBench shows cross-app personalized tasks remain much harder than ordinary computer-use tasks; failures include skipped apps, premature completion and hallucinated persona data.

Therefore computer use must query personal state through XiaoYu's authority layer rather than inventing user-specific details.

---

# 25. Recommended implementation order

## Phase A — freeze Core

1. current identity/memory/turn/provider APIs
2. temporal fact schema basics
3. profile projection
4. permission gate interface
5. purpose/event table

## Phase B — finish 1.0 surfaces

6. QQ private E2E
7. dsh-see-now sidecar
8. vision provider adapter
9. sherpa-onnx + VAD
10. TTS sidecar
11. streaming voice queue
12. Live2D body-state contract

## Phase C — product reliability

13. external-effect receipt
14. idempotency
15. startup/recovery
16. backup/restore
17. settings/status UI
18. memory UI

## Phase D — 1.x

19. bi-temporal full semantics
20. audience scope
21. SkillBank
22. durable workflow runtime
23. cross-device delta sync
24. OpenTelemetry mapping
25. memory portability adapter

---

# 26. Rejected complexity for 1.0

Do not add:

- Neo4j
- FalkorDB
- PostgreSQL
- Qdrant
- Redis
- OpenFGA server
- OPA server
- Temporal server
- Durable Task Scheduler
- CRDT database
- always-on full screenpipe recorder
- second agent harness

unless a measured blocker specifically requires it.

The purpose of external research is to remove work, not to turn XiaoYu into infrastructure archaeology.

---

# 27. Final recommended stack

```
Core
  Python 3.11
  XiaoYu-owned SQLite authority

Memory
  SQLite event ledger
  temporal facts/projections
  current local semantic retrieval worker

Text models
  DeepSeek API
  Qwen fallback

Vision
  dsh-see-now Node sidecar
  independent vision provider
  optional DXcam native path later

Voice input
  sherpa-onnx
  SenseVoiceSmall candidate
  Silero VAD

Voice output
  Qwen3-TTS 0.6B sidecar candidate
  GPT-SoVITS comparison candidate

Avatar
  existing Live2D desktop pet
  body-state adapter

Purpose 1.0
  SQLite state machine
  lightweight persistent scheduling

Purpose 1.x
  Temporal candidate

Authorization 1.0
  typed deterministic Python policy gate

Authorization 1.x
  Cedar candidate if complexity requires it

Sync 1.0
  single authoritative Core + thin surfaces

Sync 1.x
  event/delta sync
  CRDT only if true offline multi-master appears

Observability
  structured local events
  OpenTelemetry GenAI mapping later

Export
  native verified identity bundle
  Portable Memory adapter later
```

---

# 28. Guiding rule

> Use external projects for capabilities that are already solved. Keep XiaoYu's identity, memory authority, purpose semantics and verification under XiaoYu's control.

This is the implementation-level version of:

> External projects may give XiaoYu eyes, voice, hands and infrastructure. They must not become a second XiaoYu.


---

# 29. Final voice/runtime override after ecosystem source mining

This section supersedes the earlier recommendation to build XiaoYu's streaming voice orchestration manually as the first implementation.

## Primary Voice Session Engine spike: Pipecat

Pipecat should be evaluated first because the current upstream already provides:

- Python 3.11+ support;
- local microphone/speaker transport;
- VAD and turn strategies;
- local smart-turn models;
- interruption/barge-in handling;
- cancellation frames;
- TTS service abstractions;
- scripted interruption evaluation;
- broad STT/TTS/LLM provider integration.

Recommended layering:

```
XiaoYu Core
  canonical turn
  memory/context
  provider policy
  identity
  permissions
        ↓
XiaoYu Voice Adapter
        ↓
Pipecat Voice Session
  LocalAudioTransport
  ASR adapter
  LLM stream bridge
  Qwen3-TTS / GPT-SoVITS adapter
  turn/interruption pipeline
        ↓
XiaoYu Body State Adapter
```

Pipecat must not become XiaoYu's identity or conversation authority.

## Fallback decision

If a same-machine spike shows material:

- latency overhead;
- dependency conflicts;
- excessive RAM/CPU;
- hard-to-control canonical-turn semantics;

then implement the previously designed minimal custom pipeline.

Do not build both in parallel before measuring.

## Future remote/mobile voice

LiveKit Agents becomes the stronger candidate only when XiaoYu needs:

- WebRTC/mobile realtime sessions;
- multi-user rooms;
- telephony;
- remote media transport;
- distributed realtime voice.

---

# 30. Principal resolution implementation candidate

For future shared-mic/device use, prefer existing speaker-embedding infrastructure over training a custom model.

Sherpa-ONNX provides:

- speaker embedding extraction;
- enrollment;
- search/identification;
- verification;
- diarization support.

Use it as one evidence source inside Principal Resolution.

Do not let speaker score directly unlock owner-private memory or high-risk permissions without stronger session/device authentication.
