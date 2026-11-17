# XiaoYu Ecosystem Saturation — Final Verdict

**Date:** 2026-11-18  
**Status:** `ECOSYSTEM_AND_ARCHITECTURE_SATURATED`

This file is the compact authority for the external-research phase. Detailed evidence and implementation notes remain in the sibling survey documents.

---

## 1. What was actually surveyed

The research was expanded beyond feature-keyword search and cross-checked across:

- long-lived AI companions
- desktop pets / VTubers / digital life
- personal AI OS / local-first personal agents
- proactive / always-on agents
- memory / identity / user-model systems
- companion homes / virtual phones
- mobile / wearable / hardware companions
- voice / realtime multimodal runtimes
- computer-use / tool execution runtimes
- plugin / skill / MCP ecosystems
- Wasm/container sandbox runtimes
- multi-device agent systems
- shared activities
- guest/social companion systems
- persona and memory portability
- privacy / authorization / memory poisoning / multimodal injection
- longitudinal companion evaluation

The survey used both broad project discovery and direct source/architecture inspection of representative high-value systems.

---

## 2. Strongest external references by mechanism

### Whole companion/product

- Project AIRI
- N.E.K.O
- V1rtual-Desk-Pet
- OpenAlma
- Sentient
- Sentient OS
- MIRA
- Tamanitomo
- Nexus
- YuriOS
- Alicization
- Miru
- AILIS
- Operit

### Memory / identity / user model

- Memory Constellations
- Serein
- moraine-home
- Personal Model / HUMAN.md
- Mem0
- Graphiti
- Hindsight
- Letta
- LoCoMo / Memora / LongMemEval family

### Capability/runtime architecture

- AIRI plugin platform
- V1rtual native-host/harness design
- MIRA trait/provider architecture
- Operit2 CoreNode/Host/Space/Binding
- IronClaw Wasm tool sandbox
- Moltis execution backends
- MCP lifecycle/capability ideas

### Realtime voice

- Pipecat
- LiveKit Agents
- Open-LLM-VTuber
- sherpa-onnx / Sherpaw
- Qwen3-TTS / GPT-SoVITS / CosyVoice candidates

### Perception

- dsh-see-now
- screenpipe
- Nexus
- Sentient OS
- smart-glass / device-node projects

### Shared relationship experience

- Duetto
- Coread and co-reading ecosystem
- film/shared-calendar/journal tools
- Morrow / KI-CO / companion-space projects
- Atrio guest lounge

---

## 3. Final stable XiaoYu state model

No later discovery required a new fundamental memory authority.

Final durable state families:

```
SELF
  Identity
  Persona
  Relationship projection

USER MODEL
  Preferences
  Habits
  Important people
  Interaction/proactivity preferences

MEMORY
  Raw event provenance
  Episodic memories
  Temporal facts
  Dossiers/profile projections
  Source lifecycle
  Context/audience metadata

GOALS / INTENTIONS / PURPOSE
  Long-term goals
  Active intentions
  Concrete reminders/tasks/watches/events

SKILLS
  Verified procedural knowledge
  Versions
  Verification history

WORLD / PERCEPTION
  Time-bounded observations
  Sensor state with TTL
  App/device context

EXECUTION STATE
  Permissions
  Effects/receipts
  Durable task state
  Deliveries

PRINCIPAL / AUDIENCE CONTEXT
  Authenticated/estimated current user
  Viewers
  Session scope
  Confidence/auth level

SHARED ACTIVITY
  Reading/music/film/focus/game/event sessions
  Progress
  Shared annotations/artifacts
```

---

## 4. Final Kernel boundary

Stable semantic Kernel owns:

- identity authority
- event semantics
- memory/temporal truth
- canonical turn
- goals/intention/purpose lifecycle semantics
- principal/audience resolution policy
- authorization semantics
- external-effect ledger
- capability registry/router

Everything implementation-facing is replaceable through capability contracts.

---

## 5. Final capability isolation model

### Trusted in-process

For lightweight first-party pure logic.

### Local sidecar

For:

- Vision
- TTS
- heavy ASR
- native/GPU runtimes
- browser/computer-use
- crash-prone runtime dependencies

### Wasm sandbox

Preferred 1.x direction for small untrusted third-party tools.

### Remote provider

For cloud LLM/Vision/Speech/services.

State remains with XiaoYu whenever practical.

---

## 6. Major route changes discovered during the saturation pass

### Voice

Before:

```
build custom streaming TTS orchestration first
```

After source mining:

```
evaluate Pipecat first
→ add XiaoYu ASR/TTS/LLM/body adapters
→ retain XiaoYu canonical turn authority
→ custom pipeline only if measured gates fail
```

LiveKit remains the future candidate for WebRTC/mobile/remote multi-user voice.

### Third-party tools

Wasm moved from distant idea to explicit 1.x direction after reviewing IronClaw/Moltis.

### Proactivity

Cheap deterministic watcher/fingerprint/scheduler first; LLM judgment later.

No free-running expensive inner monologue as the default.

### Cross-device

1.0:
single authoritative Core + thin surfaces

1.x:
single authority + device capability nodes

Later only if justified:
replicated event protocol + multiple Core-capable nodes with persisted-boundary handoff

### Night cycle

Promoted into 1.x as maintenance/consolidation, not roleplay.

### Social/guest

Guest Session must be isolated before social visits.

### Shared experience

Shared Activity / Encounter Ledger added for co-reading/music/film/focus/etc.

### Principal resolution

Added for shared microphones, phones, glasses, cameras and household devices.

---

## 7. Final key safety/privacy invariants

1. **Principal Resolution before private context**
2. **Authorization before Context**
3. **Authorization before Action**
4. untrusted perception/tool/web content is observation/data, not instruction
5. external data cannot silently become owner-authoritative memory
6. source disconnect can trigger derived-state cleanup
7. local provider failure does not silently authorize cloud disclosure
8. device membership does not inherit another device's OS permissions
9. Guest/Unknown does not receive owner-private memory/standing high-risk grants
10. biometric matching is supporting evidence, not sole high-risk authentication
11. bystander data gets stricter retention/promotion rules
12. third-party tools do not self-approve requested capabilities

---

## 8. Final strongest product insight

The ecosystem makes clear that a companion relationship is not built by chat alone.

High-value future experience surfaces are:

- Companion Home
- diary/timeline
- shared music
- co-reading
- film/watch sessions
- focus/work sessions
- keepsakes
- active purposes
- guest visits
- mobile/device presence

These create grounded shared experiences.

They should generate structured activity evidence and memory candidates rather than directly rewriting identity.

---

## 9. What XiaoYu should reuse instead of rebuilding

Strong reuse candidates:

- dsh-see-now → screen capture/event sampling
- Pipecat → realtime local voice session orchestration
- sherpa-onnx → local ASR/speaker evidence primitives
- Qwen3-TTS / GPT-SoVITS → TTS implementations
- MCP → external general tools
- Wasm runtime / IronClaw-like model → future third-party tool isolation
- OpenTelemetry → observability vocabulary
- Temporal → later durable long-running workflows if local state machine becomes insufficient
- standard OS credential store → secrets
- standard SQLite backup API → backup

Study mechanisms from AIRI/N.E.K.O/V1rtual/Sentient/MIRA/etc.; do not migrate XiaoYu into their host runtimes.

---

## 10. What remains deliberately XiaoYu-owned

The differentiating layer remains:

```
model-independent identity
+
source-grounded provenance
+
temporal correction/freshness
+
human-confirmed persona evolution
+
answer/evidence contract
+
prospective frozen evaluation
+
calibrated proactive policy
+
same identity across replaceable capabilities
+
verified effects/skills
```

External projects are often stronger in individual product modules.

That is an advantage: XiaoYu can reuse solved modules while preserving this authority layer.

---

## 11. Saturation stop rule

Do not reopen broad ecosystem research merely because a new repository appears.

Reopen architecture only if an external system demonstrates one of:

1. a genuinely new durable state class;
2. a stronger authority/provenance boundary;
3. a substantially safer isolation/authorization primitive;
4. an order-of-magnitude resource/cost improvement;
5. a product capability impossible under current contracts;
6. reproducible evidence that a current XiaoYu architecture decision is materially inferior.

Otherwise classify it as:

- provider candidate;
- implementation reference;
- product UX reference;
- benchmark source.

---

## 12. What research becomes valuable now

Broad discovery is complete enough.

The next useful external work is **module-specific source mining and empirical spikes**, for example:

1. Pipecat + XiaoYu voice adapter
2. dsh-see-now sidecar
3. Qwen3-TTS vs GPT-SoVITS
4. InputSourceEnvelope / Principal Resolution contract
5. Purpose act/abstain/cancellation tests
6. temporal/profile schema
7. Wasm tool sandbox proof-of-concept in 1.x
8. source-disconnect deletion propagation
9. Night Cycle bounded consolidation
10. shared-activity contract

This is implementation research, not ecosystem discovery.

---

**Final status:**

```
PROJECT_LANDSCAPE_SATURATED = true
ARCHITECTURE_CLASSES_SATURATED = true
SOURCE_MECHANISM_FAMILIES_SATURATED = true
IMPLEMENTATION_BENCHMARKING_REMAINS = true
```
