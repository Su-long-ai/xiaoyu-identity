# XiaoYu Reference Project Mining Plan

**Date:** 2026-11-18  
**Purpose:** turn the saturated open-source landscape into targeted source-reading work.  
**Rule:** study mechanisms, not brands. No external project becomes a new XiaoYu host.

---

# 1. V1rtual-Desk-Pet

Repository: https://github.com/V1rtual-Klavte/Desk-Pet

## Mine

- Rust native-host / Node harness ownership boundary
- Windows named-pipe IPC
- host command/request/event contracts
- lazy MCP/Skill loading
- source-linked memory UI
- correction/forgetting invalidation
- proactive budget / quiet time / unread backoff
- safety level implementation and confirmation UI
- packaged runtime/update design

## XiaoYu target

- Capability sidecar/host contract
- permission UI
- proactive UX
- memory visibility
- process packaging

## Do not copy blindly

- its own personality/card semantics
- memory authority rules that conflict with XiaoYu provenance

---

# 2. N.E.K.O

Repository: https://github.com/Project-N-E-K-O/N.E.K.O

## Mine

- event log / outbox / restart replay
- idempotent writes
- memory hybrid retrieval
- evidence scoring
- contradiction correction
- plugin SDK/manager
- device sync
- social visit boundaries

## XiaoYu target

- effect ledger
- delivery ledger
- plugin packaging
- restart/recovery

---

# 3. AIRI

Repository: https://github.com/moeru-ai/airi

## Mine

- Plugin Host
- Capability Model
- control plane / data plane
- local vs remote plugins
- multi-device orchestration
- audio/visual high-throughput path

## XiaoYu target

- Capability Contract v1
- separate high-frequency media data path from control RPC

---

# 4. Sentient

Repository: https://github.com/existence-master/Sentient

## Mine

- single SQLite state ownership
- one agent loop across surfaces
- task restart/resume
- cheap watchers
- user model with evidence/reasons
- nightly consolidation
- skill verification before save
- source disconnect deletion propagation
- Personal/Work/Project memory scopes
- device node protocol

## XiaoYu target

- context spaces
- provenance-aware deletion
- durable-task design
- SkillBank admission
- device capability nodes

---

# 5. MIRA

Repository: https://github.com/Vexillon-ai/MIRA

## Mine

- provider/channel/tool/skill traits
- external channel provider protocol
- identity linking
- signed skill packages
- per-skill secrets
- restricted fail-closed mode
- memory provider SPI trust tiers
- encrypted backup/two-phase restore

## XiaoYu target

- provider contract
- restricted mode
- third-party plugin trust
- memory-source trust tiers

---

# 6. Tamanitomo

Repository: https://github.com/tamanitomo/tamanitomo

## Mine

- zero-LLM background routines
- fingerprint-based wake
- independent outbox gate
- quiet-hour/daily quota enforcement
- vault Git history
- evidence-backed owner facts
- doctor/status UX

## XiaoYu target

- Purpose runtime
- proactive cost control
- local audit/recovery
- status dashboard

---

# 7. Nexus

Repository: https://github.com/FanyinLiu/Nexus

## Mine

- coarse ambient sensing
- short retention
- proactive decision vs delivery split
- duplicate/expired suppression
- contradiction/downweight consolidation
- deletion propagation
- release-level test strategy

## XiaoYu target

- Vision privacy
- proactive abstention
- deletion gate

---

# 8. Sentient OS

Repository: https://github.com/Sentient-OS-Labs/sentient-os

## Mine

- overnight wake
- checkpoints/resume
- local first-pass triage
- personal knowledge projection
- proactive preparation without auto-execution
- computer-use visible STOP
- privacy data flow

## XiaoYu target

- Sleep/Night Cycle 1.x
- local structured context ingestion
- prepared-suggestion pattern

---

# 9. Memory Constellations

Repository: https://github.com/ClaraShafiq/MemoryConstellations

## Mine

- raw → observation → claim → episode → saga
- facts/status/judgment split
- CAS/lease write gates
- projection publication

## XiaoYu target

- future episode/saga layer
- relationship judgment separated from facts

---

# 10. Serein

Repository: https://github.com/Yinglianchun/Serein

## Mine

- exact source preservation
- revision lineage
- story-arc organization
- end-to-end provenance verification

## XiaoYu target

- episodic memory evolution

---

# 11. moraine-home

Repository: https://github.com/ceniran/moraine-home

## Mine

- candidate inbox
- confirmable relationship graph
- event-time calendar
- self-core vs user profile
- snapshots/recovery

## XiaoYu target

- profile/relationship state UX
- temporal inspection UI

---

# 12. Personal Model

Repository: https://github.com/Intuition-Lab/personal-model

## Mine

- HUMAN.md deterministic projection
- provenance indexes
- personal context shared to multiple agents
- data/control separation
- screen capture privacy model

## XiaoYu target

- user-model export
- provider-neutral personal context

---

# 13. YuriOS / Alicization / MIRROW

Study together as an “inner-life” comparison.

## Compare

- what wakes without user input
- which routines need LLM
- how state changes are recorded
- how proactive decision is made
- how dream/consolidation differs from fabricated narrative
- what is auditable
- how cost is bounded

## XiaoYu target

Design one minimal Sleep/Night Cycle, not three overlapping autonomy loops.

---

# 14. Morrow / AionsHome / Aura

Study together as “companion home/mobile” product references.

## Compare

- PWA/mobile home
- diary/timeline
- memories UI
- music/reading
- health/location
- push notifications
- backup/export
- onboarding

## XiaoYu target

Future XiaoYu Home surface.

---

# 15. Headlong / Prosophor

Study as counterposed proactive architectures.

## Headlong

Continuous self-guided LLM thought stream.

## Prosophor

Cheap deterministic trigger plugins wake an agent.

## XiaoYu conclusion to test

Prefer Prosophor/Tamanitomo-like trigger candidates by default.

Reserve free-running LLM thought for explicitly bounded experiments.

---

# 16. Deliverables from each deep dive

Each project study should produce only:

1. mechanism description
2. exact files/modules
3. state ownership
4. data flow
5. failure handling
6. security boundary
7. resource/cost behavior
8. license constraints
9. XiaoYu mapping
10. adopt / adapt / reject decision

Avoid collecting screenshots or marketing features without implementation relevance.

---

# 17. Stop rule

A reference project is considered mined when:

- all mechanisms relevant to XiaoYu have a source-level map;
- no remaining source section is likely to change the adopt/adapt/reject decision.

Do not study every project in the ecosystem.

The landscape is saturated; source mining should now be **mechanism-driven**.
