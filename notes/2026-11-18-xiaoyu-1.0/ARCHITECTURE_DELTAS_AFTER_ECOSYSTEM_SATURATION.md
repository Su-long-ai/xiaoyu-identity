# XiaoYu Architecture Deltas After Ecosystem Saturation

**Date:** 2026-11-18  
**Purpose:** list only the changes introduced by the final ecosystem/source-mining pass. This document overrides older implementation suggestions where explicitly stated.

---

# D1. Add InputSourceEnvelope

Every canonical inbound event should eventually have:

```
surface
principal
source_type
trust_class
taint
eligible_for_memory
audience_scope
context_space
correlation_id
```

Reason:

Desktop, QQ, Vision, tools, guests and future device nodes must not enter Core as semantically equivalent text.

---

# D2. Health is three-dimensional

Replace simple healthy/unhealthy with at least:

```
liveness
readiness
capability_health
```

Example:

TTS process alive
but voice-cloning model OOM
while basic speech still ready.

This should become part of Capability Contract.

---

# D3. Add future Guardian/Sentinel

1.x candidate:

A tiny independent process monitors:

- Core liveness
- sidecar/process tree
- stuck restart loop
- backup failure
- fatal health state

No LLM.

No identity/memory mutation.

It should survive the main app crashing.

---

# D4. Separate control and data planes

Control:

- lifecycle
- config
- health
- permission
- request metadata

Data:

- streaming audio
- video/frame data
- large binary blobs
- potentially token stream

For sidecars, do not base64 every large payload through generic JSON if avoidable.

---

# D5. Voice implementation recommendation changes

## Previous

Build XiaoYu streaming voice orchestration manually.

## New

Primary spike:

**Pipecat as Voice Session Engine.**

Why:

- Python 3.11 compatible
- BSD-2-Clause
- local audio transport
- VAD/turn strategies
- local smart-turn support
- interruption/cancellation
- TTS service abstraction
- scripted barge-in tests
- broad provider ecosystem

XiaoYu should own:

- canonical turn
- memory/context
- model policy
- voice provider selection
- body semantics

Pipecat should own:

- realtime audio flow
- turn detection plumbing
- cancellation/interruption pipeline
- audio transport

Build:

- Qwen3-TTS adapter
- GPT-SoVITS adapter
- selected ASR adapter
- XiaoYu LLM stream bridge
- body-state event bridge

Fallback:

If measured overhead/dependency complexity materially hurts the local desktop product, implement the minimal custom pipeline.

---

# D6. LiveKit is future transport, not 1.0 Core

Revisit for:

- mobile/WebRTC
- remote voice
- multi-user rooms
- telephony
- distributed media

Do not introduce it solely for local desktop voice.

---

# D7. Wasm plugin sandbox moves up to 1.x

IronClaw shows a practical full chain:

```
Wasm
→ capability allowlist
→ secret leak scan
→ host-side credential injection
→ endpoint policy
→ response scan
```

Use future Wasm for small third-party tools.

Do not use it for:

- Core
- identity
- memory authority
- GPU TTS/Vision

---

# D8. Context Spaces become formal 1.x state

Before full audience/multi-user semantics, add:

```
GLOBAL
PERSONAL
WORK
PROJECT:<id>
```

Facts/memories/purposes may belong to a context space.

Context-space selection is not the same as audience authorization.

---

# D9. Source lifecycle is first-class

A durable datum should know which external source(s) support it.

If a source is disconnected:

```
source disabled
→ stop future ingestion
→ identify solely-derived projections
→ offer archive/delete/retain decision
→ cascade rebuild
```

Do not silently retain opaque derived personal facts forever.

---

# D10. Sensor state requires TTL

Screen/app/location/audio observations are not eternal facts.

Every perception projection should have:

```
observed_at
expires_at / ttl
source
confidence
```

When sensor is absent, old state must become UNKNOWN, not remain “current.”

---

# D11. Night Cycle moves to 1.x

Night Cycle is maintenance, not fantasy roleplay.

Order:

```
deterministic cleanup
→ source reconciliation
→ duplicate/conflict scan
→ stale purpose review
→ profile projection rebuild
→ optional bounded consolidation model
→ proactive candidates
→ backup/health
→ user-readable report
```

Default external actions: none.

---

# D12. Add Shared Activity / Encounter Ledger in 1.x

Shared experience should not be reconstructed only from chat.

Capture structured activity:

- reading
- music
- film
- focus
- games
- events/trips

Memory remains separate.

Activity produces evidence and memory candidates.

---

# D13. Add Guest Session contract before social visits

Defaults:

- isolated audience
- zero private owner memory
- zero privileged tools
- bounded lifetime/messages
- no owner permission inheritance
- no automatic durable owner-memory write

Guest summaries are low-trust model-derived candidates.

---

# D14. Cross-device future becomes capability-node aware

1.0:

```
single Core
+ thin surfaces
```

1.x:

```
single authority
+ device capability nodes
```

Longer term, only if useful:

```
replicated event protocol
+ multiple Core-capable nodes
```

Task handoff occurs only at a persisted safe boundary.

Local OS permissions never transfer through node membership.

---

# D15. Local→cloud fallback must be privacy-aware

A local provider failure must not silently cause private data to be sent to a remote fallback.

Provider routing adds:

```
data_class
locality_requirement
cloud_fallback_allowed
user_grant
```

A model fallback can be technically compatible and still privacy-ineligible.

---

# D16. Proactive trigger pipeline is more deterministic than cognitive

Preferred default:

```
cheap watcher / scheduler / fingerprint
→ candidate event
→ validity/cancellation
→ intervention gate
→ optional model judgment
→ delivery gate
```

Not:

```
heartbeat
→ ask expensive model what it feels like doing
```

Continuous inner monologue remains an explicit bounded experiment only.

---

# D17. One state + projections is reaffirmed

Do not create separate authoritative stores for:

- profile
- search
- graph
- summary
- view
- device state

when they can be derived.

Canonical truth should remain as small and rebuildable as possible.

---

# D18. Product experience expands, Kernel does not

The ecosystem added meaningful future surfaces:

- Companion Home
- Shared Activities
- Guest Lounge
- Mobile
- device nodes
- social/community
- wearable/health context

These do **not** require another brain.

They should plug into the same Kernel through typed contracts.

---

# D19. Revised high-level roadmap

## 1.0

Unchanged focus:

- Core freeze
- DECADE100
- temporal/profile basics
- purpose/cancellation
- permissions/effects
- QQ private
- bounded Vision
- Voice
- recovery/backup
- memory/proactivity settings

Voice spike now evaluates Pipecat first.

## 1.x

Now explicitly includes:

- full bi-temporal
- Context Spaces
- audience scope
- source lifecycle/cascade
- SkillBank
- Night Cycle
- Wasm third-party tools
- Guardian
- device capability nodes
- Shared Activity Ledger
- Guest Session
- cross-device deltas
- delivery ledger
- richer relational/privacy gates

## 2.0

- general computer use
- true multi-Core/multi-master only if justified
- ambient lifelog
- broader social presence
- Quest/VR
- household mode
- advanced multimodal memory

---

# D20. New stop rule

The open-source landscape is now sufficiently broad that a new repository alone is not a reason to reopen architecture.

Reopen an architecture decision only when a new external mechanism demonstrates one of:

1. new durable state class;
2. materially better authority boundary;
3. safer permission/isolation primitive;
4. order-of-magnitude resource improvement;
5. user-visible capability impossible under current contracts;
6. reproducible evidence that an existing XiaoYu decision is inferior.

Otherwise classify the project as another provider/reference implementation.
