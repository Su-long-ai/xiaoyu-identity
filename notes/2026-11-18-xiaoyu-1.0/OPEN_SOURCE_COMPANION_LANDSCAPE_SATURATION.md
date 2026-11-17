# XiaoYu Open-Source Companion Landscape — Saturation Survey

**Research date:** 2026-11-18  
**Goal:** exhaust the current open-source landscape surrounding long-lived AI companions, desktop pets, personal AI OSes, proactive agents, memory/identity systems, embodied assistants, mobile companion spaces, and portable persona infrastructure.  
**Status:** architecture-level and project-landscape saturation reached after broad topic sweeps, curated-list cross-checking, and direct README/source inspection of representative projects.

---

# 1. Why the earlier survey was incomplete

Earlier XiaoYu research was primarily **capability-driven**:

- memory
- proactivity
- vision
- voice
- computer use
- plugins
- safety
- evaluation

That approach was good for architecture, but it missed projects that are easier to discover by **product identity** or **community vocabulary**:

- digital life
- AI companion
- desktop pet
- virtual phone
- companion space
- AI girlfriend/boyfriend
- persistent agency
- personal AI OS
- autonomous companion
- human-AI relationship tools
- co-reading / co-listening
- companion portability
- digital persona distillation

The corrected survey therefore searched by both architecture and product/ecosystem vocabulary.

---

# 2. Coverage and saturation method

The survey cross-checked:

- GitHub `ai-companion` topic (roughly 1.5k public repositories in the current crawl)
- `digital-life`
- `personal-ai`
- `proactive-agent` / `proactive-ai`
- desktop-pet / Live2D / VTuber companion terms
- local-first / second-brain / personal-model terms
- Chinese companion / 桌宠 / 数字生命 / 主动陪伴 terms
- Android / iOS / hardware companion projects
- DSH / MCP / skills ecosystems
- memory / persona portability projects
- curated `awesome-ai-companion` list

The curated Awesome AI Companion repository itself divides the ecosystem into:

1. Companion Clients & Workspaces
2. Virtual Phones & Companion Spaces
3. Background Heartbeats & Proactive Messaging
4. Memory, Identity & Emotion State
5. Voice, Visual Presence & Embodiment
6. Perception
7. Services & Real-World Integrations
8. Game Worlds & Agent Toys
9. Shared Activities & Media
10. Communities & Forums
11. Continuity & Data Ownership

This classification turned out to be useful because it covers **relationship/product surfaces** that architecture-first searches tend to miss.

---

# 3. Saturation conclusion

After the final sweeps, newly discovered projects continued to provide:

- different implementations;
- different UI/body forms;
- different licenses;
- different operating systems;
- different choices for memory/proactivity;

but they stopped introducing new fundamental Core state categories.

The final stable state model remains:

```
SELF
USER MODEL
MEMORY
PURPOSE
SKILLS
WORLD/PERCEPTION
EXECUTION STATE
```

What continued to expand was the **experience layer**:

```
COMPANION SPACE
SHARED ACTIVITIES
MOBILE / WEARABLE / HARDWARE
SOCIAL / VISITS
PORTABILITY / CONTINUITY
```

Therefore the architecture is saturated, while the product surface remains extensible.

---

# 4. Tier S — projects XiaoYu should study deeply

These projects are not necessarily "better than XiaoYu." They are selected because each contains a mature implementation pattern that can materially reduce XiaoYu's work or reveal product failure modes.

---

## S1. Project AIRI

Repository: https://github.com/moeru-ai/airi

### Strongest value to XiaoYu

- plugin platform
- capability model
- local/remote extension architecture
- control-plane vs data-plane separation
- Live2D/VRM embodiment
- voice
- games/world integrations
- multi-device direction

### Why it matters

AIRI is one of the closest public examples to the planned:

```
XiaoYu Kernel
→ Capability Registry/Router
→ local/sidecar/remote providers
```

### Do not copy

- do not migrate XiaoYu identity/memory authority into AIRI;
- do not let body/plugin architecture become identity authority.

---

## S2. N.E.K.O

Repository: https://github.com/Project-N-E-K-O/N.E.K.O

License: Apache-2.0

### Strongest value

- complete companion product ecosystem
- voice + vision + Live2D/VRM/MMD/PNGTuber
- memory with keyword/vector hybrid retrieval
- evidence scoring
- contradiction correction
- proactive delivery gates
- append-only event log
- outbox/restart replay
- idempotent writes
- plugin SDK / plugin manager / market
- device and social roadmap

### Why it matters

N.E.K.O is currently one of the strongest whole-product benchmarks for what an open companion platform can become.

---

## S3. V1rtual-Desk-Pet

Repository: https://github.com/V1rtual-Klavte/Desk-Pet

### Strongest value

A very close engineering comparison to XiaoYu:

```
Rust native host
+
single Node harness
+
private IPC
```

On Windows it uses a named-pipe-style private IPC architecture.

Implemented product ideas include:

- source-linked memory and version history;
- correction/forgetting invalidating old projections;
- proactive-message budgets and quiet time;
- silent observation;
- Skill/MCP lazy loading;
- four-level safety policy;
- user confirmation UI;
- runtime configuration;
- personality/profile import-export;
- native host ownership of observation/execution.

### Why it matters

It demonstrates that many of XiaoYu's proposed boundaries are practical in a real packaged desktop pet.

---

## S4. existence-master/Sentient

Repository: https://github.com/existence-master/Sentient

License: AGPL-3.0

### Strongest value

- one SQLite state store
- one agent loop shared by chat/tasks/helpers/proactivity/voice
- long-running tasks with restart resume
- watchers implemented as cheap scripts that only wake AI on change
- editable user model with reasons
- nightly memory consolidation
- skill proposals with verification checks
- local/cloud provider mixing
- phone / smart-glasses nodes
- task approval
- postcondition verification
- source-scoped memory (Personal / Work / Project / Global)
- source disconnect can optionally cascade-forget derived memories

### Particularly valuable new ideas

**Source-disconnect forgetting**

If a connected source is removed, the user can choose to remove the memories/summaries learned from that source.

This is a direct application of provenance to privacy deletion.

**Memory places**

Memories can be scoped to:

- personal
- work
- specific project
- every chat

This is more concrete than a single global profile and should inform XiaoYu 1.x context scope.

---

## S5. Sentient OS

Repository: https://github.com/Sentient-OS-Labs/sentient-os

License: AGPL-3.0

### Strongest value

- local high-volume reading of personal digital life
- files/messages/notes/mail/calendar
- on-device first-pass understanding
- human-editable Markdown knowledge
- overnight wake while plugged in
- bounded wake sessions
- interruption checkpoints
- proactive preparation
- proposed work waits for user to start execution
- separate screen-aware computer-use cursor
- choice of local/cloud model
- privacy/source selection

### XiaoYu implication

A useful “sleep cycle” is not:

```
LLM randomly dreams
```

It is:

```
idle / night
→ process new evidence
→ consolidate
→ detect open loops
→ prepare candidates
→ user sees suggestions
→ action waits for authorization
```

Move this idea from distant 2.0 into XiaoYu 1.x.

---

## S6. Alicization

Repository: https://github.com/TouHouQing/alicization

### Strongest value

- local-first digital-life control plane
- auditable structured thought/emotion/reply
- subconscious tick
- tension-based initiative
- dream/consolidation cycle
- tool permission gates
- workspace sandbox
- kill switch
- failures kept out of personality/memory
- explicit personality authority

### Difference from XiaoYu

Alicization leans on a Markdown soul file as primary personality authority.

XiaoYu should preserve its stronger provenance/versioned persona model.

---

## S7. Nexus

Repository: https://github.com/FanyinLiu/Nexus

### Strongest value

- quiet ambient presence
- privacy-sensitive desktop sensing
- contradiction-aware consolidation
- down-weighting rather than naive deletion
- proactive decision separated from delivery
- suppression during active chat/dismissal/duplicate/expired signals
- memory deletion propagation
- release-level testing discipline

### Why it matters

Nexus is a strong reference for making XiaoYu feel present **without becoming intrusive**.

---

## S8. Tamanitomo

Repository: https://github.com/tamanitomo/tamanitomo

### Strongest value

- self-hosted persistent companion
- evidence-backed owner facts
- append-only ledger
- code-enforced quiet hours and message limits
- independent outbox gate
- 16 background routines
- 6 routines require zero LLM calls
- fingerprinting avoids model calls when state did not change
- automatic Git-backed vault history
- nightly reflections/journals
- local/cloud provider chains

### Key lesson

“Always alive” does not mean “always call an LLM.”

Most persistent life-state can be deterministic.

---

## S9. MIRA

Repository: https://github.com/Vexillon-ai/MIRA

License: AGPL-3.0

### Strongest value

- Rust core
- providers/channels/tools/skills as extensible traits
- multi-channel identity linking
- external Channel Provider Protocol
- proactive check-ins
- signed packaged skills
- per-skill secret vault
- restricted fail-closed mode
- memory provider SPI with trust tiers
- memory history/supersession/deletion
- encrypted backup + two-phase restore
- audit trail

### Especially valuable

MIRA is one of the strongest references for XiaoYu's future:

```
Capability Contract
+
trust-aware memory providers
+
restricted mode
+
signed skills
```

---

## S10. YuriOS

Repository: https://github.com/yuri-os/YuriOS

### Strongest value

- always-on inner life
- small self-directed goals
- promise tracking
- memory consolidation while sleeping
- readable journal of what happened while user was away
- local voice with barge-in
- VRM/Live2D/body separation

### Lesson

If XiaoYu claims to have “life while away,” it should leave an auditable record, not fabricate vague backstory later.

---

# 5. Tier A — high-value specialized references

---

## A1. MIRROW

Repository: https://github.com/EvelynnYu/MIRROW

Strong ideas:

- every memory traced to original text;
- revisable cognition books;
- mood/habit/concern state;
- calendar/tasks;
- proactive wander engine that evaluates whether interruption is appropriate;
- sensing/co-listening;
- explicit public/private source separation.

Use for:

- provenance UI;
- cognition projection;
- proactive context checks.

---

## A2. Morrow

Repository: https://github.com/ariaprism/Morrow  
License: MIT

Strong ideas:

- one-user “home” metaphor;
- branching conversations;
- rolling memory;
- companion free-time room;
- future-self notes;
- proactive Web Push;
- diary, keepsakes, cycle records, shared songs;
- encrypted backup;
- optional private-GitHub backup.

Product lesson:

A companion needs a **place** as well as a chat surface.

---

## A3. Aura

Repository: https://github.com/gqy20/Aura

Strong ideas:

- native Android companion;
- Room-based LTM;
- emotional/relationship projections;
- 6h local Qwen Dream Loop;
- post-chat insight after a short delay;
- Health Connect;
- image memory;
- local Qwen/MNN option;
- memory room/data export.

Use for:

- mobile companion UX;
- wearable/health structured context;
- local periodic consolidation.

---

## A4. AionsHome

Repository: https://github.com/death34018-hue/AionsHome

Strong ideas:

- LAN/Tailscale multi-device PWA;
- camera;
- Android bridge;
- local activity logs;
- foreground-window summaries;
- music;
- EPUB reading;
- schedule;
- GPS / POI / weather;
- WebRTC/VAD-style voice bridge.

Use for:

- “companion home hub” scope;
- cross-device life context;
- co-reading/music/location integration.

---

## A5. AILIS

Repository: https://github.com/haowenGuo/AILIS  
License: MIT

Strong ideas:

- companion + reliable personal agent;
- VRM/voice/memory/relationship;
- screen/window/file context;
- approval flow;
- traceable progress;
- recoverable failures;
- long-horizon task execution.

Use for:

- XiaoYu 2.0 “hands.”

---

## A6. Cyrene-Agent

Repository: https://github.com/Playa-Cyrene/Cyrene-Agent

Strong ideas:

- layered memory;
- user profile / recent state / long-term experiences;
- evidence chains;
- conflict resolution;
- Worldbook activation states;
- different operation modes.

Use for:

- memory/profile packaging;
- mode-specific context.

---

## A7. VCPToolBox

Repository: https://github.com/lioensky/VCPToolBox

Strong ideas:

- deep multi-layer memory;
- diary/event timeline;
- active recall;
- distributed plugin engine;
- agent dreams;
- provider/model infrastructure.

Use carefully:

It is much heavier than XiaoYu's desired Core.

Mine ideas, not architecture wholesale.

---

## A8. Hermes Agent

Repository: https://github.com/NousResearch/hermes-agent

Strong ideas:

- one gateway across CLI/TUI/Desktop/bots/cron;
- provider plugins;
- memory provider plugins;
- bounded editable USER/MEMORY files;
- FTS5 session search;
- security scanning of memory;
- skills/plugins;
- channel/session ownership.

Use for:

- provider plugin API;
- memory-provider interface;
- single-gateway channel routing.

---

## A9. AgentOS

Repository: https://github.com/use-agent-os/agent-os

Strong ideas:

- one turn runner across Web/CLI/Slack/Telegram/Discord;
- 20+ model providers;
- skills and MCP loaded on demand;
- local memory;
- durable sessions;
- approvals;
- scheduling/cost.

Use for:

- unified-turn architecture;
- surface adapters.

---

## A10. Thoth

Repository: https://github.com/tokwalabs/Thoth

Strong ideas:

- local-first personal AI OS;
- tools/workflows;
- structured personal knowledge;
- many channels;
- OS credential store;
- plugins/MCP;
- workflow operations.

Use for:

- operations/tooling.

---

## A11. companion-emergence

Repository: https://github.com/hanamorix/companion-emergence

Strong ideas:

- local-first persistent emotional/body state;
- Hebbian-linked memory;
- nightly dreams;
- private journal;
- desktop app;
- ~2.5k tests in its framework;
- experimental encrypted companion-to-companion links kept off by default.

Use for:

- embodied state;
- test discipline;
- experimental social pairing boundaries.

---

## A12. Persisto Mate

Repository: https://github.com/m-rui001/Persisto-Mate

Strong ideas:

- learned body clock;
- sleep;
- dreams;
- ACT-R-inspired memory;
- Plutchik/PAD affect;
- separate affect appraisal;
- impulse heartbeat.

Use cautiously:

These are simulation models, not factual claims of genuine emotion.

---

## A13. Firefly Companion

Repository: https://github.com/iamchunhao618/Firefly-Companion

Strong ideas:

- Windows Live2D;
- streaming response/TTS;
- voice;
- vision;
- relationship state;
- permission-controlled tools.

Use for:

- packaged Windows UX comparison.

---

## A14. Miru

Repository: https://github.com/kiyotakali/Miru  
License: Apache-2.0

Strong ideas:

- auditable memory/journal/attention files;
- screenshot discarded after analysis;
- proactive AttentionEngine;
- self-hosted multi-device;
- Live2D.

Use for:

- privacy-preserving perception;
- auditable presence.

---

## A15. MaiBot

Repository: https://github.com/Mai-with-u/MaiBot

Strong value:

- large Chinese digital-life/community project;
- QQ/social interaction;
- natural conversational presence.

Use for:

- Chinese social style and QQ ecosystem, not as Core authority.

---

# 6. Specialized infrastructure projects that matter

---

## Memory Constellations

Repository: https://github.com/ClaraShafiq/MemoryConstellations

A highly relevant memory architecture:

```
raw message
→ Scribe observation
→ evidence pool
→ Claim review
→ Constellation
→ Episode
→ Saga
→ Facts / Status / Judgment
→ retrieval projection
```

Important principles:

- original messages remain authority;
- model produces proposals, host program commits;
- facts, recent status, and companion judgment are separate publication streams;
- provenance/version/rollback are explicit;
- ambiguous claims remain pending.

This is philosophically very close to XiaoYu.

---

## Serein

Repository: https://github.com/Yinglianchun/Serein

Strong ideas:

- episodic memories preserve recognizability;
- every memory tied to evidence;
- revisions preserve relationship to previous versions;
- story arcs;
- cross-day continuation;
- source trace must survive input → revision → save.

Useful for XiaoYu's future episode/saga layer.

---

## moraine-home

Repository: https://github.com/ceniran/moraine-home

Strong ideas:

- candidate inbox;
- duplicate/conflict review;
- timelines and version history;
- event calendar based on event time;
- core locks;
- decay/archive/restore;
- tiny self-core;
- separate source-linked user profile;
- relationship graph requiring confirmation;
- import/export/snapshot/recovery.

This strongly validates XiaoYu's decision to keep:

```
Identity
User Profile
Memory
Relationship
```

as different state classes.

---

## Personal Model / HUMAN.md

Repository: https://github.com/Intuition-Lab/personal-model

Strong ideas:

- local-first personal model;
- screen/activity evidence;
- SQLite WAL + FTS5 + vector index + provenance;
- deterministic human-readable `HUMAN.md`;
- one personal context layer for multiple agents;
- screen/memory treated as untrusted data;
- no automatic promotion of model-generated skills into executable tools.

Use for:

- portable user-model export;
- source evidence;
- data/control separation.

---

## immortal-skill

Repository: https://github.com/agenmod/immortal-skill  
License: MIT

Strong ideas:

- persona distillation from 12+ data sources;
- separates:
  - procedural knowledge
  - interaction style
  - memories/experiences
  - personality/values
- evidence grading;
- conflict merging;
- relationship-specific consent;
- output as portable Agent Skill.

Use for:

- Companion Bundle import/export;
- external persona migration;
- migration tools.

Do not use it to bypass consent or provenance.

---

## Prosophor

Repository: https://github.com/Swair/prosophor

Strong ideas:

- plugin-driven proactive triggers;
- periodic / idle / idle-once modes;
- trigger scripts separated from LLM execution;
- provider/model/tool/memory/permission/skill systems;
- active-interaction post-processing.

Main XiaoYu lesson:

Use cheap deterministic **trigger detectors** to create proactive candidates.

Do not let every timer invoke an LLM.

---

## Headlong

Repository: https://github.com/laude-institute/headlong  
License: Apache-2.0

Strong ideas:

- persistent agency;
- one continuous trajectory;
- append-only DAG trajectory;
- exponentially decaying context resolution;
- raw history never compacted away;
- skills;
- fork/test/merge self-improvement;
- multi-provider.

Counter-lesson for XiaoYu:

Headlong's fully continuous LLM thinking can cost roughly dollars per hour in the project's own example and has a much broader shell attack surface.

XiaoYu should borrow trajectory/audit ideas, not continuous unbounded thinking.

---

## dsh-see-now

Repository: https://github.com/SAOS-3624/dsh-see-now

Still the preferred screen-perception substrate candidate:

- local change detection;
- selected frames;
- storyboard packing;
- region/watch;
- independent library exports.

---

# 7. Product forms we previously underweighted

---

## 7.1 Companion Space / Home

Representative projects:

- Morrow
- KI-CO
- Fuyue
- SullyOS
- Aery
- LandricSpace
- AionsHome

The common idea:

> the relationship lives in a place, not just a chat transcript.

Typical features:

- room/home
- diary
- keepsakes
- calendar
- shared todo
- photos
- music
- relationship timeline
- letters
- journals

### XiaoYu implication

Do not replace the desktop pet.

But consider a future **XiaoYu Home** surface for:

- memory browsing;
- diary;
- active purposes;
- shared media;
- timeline;
- settings;
- backup;
- companion state.

**Target: 1.x / 2.0**

---

## 7.2 Shared Activities

Representative ecosystem modules:

- co-reading rooms
- book/EPUB annotation
- listen-together music
- film timeline annotation
- journaling
- Pomodoro/focus
- games/TRPG

### Why this matters

Shared activities create **grounded shared experiences**.

This is stronger relationship material than simply asking the model to “act affectionate.”

### XiaoYu implication

High-value 1.x candidates:

1. co-listening / current music context
2. co-reading
3. shared focus/work session
4. shared journal / recap

---

## 7.3 Health / Wearables / Device State

Representative projects:

- Aura + Health Connect
- Akari Pulse
- AionsHome location/activity
- smart-glass/device-node projects

Structured signals can be cheap and useful:

- sleep duration
- steps
- current song
- device battery
- location state
- calendar
- activity class

### Safety implication

Health/location data is sensitive.

It should require:

- explicit source enablement;
- narrow retention;
- memory sensitivity tags;
- no casual cross-context mention.

---

## 7.4 Mobile and Device Nodes

Representative:

- Aura
- Droy
- Scowld
- AionsHome
- Sentient
- Sentient OS
- Anzhi's Phone
- Domia

The architectural pattern is increasingly:

```
one identity/core
+
device nodes advertising capabilities
```

Example device capabilities:

- microphone
- speaker
- camera
- GPS
- notifications
- screen/action

### XiaoYu implication

Future phone/Quest should be **capability nodes**, not independent XiaoYu copies.

---

## 7.5 Social / Visits / Communities

Representative:

- N.E.K.O social/visits direction
- Atrio guest lounge
- companion-emergence Kindled Links
- LandricSpace
- AI companion forums

### Hard prerequisite

Do not build before:

- audience-scoped memory;
- third-party privacy;
- identity linking;
- guest mode;
- outbound permission;
- social delivery ledger.

---

# 8. Portability ecosystem

Three separate portability layers now exist in the ecosystem.

## Persona

Character Card v2/v3.

## User model

Personal Model / HUMAN.md style artifacts.

## Persona + skill distillation

immortal-skill and Agent Skill style packages.

### XiaoYu should eventually export a Companion Bundle

Suggested high-level structure:

```
xiaoyu-bundle/
  manifest
  identity/
  persona/
  user-model/
  memories/
  temporal-facts/
  relationship/
  purposes/
  skills/
  body-references/
  voice-references/
  provenance/
  deletion-tombstones/
```

Secrets must remain excluded.

Not every section should be imported at equal trust.

---

# 9. New ideas that should alter XiaoYu's roadmap

These were not emphasized enough in earlier plans.

---

## 9.1 Sleep / Night Cycle — move to 1.x

Not for roleplay.

A real cycle should:

- consolidate new evidence;
- merge duplicates;
- resolve/flag contradictions;
- update user-profile projection;
- review stale purposes;
- prepare proactive candidates;
- run health/backup checks;
- produce an auditable change report.

Most of this can run without an LLM.

---

## 9.2 Source disconnect → derived-memory deletion

If a source is removed:

- mailbox
- folder
- messaging connector
- device
- imported archive

the user should optionally be able to remove memories derived solely from it.

This should become a 1.x provenance feature.

---

## 9.3 Context spaces

Instead of one global memory scope, add:

- GLOBAL
- PERSONAL
- WORK
- PROJECT:<id>

Later add audience scopes separately.

A task/conversation inherits a context space.

This reduces irrelevant or privacy-inappropriate recall.

---

## 9.4 Companion Home

Future surface for:

- timeline
- memories
- diary
- purpose queue
- shared activities
- keepsakes
- health/status
- backup/export

Do not make it a separate brain.

---

## 9.5 Shared Activity Layer

Add a generic activity record:

```
activity_id
type
started_at
ended_at
participants
artifact_refs
notes
memory_candidates
```

Examples:

- listened to song
- read chapter
- watched film
- focus session
- played game

This gives XiaoYu real shared-history anchors.

---

## 9.6 Hibernation / graceful separation

Mirrai-like “graduation” ideas suggest a useful product state:

```
ACTIVE
HIBERNATING
ARCHIVED
```

Hibernation:

- stops proactivity;
- freezes recurring jobs;
- retains identity;
- remains exportable;
- can be resumed.

This is healthier and operationally cleaner than “must always be awake forever.”

---

## 9.7 Compute mobility

Domia/Sentient/device-node patterns suggest:

> identity and compute location are different things.

Future:

```
XiaoYu identity stays canonical
task may run on:
  laptop
  desktop GPU
  server
  phone
  remote provider
```

Capability routing should consider where compute is available without moving identity authority.

---

# 10. What should NOT change because of this survey

The broader landscape does **not** justify:

- migrating XiaoYu to AIRI/N.E.K.O/DSH/Hermes;
- adding another memory authority;
- turning relationship state into arbitrary numeric affection;
- running continuous expensive LLM inner monologue;
- enabling group/social features before audience privacy exists;
- default 24/7 screen recording;
- auto-admitting learned skills;
- making every product surface a separate agent.

---

# 11. Reference matrix

Legend:

- ★★★ = defining strength
- ★★ = mature/relevant
- ★ = present/partial

| Project | Identity | Provenance Memory | Proactivity | Body/Voice | Perception | Action/Safety | Plugins/Skills | Multi-device | Product UX |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AIRI | ★★ | ★ | ★★ | ★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ |
| N.E.K.O | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★ | ★★★ | ★★★ | ★★★ |
| V1rtual-Desk-Pet | ★★ | ★★★ | ★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★ | ★★★ |
| Sentient | ★★ | ★★★ | ★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★★ |
| Sentient OS | ★ | ★★★ | ★★★ | ★ | ★★★ | ★★★ | ★★ | ★★ | ★★★ |
| Alicization | ★★★ | ★★ | ★★★ | ★★ | ★★ | ★★★ | ★★ | ★ | ★★ |
| Nexus | ★★ | ★★★ | ★★★ | ★★ | ★★★ | ★★ | ★ | ★★ | ★★★ |
| Tamanitomo | ★★★ | ★★★ | ★★★ | ★★ | ★★ | ★★ | ★★ | ★★ | ★★★ |
| MIRA | ★★ | ★★★ | ★★★ | ★★ | ★ | ★★★ | ★★★ | ★★★ | ★★★ |
| YuriOS | ★★★ | ★★ | ★★★ | ★★★ | ★★ | ★★ | ★★ | ★ | ★★★ |
| MIRROW | ★★ | ★★★ | ★★★ | ★★ | ★★ | ★★ | ★★ | ★ | ★★★ |
| Morrow | ★★ | ★★ | ★★★ | ★ | ★ | ★★ | ★★ | ★★ | ★★★ |
| Aura | ★★ | ★★ | ★★ | ★ | ★★★ | ★ | ★★ | ★★★ | ★★★ |
| AILIS | ★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★ | ★ | ★★★ |
| Cyrene-Agent | ★★ | ★★★ | ★★ | ★★ | ★★ | ★★ | ★★ | ★ | ★★ |
| VCPToolBox | ★★ | ★★★ | ★★★ | ★ | ★★ | ★★ | ★★★ | ★★ | ★★ |
| Hermes Agent | ★★ | ★★ | ★★ | ★ | ★ | ★★★ | ★★★ | ★★★ | ★★ |
| companion-emergence | ★★★ | ★★ | ★★ | ★★★ | ★ | ★★ | ★ | ★★ | ★★ |
| Persisto Mate | ★★★ | ★★ | ★★★ | ★ | ★ | ★ | ★ | ★ | ★★ |
| AionsHome | ★★ | ★★ | ★★ | ★★ | ★★★ | ★★ | ★★ | ★★★ | ★★★ |
| Miru | ★★ | ★★★ | ★★★ | ★★★ | ★★★ | ★ | ★ | ★★★ | ★★★ |
| Firefly Companion | ★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★ | ★ | ★★★ |

This table is qualitative architecture triage, not a benchmark ranking.

---

# 12. XiaoYu's strongest differentiated combination

After surveying this ecosystem, none of the representative projects clearly combines all of the following as first-class, rigorously evaluated layers:

```
model-independent identity authority
+
source-grounded memory authority
+
human-confirmed persona evolution
+
temporal correction/freshness
+
answer/evidence contract
+
prospective frozen evaluation
+
calibrated proactivity
+
replaceable capability providers
+
cross-surface same identity
+
verified skills/effects
```

Many projects are stronger than XiaoYu in individual layers.

That is useful: XiaoYu should reuse their solved product/engineering patterns rather than reproduce them.

---

# 13. Final priority of projects to mine

## Deep source study now

1. V1rtual-Desk-Pet
2. N.E.K.O
3. AIRI
4. Sentient
5. MIRA
6. Tamanitomo
7. Nexus
8. Sentient OS

## Deep study for memory/user model

9. Memory Constellations
10. Serein
11. moraine-home
12. Personal Model

## Study for autonomy/inner-life experiments

13. YuriOS
14. Alicization
15. MIRROW
16. Headlong
17. Persisto Mate

## Study for surfaces/product experience

18. Morrow
19. AionsHome
20. Aura
21. Miru
22. AILIS
23. Firefly Companion

## Study only when entering relevant phase

- Domia → device mesh / compute mobility
- immortal-skill → import/persona portability
- Prosophor → proactive trigger plugins
- SillyTavern ecosystem → character cards/worldbooks/roleplay UX
- social/visit projects → after audience/privacy work
- hardware robot projects → after Quest/mobile/device-node work

---

# 14. Saturation criterion reached

The final search rounds produced new projects such as:

- ZapMomo
- AIPet
- OpenCompanion
- Firefly Companion
- Moepet
- xiaokeai
- Droy
- XiaoQi

but their mechanisms mapped cleanly to already-known categories:

- voice
- body
- memory
- perception
- proactive behavior
- tools/permissions
- local-first deployment
- mobile/device surfaces

No additional fundamental state class or architecture boundary was required.

The remaining research problem is therefore **not discovery**.

It is empirical comparison and source mining:

```
choose reference project
→ inspect exact implementation
→ isolate reusable mechanism
→ map to XiaoYu contract
→ benchmark / regression-test
→ adopt only if net-positive
```

This document therefore marks the open-source ecosystem survey as **LANDSCAPE_SATURATED_2026-11-18**.


---

# 15. Late saturation additions

## S11. OpenAlma

Repository: https://github.com/mekineer-com/OpenAlma  
License: GPL-3.0

OpenAlma is one of the closest newly found whole-product references.

Verified from its current README:

- one always-present local memory/orchestration service;
- multiple clients (SillyTavern / WhatsApp / Iris / others);
- conversations become episodes;
- people/topics/patterns become revisable dossiers;
- sleep-gap automatic extraction;
- memory injected automatically into later turns;
- entity graph + temporal queries;
- life goals separated from active intentions;
- SPEAK/LISTEN gating;
- cross-chat awareness;
- photo memory / visual recall lane;
- manual record-and-review mode;
- Atomic Mind Map for entity/dossier curation;
- staged reflection/consolidation;
- launcher-managed backup/migration/rollback behavior.

### XiaoYu relevance

High-value ideas:

- dossiers as human-readable evidence-linked projections;
- goal vs intention separation;
- cross-surface awareness;
- reviewable visual memory;
- sleep-gap consolidation;
- entity/dossier curation UI.

Do not adopt OpenAlma as a new Core. Its memory engine remains a separate architectural choice, while XiaoYu already has stronger existing provenance/governance foundations.

GPL-3.0 also makes direct code reuse a separate licensing decision; architecture/mechanism study is the cleaner default.

---

## B-tier direct comparator: Serenity

Repository: https://github.com/RECTDEV/serenity  
License: custom CC BY-NC-derived community license / commercial license path

Serenity is a direct whole-product companion comparator with:

- local Ollama inference;
- cross-session vector memory;
- voice/wake word;
- screen/camera vision;
- Telegram/WhatsApp;
- Obsidian integration;
- cron/reminders;
- proactive reach-out;
- autonomous goals;
- curiosity loop;
- periodic dream/consolidation cycle;
- emotional state variables;
- skills.

### XiaoYu relevance

It validates user demand for one persistent agent spanning personal/work/coding/voice/messaging.

However, its public architecture centers vector memory and comparatively free-running autonomous/emotional loops. These mechanisms do not overturn XiaoYu's stronger decisions around:

- source authority;
- temporal correction;
- calibrated proactivity;
- verified SkillBank admission;
- code-enforced permissions;
- evidence-based persona change.

Treat Serenity as a feature/product comparator and a counterexample for what must be gated, not as a Core architecture target.

---

# 16. Physical / wearable saturation result

Final hardware/wearable scans did not introduce a new durable memory type, but they exposed a new **access boundary**:

```
Principal Resolution
```

When a device has microphones/cameras in a shared environment, XiaoYu must distinguish:

- authenticated owner;
- recognized-but-not-strongly-authenticated speaker;
- known guest;
- unknown person;
- multi-person audience.

Speaker identification can assist but must not be treated as definitive authentication.

This requirement is now recorded in the architecture-delta document.

---

# 17. Final landscape saturation status

After adding:

- OpenAlma;
- Serenity;
- personal-agent runtimes;
- Wasm/container tool runtimes;
- realtime voice frameworks;
- shared-activity ecosystems;
- guest-lounge patterns;
- multi-device CoreNode/Host designs;
- wearable/hardware projects;

new discoveries no longer introduce a new fundamental XiaoYu durable state family.

They map into:

```
SELF
USER MODEL
MEMORY
GOALS / INTENTIONS / PURPOSE
SKILLS
WORLD / PERCEPTION
EXECUTION STATE
PRINCIPAL / AUDIENCE CONTEXT
SHARED ACTIVITY
```

The open-source landscape is therefore considered saturated for **architecture and project-class discovery** as of 2026-11-18.

Individual implementation source mining can continue when a concrete XiaoYu module is being built, but that is no longer landscape discovery.
