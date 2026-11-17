# XiaoYu Source-Level Reference Mining

**Date:** 2026-11-18  
**Status:** source-level saturation pass  
**Goal:** inspect implementation/architecture sources of the strongest external references and extract mechanisms that materially change XiaoYu design. Marketing-only similarities are excluded.

---

# 1. V1rtual-Desk-Pet

Repository: https://github.com/V1rtual-Klavte/Desk-Pet

## Mechanisms verified

### Native Host vs Harness ownership

The project deliberately separates:

- native host responsibilities:
  - desktop/window integration
  - observation
  - durable native state
  - subprocess supervision
  - final command/security boundary
- Node harness responsibilities:
  - model/business logic
  - tools/MCP/skills
  - context and agent behavior

### Private IPC

The design uses private local IPC rather than assuming localhost HTTP.

Important mechanisms include:

- handshake/role negotiation
- request/response IDs
- event broadcast
- control channel + binary/media handling
- bounded blob registry
- backpressure/credits
- generation rotation after child runtime crashes

### Input source metadata

User input is persisted before model dispatch and carries source-related metadata.

Synthetic/proactive/recovery traffic can be marked as not eligible for memory.

## XiaoYu adoption

Add a first-class per-event/input envelope:

```
source_surface
source_principal
source_type
trust_class
taint
eligible_for_memory
audience_scope
correlation_id
```

This should exist before increasingly many surfaces start writing into one Core.

---

# 2. N.E.K.O

Repository: https://github.com/Project-N-E-K-O/N.E.K.O

## Mechanisms verified

### Event-before-view

State transitions can be represented as:

```
append durable event
→ update derived view
```

If the view update fails after the event is committed, startup reconciliation can replay the authoritative event.

### At-least-once outbox

Delivery work can be retried, therefore handlers must be idempotent.

### Deterministic reflection identity

Derived reflection batches can be keyed from source/fact IDs so a retry does not create a new logical reflection.

## XiaoYu adoption

Strengthen the existing event-ledger design:

- authoritative event before rebuildable projection where practical;
- derived view reconciliation on startup;
- deterministic IDs for derived/consolidated work;
- outbox/effect handlers must be idempotent.

---

# 3. Project AIRI

Repository: https://github.com/moeru-ai/airi

Relevant design docs:
- packages/plugin-sdk/docs/design/architecture.md
- packages/plugin-sdk/docs/design/capability-orchestration.md
- packages/plugin-sdk/docs/design/multi-transport.md

## Mechanisms verified

### Capability-oriented plugin architecture

AIRI is moving toward explicit capability orchestration rather than plugin-name branching.

Registry/orchestration metadata includes compatibility/health concerns.

### Control plane vs data plane

High-frequency media data should not travel through the same generic control path as:

- lifecycle
- configuration
- discovery
- permission
- status

This is highly relevant to:

- audio streams
- screenshots
- video frames
- future avatar motion

## XiaoYu adoption

Capability Contract should separate:

```
Control Plane:
  discover
  negotiate
  configure
  start/stop
  health
  permission

Data Plane:
  audio
  image/video
  streaming text
  large binary outputs
```

Do not force all media through JSON control RPC.

---

# 4. existence-master/Sentient

Repository: https://github.com/existence-master/Sentient

## Mechanisms verified

### One agent loop across product paths

Chat, tasks, subagents and proactive context reuse the same main agent loop instead of creating separate behavioral brains.

### Pushed memory

Relevant memory is assembled into context by the system rather than relying exclusively on the model remembering to invoke a memory tool.

### Review inbox

Unasked/imported/external memories can wait for review instead of immediately entering privileged context.

### Durable tasks

Task transcripts/checkpoints can resume after restart.

### Watcher scripts

Cheap deterministic scripts watch external state and only wake AI when something changes.

### Skill verification

A proposed skill contains explicit verification and is not equivalent to a trusted skill merely because the model wrote it.

### Memory context spaces

Memory can be scoped to Personal / Work / Project / Global contexts.

### Source disconnect deletion

Disconnecting a source can optionally remove derived memories/summaries/results that came solely from that source.

## XiaoYu adoption

Promote to 1.x:

- Context Spaces
- source lifecycle / derived-data cascade
- deterministic watchers
- reviewed imported/external memory
- durable purpose checkpoints

---

# 5. Tamanitomo

Repository: https://github.com/tamanitomo/tamanitomo

Relevant source: docs/CONCEPTS.md

## Mechanisms verified

### One state, derived views

The durable event ledger remains authoritative; readable state files/views are derived.

### Important things are superseded, not silently overwritten

Corrections preserve historical continuity.

### Behavioral rules live in code, not prompt

Examples:

- quiet hours
- daily cap
- permissions
- delivery expiry

### Decide-to-speak and delivery are separate

A proactive thought does not imply a message was actually sent.

### Unknown delivery is treated conservatively

The project prefers avoiding duplicate sends when delivery status is ambiguous.

### Sensors expire

If a sensor disappears, stale old sensor state is removed rather than treated as current forever.

### Cheap before expensive

State fingerprinting avoids an LLM call when nothing material changed.

### Derived values should be computed

Values like age/duration are computed from canonical dates instead of stored as slowly-staling numbers.

## XiaoYu adoption

Directly adopt principles:

- one authority + rebuildable projections
- code-enforced proactivity gates
- proactive decision != delivery
- sensor TTL/staleness
- deterministic fingerprint before AI wake
- derived values computed from primary facts

For ambiguous external-effect delivery XiaoYu should retain its stronger:

```
UNKNOWN
→ reconcile target state
→ retry only if safe
```

rather than universally giving up on retry.

---

# 6. Nexus

Repository: https://github.com/FanyinLiu/Nexus

Relevant source: docs/ARCHITECTURE.md

## Mechanisms verified

### Main process as authority

Renderer/UI is not trusted as the durable-state owner.

### Transient sensory data

Screen captures may be processed and then discarded; only bounded derived state remains.

### Fingerprints instead of content

For some change detection, salted comparison fingerprints can be retained rather than the sensitive raw content.

### External messages do not automatically become model context

Inbound Telegram/Discord-like content is not assumed to have owner authority.

### Release-level privacy gates

The project has explicit architecture/privacy/storage/vault/message/context audits.

## XiaoYu adoption

Add to perception contract:

- sensor TTL
- raw retention policy
- optional change fingerprint
- observation trust class
- explicit context eligibility

Add product release gates for privacy boundaries, not only feature correctness.

---

# 7. MIRA

Repository: https://github.com/Vexillon-ai/MIRA

## Mechanisms verified

### Extensible traits

Providers/channels/tools/skills are explicit extension surfaces.

### Trust-tiered memory providers

Memory inputs can carry different trust classes.

### Signed/limited skills

Self-authored skills are not automatically equivalent to privileged executable extensions.

### Restricted Mode

Dangerous capabilities can be denied server-side in a fail-closed mode.

### Local-only fallback default

Fallback does not have to silently move private work to cloud providers.

### Liveness != readiness

The system separately models:

- process alive
- service ready to accept work

### Independent sentinel

An out-of-process monitoring component can detect/report failure even when the primary application is unavailable.

## XiaoYu adoption

Promote these principles:

```
liveness
readiness
capability health
```

are separate.

For future high-availability 1.x:

- tiny independent Guardian process
- no LLM required
- only health/recovery/notification duties

Also add:

> local → cloud fallback requires explicit privacy policy/grant.

---

# 8. Sentient OS

Repository: https://github.com/Sentient-OS-Labs/sentient-os

## Mechanisms verified

### Night cycle

While plugged in/idle, the system can process enabled personal sources and update human-readable knowledge.

### Bounded wake and checkpoints

Night work is not assumed to run forever; it can checkpoint and resume.

### Prepare, do not silently execute

Proactive intelligence can prepare drafts/suggestions for morning review while execution remains user-driven.

### Separate computer-use cursor

Computer control is visible and interruptible rather than hidden.

## XiaoYu adoption

Move Sleep/Night Cycle into 1.x.

Its contract should be:

```
new evidence
→ deterministic maintenance
→ optional bounded AI consolidation
→ profile/fact proposals
→ stale-purpose review
→ proactive candidates
→ health/backup report
→ no unauthorized external execution
```

Produce a user-readable nightly change report.

---

# 9. IronClaw

Repository: https://github.com/nearai/ironclaw  
License: MIT OR Apache-2.0

## Mechanisms verified

### Wasm tool sandbox

Untrusted tools can run in WebAssembly with:

- capability-based permission
- endpoint allowlists
- secret injection at host boundary
- secret leak scanning
- rate limits
- memory/CPU/execution limits

### Secret non-disclosure

Tools can use credentials without receiving raw credentials.

### Self-expanding capability path

Tools can be built/installed without giving them unrestricted host-process power.

## XiaoYu adoption

Promote Wasm from “distant option” to a **1.x third-party tool/plugin target**.

Do not use Wasm for XiaoYu Core or heavy media models.

Good future Wasm classes:

- transforms
- parsers
- bounded web/API tools
- deterministic helpers
- small skill executors

---

# 10. Moltis

Repository: https://github.com/moltis-org/moltis  
License: MIT

## Mechanisms verified

- modular Rust service interfaces
- Docker/Apple Container/Wasm execution backends
- secret/vault subsystem
- network filters
- before-tool-call gating
- release attestations/signing
- voice/provider modularity
- lightweight build mode for constrained devices

## XiaoYu adoption

Reference for:

- future Tool Execution Provider
- provider/tool service traits
- supply-chain verification
- constrained-device capability profile

Do not import its entire server architecture into XiaoYu.

---

# 11. Pipecat

Repository: https://github.com/pipecat-ai/pipecat  
License: BSD-2-Clause  
Python: supports 3.11+ in current project docs

## Mechanisms verified

### Mature realtime voice/multimodal pipeline

It already provides:

- local audio input/output transport
- STT / LLM / TTS service abstraction
- VAD
- local smart-turn models
- interruption/barge-in processing
- cancellation frames
- scripted interruption evaluation
- local and remote transports
- provider integration ecosystem
- debugging/evaluation tooling

### Custom TTS integration seam

`TTSService` exposes a standard service interface including a `run_tts` path.

This means Qwen3-TTS or GPT-SoVITS can be adapted into Pipecat without rewriting the entire conversational audio pipeline.

## XiaoYu adoption

**Change prior implementation recommendation.**

Instead of first building a custom:

```
segmenter
→ TTS workers
→ ordered queue
→ interruption engine
```

evaluate Pipecat as the primary Voice Session Engine.

Suggested XiaoYu layering:

```
XiaoYu canonical turn / identity
        ↓
Voice Session Adapter
        ↓
Pipecat
  ├─ LocalAudioTransport
  ├─ XiaoYu ASR adapter
  ├─ XiaoYu LLM stream adapter
  ├─ Qwen3-TTS / GPT-SoVITS TTSService
  └─ turn/interruption pipeline
        ↓
Body state events
```

XiaoYu Core remains the conversation authority.

Pipecat owns realtime audio flow only.

---

# 12. LiveKit Agents

Repository: https://github.com/livekit/agents  
License: Apache-2.0

## Mechanisms verified

- interchangeable STT/LLM/TTS
- WebRTC clients on major platforms
- job dispatch
- native turn/interruption handling
- adaptive interruption/backchannel handling
- runtime model updates
- tool interruption behavior
- builtin agent testing
- video/avatar integrations

## XiaoYu adoption

Do not add for local desktop 1.0 if Pipecat/local audio is sufficient.

Re-evaluate when XiaoYu needs:

- phone/WebRTC realtime voice
- remote rooms
- multi-user audio
- telephony
- distributed realtime media

LiveKit is a strong **future transport/runtime candidate**, not current Core.

---

# 13. Atrio

Repository: https://github.com/29-Cu/atrio

## Mechanisms verified

A guest lounge can be designed with:

- one-time expiring links
- per-session message limits
- guest transcript visible to guest but not host admin
- host sees only an AI-written visit summary
- guest AI has zero tools by default
- memory recall/write hooks off by default
- isolated temp execution for guest-facing model

## XiaoYu adoption

If “friends visit XiaoYu” is ever added:

Guest Session defaults must be:

```
no owner-private memory
no privileged tools
no owner permissions
no durable owner-profile mutation
bounded TTL
bounded messages
separate audience
```

Any guest-derived summary is **model-derived evidence**, not a confirmed fact.

It may enter a review/candidate inbox, never direct owner memory.

---

# 14. Duetto / co-reading ecosystem

Representative:
- https://github.com/avisforevelyn/Duetto
- https://github.com/meowmana/coread
- co-reading / film / shared calendar projects in the companion ecosystem

## Mechanisms verified

Companion activity state is richer than chat:

- current media
- playback/reading position
- exact lyric/passages
- shared annotations
- presence notes
- repeat count/history
- shared reactions
- activity artifacts

Duetto additionally turns accumulated song-specific presence notes into song memory.

## XiaoYu adoption

Add a future **Shared Activity / Encounter Ledger** separate from ordinary messages.

Possible schema:

```
activity_id
type
context_space
participants
started_at
ended_at
subject_ref
position/timeline
artifact_refs
shared_annotations
source_events
memory_candidate_ids
```

Examples:

- listening
- reading
- watching
- focus/work session
- game
- trip/event

This is 1.x product state, not a 1.0 release blocker.

---

# 15. Operit / Operit2

Repositories:
- https://github.com/AAswordman/Operit
- https://github.com/AAswordman/Operit2

## Mechanisms verified

### Operit

A mature Android agent product demonstrates:

- tool permissions Allow/Ask/Deny
- Android accessibility/device automation
- local/cloud model selection
- multiple model roles
- multiple memory spaces
- per-character model/memory/tool/skill/MCP configurations
- workflow triggers
- marketplace/extensions
- backup/restore
- local HTTP/Web access disabled by default

### Operit2

Operit2 moves toward:

```
CoreNode
Host
Space
Binding
```

Each node has its own local Host capabilities.

Space membership does **not** transfer local OS permissions.

Task handoff is constrained to a safe boundary:

```
tool result persisted
AND
next model request not started
```

The target node synchronizes the required records and then continues.

An in-progress model request, terminal process or browser session is not magically migrated.

## XiaoYu adoption

Long-term cross-device direction becomes clearer:

### Near term

```
one authoritative Core
+ thin capability/surface nodes
```

### Later

Potential evolution:

```
replicated canonical event protocol
+ multiple Core-capable nodes
+ local Host permissions
+ persisted-boundary task handoff
```

Do not implement true multi-master until there is a real need.

Key invariant:

> Device membership never implies permission inheritance.

---

# 16. Cross-project mechanisms that now look universal

After direct source inspection, the strongest repeated patterns are:

## A. One authoritative state + derived views

Repeated by XiaoYu, Tamanitomo, N.E.K.O-style event/view patterns, and several memory systems.

## B. Source classification before memory

Every inbound datum should carry origin/trust/context/memory eligibility.

## C. Proactive decision separate from delivery

Repeated across Tamanitomo, Nexus, Sentient-like systems.

## D. Cheap detector before model call

Watchers/fingerprints/local screen-change detection dominate mature low-cost designs.

## E. Liveness, readiness, capability health are different

Especially clear in MIRA and mature service systems.

## F. Side-effect ambiguity needs reconciliation

Event/outbox systems show that “did the call return?” is not sufficient.

## G. High-frequency media needs a data plane

AIRI/V1rtual/Pipecat all point away from JSON-everything designs.

## H. Third-party code needs real isolation

IronClaw/Moltis/NanoClaw show a spectrum:

- Wasm capability sandbox
- container isolation
- restricted host mounts
- host-side credential injection

## I. Cross-device execution requires checkpoint boundaries

Operit2/Sentient long-task designs reinforce this.

## J. Relationship continuity gains from shared artifacts

Co-reading/listening/home projects repeatedly create durable shared artifacts rather than relying only on chat summaries.

---

# 17. What the source mining changed

## Newly promoted to 1.x

- Source lifecycle + cascade cleanup
- Context Spaces
- Night/Sleep maintenance cycle
- Wasm third-party tool sandbox
- Guardian/Sentinel health process
- Shared Activity / Encounter Ledger
- structured Guest Session boundary
- device capability-node protocol
- privacy-aware local-only fallback rules

## Changed implementation choice

Voice:

```
OLD:
custom streaming audio orchestration first

NEW:
evaluate Pipecat first;
write XiaoYu-specific ASR/TTS/LLM/body adapters;
custom minimal runtime only if Pipecat overhead/integration fails measured gates.
```

## Strengthened Capability Contract

Add:

- liveness vs readiness
- data-plane stream contract
- input source/trust envelope
- provider privacy/fallback eligibility
- sensor TTL
- sidecar generation/process ownership
- provider capability degradation
- context-space eligibility

---

# 18. Source-level saturation verdict

At this point newly inspected projects continue to instantiate existing mechanism families rather than create new XiaoYu Core concepts.

The remaining high-value work is:

```
mechanism benchmark
→ implementation spike
→ measure overhead
→ adopt/adapt/reject
```

rather than finding more repositories.

Mark:

**SOURCE_LEVEL_ECOSYSTEM_SATURATED_2026-11-18**
