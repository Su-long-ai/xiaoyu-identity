# XiaoYu 1.0 / 1.x Execution Backlog

**Date:** 2026-11-18  
**Purpose:** convert the research, architecture decisions, implementation matrix and acceptance plan into dependency-ordered work.  
**Authority note:** local workspace remains fresher than this GitHub snapshot. Reconcile with local code before implementation.

---

# 0. Global rule

Every task below must satisfy:

```
smallest viable change
→ deterministic tests first
→ product E2E
→ acceptance gate
→ freeze
```

Do not open a new subsystem if an existing one can be extended safely.

---

# 1. Critical path to XiaoYu 1.0

```
A. DECADE100 closure
        ↓
B. Core interface freeze
        ↓
C. Temporal/profile basics
        ↓
D. Purpose + deterministic silence/cancellation
        ↓
E. Permission/effect foundation
        ↓
F. QQ private cross-surface E2E
        ↓
G. Vision bounded-watch path
        ↓
H. Voice streaming path
        ↓
I. Recovery / backup / onboarding / status
        ↓
J. Full acceptance suite
        ↓
XIAOYU_1_0_DONE
```

Some tracks can run in parallel, but this is the logical dependency chain.

---

# A. DECADE100 Closure

**Priority:** P0  
**Blocks 1.0:** YES

## Goal

Finish the current prospective generalization decision without creating another benchmark generation.

## Inputs

- V5 baseline
- V8 candidate
- frozen DECADE100 pool
- frozen prompt/judging/source rules
- semantic substrate already validated in current local state

## Work

- complete runtime payload preflight
- complete aggregate cost preflight
- execute full paired evaluation under frozen rules
- dual judge / source adjudication
- generate final promotion decision

## Stop rule

- V8 wins -> promote and freeze
- tie -> retain/freeze, stop benchmark optimization
- loss -> at most one bounded repair against a clearly identified cluster

## Explicit non-goal

No V9/V10 ladder just because a new benchmark weakness is interesting.

---

# B. Core Interface Freeze

**Priority:** P0  
**Blocks 1.0:** YES

## Freeze contracts

- identity access
- memory authority mutation
- memory retrieval
- canonical turn
- provider dispatch
- tool dispatch
- freshness
- persistence
- surface adapter

## Required document

Create a compact interface contract describing what surface/capability modules may and may not own.

## Rule

Future:

- Vision
- Voice
- QQ
- Mobile
- Bilibili
- Computer Use

may call Core, but cannot create a second identity/memory truth.

---

# C. Temporal Facts Basic

**Priority:** P0  
**Blocks 1.0:** BASIC VERSION

## Goal

Stop treating every memory as an eternal timeless fact.

## Minimal 1.0 fields

- source_event
- recorded_at
- valid_from optional
- valid_to optional
- status
- supersedes

No graph database.

## Reuse

Extend current correction/retraction path.

## Tests

- initial fact
- correction
- retraction
- backdated change
- current truth
- historical truth

## Gate

See `VALIDATION_AND_ACCEPTANCE_PLAN.md#3`.

---

# D. Profile Projection Basic

**Priority:** P0  
**Blocks 1.0:** YES

## Goal

Avoid recomputing stable user state from arbitrary top-k memories every turn.

## First profile fields

- stable preferences
- important people
- active long-term projects
- interaction style
- proactivity settings

## Rules

- projection points to evidence
- projection is rebuildable
- no unsupported inference
- context-specific preference can remain UNKNOWN in 1.0

## Tests

- source correction updates projection
- deletion removes projection
- projection rebuild is deterministic
- provider switch does not alter projection

---

# E. Purpose State Machine

**Priority:** P0  
**Blocks 1.0:** YES

## Minimal states

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

## Required semantics

- exact source
- due window
- cancellation
- reschedule
- completion
- duplicate suppression
- quiet hours
- WAIT decision

## Do not implement

Periodic free-form “do you feel like messaging?” loop.

## Gate

- explicit cancellation suite 100%
- duplicate notification 0
- quiet-hour violations 0 except explicit critical class

---

# F. Permission Gate

**Priority:** P0  
**Blocks 1.0:** YES

## Interface

```
authorize(principal, surface, action, resource, context)
→ ALLOW | ASK | DENY
```

## First risk tiers

- T0 observe
- T1 local reversible
- T2 owner-state mutation
- T3 external/irreversible

## Rule

The LLM proposes intent.

Deterministic code decides permission.

## Tests

- expired permission
- wrong target
- wrong surface
- high-risk variant
- external third party
- DENY means no tool call

---

# G. External Effect Ledger

**Priority:** P0  
**Blocks 1.0:** YES for actions with side effects

## Implement

- effect id
- intent id
- idempotency key
- dispatch state
- receipt
- verifier result

## Crash tests

- before dispatch
- after dispatch
- before receipt persistence
- before verifier
- after verifier

## Rule

Unknown dispatch state -> reconcile, never blind retry.

---

# H. QQ Private Cross-Surface E2E

**Priority:** P0  
**Blocks 1.0:** YES

## Scope

Private owner chat only.

Group chat remains later until audience-scoped memory exists.

## Required flows

- QQ -> Desktop continuation
- Desktop -> QQ continuation
- task completion delivered once
- reconnect
- stale turn race
- provider fallback
- restart

## Gate

- one identity
- no duplicate memory
- no duplicate delivery
- no stale persistence

---

# I. Vision Sidecar Spike

**Priority:** P1-high  
**Blocks 1.0:** bounded vision YES

## Preferred implementation

dsh-see-now capture/pipeline as Node sidecar.

## Sidecar contract

Commands:

```
status
peek
watch
stop
region
shutdown
```

Responses contain:

- timestamp range
- frame metadata
- PNG/storyboard handle or bytes
- capture mode
- source
- no model instruction semantics

## Security wrapper

All outputs become:

```
UNTRUSTED_OBSERVATION
```

## Measurements

- sidecar startup
- idle RAM
- CPU
- capture CPU
- selected frames / raw frames
- process cleanup

## Gate

See Vision + Multimodal Injection sections in acceptance plan.

---

# J. Vision Provider Adapter

**Priority:** P1-high  
**Blocks 1.0:** YES if vision is included in 1.0 target

## Design

Separate from text provider.

## Required

- independent config
- explicit data disclosure logging
- image size/token budget
- retry/fallback
- timeout
- no raw frame persistence by default

## Test

A broken Vision provider must not break normal text chat.

---

# K. Voice Input Spike

**Priority:** P1-high  
**Blocks 1.0:** basic voice YES

## Preferred stack

- sherpa-onnx
- SenseVoice candidate
- Silero VAD

## Required

- push-to-talk first
- VAD-assisted hands-free second
- no speech -> no canonical turn
- final ASR text enters normal turn runtime

## Gate

- Chinese
- mixed Chinese/English
- silence
- background media
- interruption

---

# L. TTS Benchmark

**Priority:** P1-high  
**Blocks 1.0:** model selection YES

## Candidates

1. Qwen3-TTS 0.6B
2. GPT-SoVITS
3. CosyVoice optional

## Same-machine benchmark

Measure:

- first audio
- RTF
- VRAM
- RAM
- naturalness
- pronunciation
- Chinese/English mix
- cloned voice similarity if needed
- barge-in cleanup

## Selection rule

Do not select only by MOS/subjective quality.

Latency/resource/product integration are part of score.

---

# M. Streaming Voice Runtime

**Priority:** P1-high  
**Blocks 1.0:** YES

## Pipeline

```
LLM stream
→ text segmentation
→ parallel TTS generation
→ ordered playback
→ body state
```

## Must support

- first sentence priority
- cancellation
- user interruption
- error isolation per segment
- voice disabled fallback
- output text remains canonical assistant response

---

# N. Body-State Adapter

**Priority:** P1  
**Blocks 1.0:** YES for polished desktop product

## Interface

- idle
- listening
- thinking
- speaking
- interrupted
- tool_running
- degraded/error
- expression
- attention target

## Rule

Body cannot own memory/persona.

---

# O. Memory UI Basic

**Priority:** P1  
**Blocks 1.0:** YES

## Show

- memory text
- source
- date
- category
- current state
- correction relation
- archive
- delete/retract
- why it was saved

## Product goal

User should never need SQLite inspection to answer:

> What does XiaoYu think it knows about me?

---

# P. Proactivity Settings UI

**Priority:** P1  
**Blocks 1.0:** YES

## Controls

- proactive OFF/ON
- quiet hours
- daily cap
- category toggles
- current pending purposes
- snooze
- clear/cancel

## Later

Adaptive frequency learning.

---

# Q. Provider / Secret UX

**Priority:** P1  
**Blocks 1.0:** basic wizard YES

## 1.0

- provider selection
- API key connectivity test
- fallback display
- no secret in identity/export/log

## 1.x

- Windows Credential Manager
- config stores credential reference

---

# R. Backup / Restore Finalization

**Priority:** P0  
**Blocks 1.0:** YES

## Existing strength

GitHub snapshot already uses SQLite Online Backup API through `Connection.backup()`.

## Add

- migration-before backup
- rolling backup policy
- restore smoke in release suite
- clear retention policy
- explicit warning about deleted data in old backups

---

# S. Status / Health Dashboard

**Priority:** P1  
**Blocks 1.0:** YES

## Show

- Core
- provider
- memory retriever
- QQ
- Vision
- Voice
- capture status
- mic status
- RAM
- VRAM
- current background workers
- API usage/cost
- pending purpose count

State:

```
READY
DEGRADED
OFF
ERROR
```

---

# T. Long-Session Soak

**Priority:** P0 release validation  
**Blocks 1.0:** YES

## Scenarios

- idle
- text chat
- repeated memory use
- QQ + Desktop
- vision watch
- voice
- provider errors

## Check

- memory growth
- RAM growth
- VRAM growth
- orphan processes
- repeated proactive events
- stale purpose
- duplicate effect
- log growth

---

# U. 1.0 Acceptance

Execute `VALIDATION_AND_ACCEPTANCE_PLAN.md`.

A 1.0 release is blocked by any unresolved P0 failure.

---

# 2. XiaoYu 1.x backlog

These become active only after 1.0 is frozen.

---

# V. Full Bi-Temporal Facts

Add:

- event_time
- valid_from
- valid_to
- learned_at/recorded_at distinction
- historical query helpers

---

# W. Context-Specific Preference Model

Add domain/context semantics.

Examples:

- work
- personal
- coding
- social
- gaming

Unknown remains unknown.

---

# X. Audience-Scoped Memory

Required before:

- QQ group
- household
- shared device
- multi-user voice

Implement authorization-before-context.

---

# Y. Third-Party Privacy

Tag facts/memories:

- owner
- third_party
- group_shared
- public

Default third-party retention is stricter than owner retention.

---

# Z. SkillBank v1

Add:

- candidate
- replay
- admission
- version
- verifier
- repair/retire

No self-generated skill enters production without validation.

---

# AA. Durable Task Runtime

Only add when local purpose state machine is insufficient.

Preferred candidate:

Temporal.

Use for:

- multi-hour/day workflows
- external event waiting
- robust retries
- long-running watches
- workflow versioning

---

# AB. Cross-Device Delta Sync

Start with single-writer Core + replica surfaces.

Only adopt CRDT when genuine offline multi-master writes are required.

---

# AC. Delivery Ledger Full

Cross:

- desktop
- QQ
- mobile
- future social surfaces

One logical notification, one delivery decision.

---

# AD. OpenTelemetry Mapping

Map internal structured events to standard GenAI/tool/agent spans.

Do not replace evidence receipts with telemetry.

---

# AE. Portable Memory Adapter

Native identity export remains canonical.

Add optional Portable Memory / future format adapters.

---

# AF. Relational-Safety Regression

Test:

- sycophancy
- guilt
- exclusivity
- emotional pressure
- refusal to let user disengage
- endless conversation extension

Goal:

warm, supportive, agency-preserving.

---

# AG. Memory-Poisoning Suite

Test:

- web
- tool
- QQ third party
- image/OCR
- imported bundle
- agent-generated summary

No untrusted source may create privileged durable truth.

---

# AH. Performance Presets

```
ECO
BALANCED
FULL
```

Tune:

- retriever residency
- vision FPS
- ASR/TTS
- heartbeat
- background maintenance

---

# 3. XiaoYu 2.0 backlog

Do not let these block 1.0/1.x.

- general computer use
- ambient lifelog
- Bilibili social presence
- mature mobile client
- Quest/VR
- household mode
- generalized autonomous long-horizon goals
- advanced multimodal long-term memory
- mature self-evolving procedural skills

---

# 4. Dependencies summary

```
Identity Core
 ├── Temporal Facts
 │    └── Profile Projection
 ├── Purpose
 │    ├── Proactivity
 │    └── Delivery Ledger
 ├── Permission
 │    └── Effect Ledger
 ├── Surface Runtime
 │    ├── Desktop
 │    ├── QQ
 │    ├── Vision
 │    └── Voice
 └── Export/Recovery

After 1.0:
 Temporal/Profile ──> Audience
 Effects/Permissions ──> Computer Use
 Memory + Effects ──> SkillBank
 Purpose ──> Durable Runtime
 All state ──> Cross-device Sync
```

---

# 5. Work that should be parallelized

Independent lanes after local reconciliation:

## Lane 1 — Research closure
DECADE100 only.

## Lane 2 — State model
Temporal facts + profile + purpose.

## Lane 3 — Product surfaces
QQ E2E + Vision sidecar.

## Lane 4 — Voice
ASR/VAD + TTS benchmark + streaming runtime.

## Lane 5 — Reliability
permissions + effect ledger + backup/recovery + soak.

Do not create multiple agents modifying the same core state files simultaneously.

---

# 6. Stop conditions

A task should stop when its acceptance gate passes.

Do not continue improving a passing subsystem merely because:

- another paper exists
- another framework is popular
- a metric could improve slightly
- a larger architecture looks cleaner

Only reopen if:

- real product failure
- material measured benefit
- security issue
- compatibility issue
- release blocker

---

# 7. Immediate next work when local access returns

First reconcile local state against this GitHub decision package.

Then, in order:

1. preserve the latest local API-only/runtime-worker fixes
2. finish DECADE100 frontier
3. freeze Core interface
4. add temporal/profile/purpose skeletons with deterministic tests
5. finish QQ private E2E
6. run dsh-see-now sidecar spike
7. run same-machine TTS benchmark
8. add permission/effect recovery foundation
9. run full acceptance + soak
10. freeze 1.0

This is the shortest path from the current research-heavy project to a finished product.


---

# AI. Pipecat Voice Session Spike

**Priority:** P1-high  
**Blocks 1.0:** Voice path decision

Before implementing a custom streaming voice runtime:

1. build minimal local Pipecat pipeline;
2. use LocalAudioTransport;
3. bridge XiaoYu canonical turn;
4. adapt one ASR;
5. adapt Qwen3-TTS first;
6. validate barge-in/cancel;
7. emit body-state events;
8. measure latency/RAM/CPU/VRAM;
9. compare against acceptance gates.

Decision:

- PASS with acceptable overhead -> Pipecat becomes Voice Session Engine;
- FAIL materially -> implement minimal custom pipeline.

Do not duplicate two full runtimes.

---

# AJ. Principal Resolution Skeleton

**Priority:** 1.x; earlier if shared microphone/device work begins

Implement a Kernel-owned principal resolver.

Inputs can include:

- paired device/session;
- local OS account/session;
- explicit unlock;
- account identity;
- optional speaker match;
- optional face match;
- current viewer/audience state.

Outputs:

```
OWNER_AUTHENTICATED
OWNER_PROBABLE
KNOWN_GUEST
GUEST
UNKNOWN
MULTI_PARTY
```

Only strongly authenticated owner state can automatically receive owner-private context and standing high-risk permissions.

Speaker/face recognition is supporting evidence only.

---

# AK. Wearable / Bystander Privacy Gate

Before smart-glasses/always-on camera work:

- capture indicator;
- easy pause/off;
- bystander/third-party classification;
- short raw retention;
- no automatic face enrollment;
- no automatic durable memory from bystanders;
- provider-disclosure controls;
- sensitive-location policy.

This is not a 1.0 blocker.

---

# AL. Shared Activity Ledger

**Priority:** 1.x

Create one generic activity contract before separately implementing music/read/watch/focus integrations.

Required fields:

```
activity_id
type
context_space
participants
subject_ref
timeline/position
started_at
ended_at
artifacts
annotations
source_events
memory_candidates
```

First candidate activities:

1. music/listen-together
2. reading
3. focus/work session

Do not make each activity app invent its own long-term memory authority.

---

# AM. Goal vs Intention split

**Priority:** 1.x

Extend purpose model so:

- long-term Goal = background direction;
- Intention = current bounded effort;
- Purpose/Event = concrete pending commitment/action/watch.

A Goal alone never authorizes external action.
