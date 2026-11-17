# XiaoYu v0.3 Saturation Re-Audit & Product-Mechanism Delta

**Date:** 2026-11-18
**Status:** DRAFT DELTA — applies on top of `IMPLEMENTATION_SPEC_V0_2.md`
**Purpose:** record the final red-team pass against current commercial companions, open-source companions, household/personal agents, wearable memory products, and 2026 longitudinal/memory/security research.

---

# 0. Honest saturation statement

The previous v0.2 architecture remains valid, but “everything has been investigated” was too strong.

The correct claim is:

- **Core authority/state architecture:** saturated enough to freeze.
- **Runtime/provider/plugin architecture:** saturated enough to freeze.
- **Product-mechanism coverage:** not previously complete; this delta closes the remaining high-value gaps found in the red-team pass.
- **Literal enumeration of every companion product/repository:** impossible and not a useful saturation criterion.

Saturation is reached when additional products map to already-known mechanism classes and no longer force a new durable state class, authority boundary, execution primitive, or product lifecycle contract.

---

# 1. Coverage model used for the re-audit

The re-audit covered these families, not only “AI girlfriend” apps:

1. commercial relationship-first companions;
2. local/self-hosted companions;
3. desktop/avatar/VTuber companions;
4. general personal agents with companion qualities;
5. household/group agents;
6. mobile/device-node agents;
7. wearable/lifelog memory systems;
8. game/co-play companions;
9. social/companion-network systems;
10. memory backends and personalized-agent benchmarks;
11. relationship-formation/longitudinal research;
12. plugin/MCP/skills/Wasm/A2A ecosystems;
13. release/update/backup/security lifecycle.

Representative systems include Replika, Nomi, Kindroid, Character.AI, N.E.K.O, YuriOS, Tamanitomo, AILIS, AIRI, Miru, Operit, Open-LLM-VTuber, Google CC, Apple household-personalization patterns, Limitless-style wearable memory, and public memory/agent evaluation systems.

---

# 2. New product-mechanism gaps found

## D25. Promise Ledger — first-class commitments

A companion must remember **its own promises**, not only the user's tasks.

Add a distinct semantic source for promises:

```
Promise
  promise_id
  speaker_actor
  source_event_id
  commitment_text
  due_window optional
  state
  linked_purpose_id
  provenance
```

States:

```
OPEN
WAITING
FULFILLED
BROKEN
CANCELLED
SUPERSEDED
```

Rules:

1. a model sentence beginning “I’ll…” does not automatically authorize action;
2. it may create a Promise candidate;
3. accepted Promise creates/links a bounded Purpose where execution is required;
4. Promise can remain non-executable (e.g. “I’ll remember that”);
5. broken/expired promises remain auditable instead of silently disappearing.

Why this matters: companion products such as YuriOS treat self-promises as explicit provenance-bearing goals. This is relational continuity, not ordinary reminders.

**1.0:** schema + extraction for explicit commitments only.
**1.x:** richer promise repair/renegotiation.

---

## D26. Memory Control Plane — user-visible revisions, priority and provenance

The Memory UI in v0.2 is insufficiently specific.

Add a stable user-facing control model inspired by Nomi/Kindroid/Replika patterns, but keep XiaoYu authority semantics.

For every user-visible projection/memory:

```
current_value
source_evidence
created_at
last_updated_at
revision_history
priority
status
why_active
```

Priority is a retrieval control, not truth:

```
PINNED
NORMAL
LOW
MUTED
```

Required operations:

- inspect;
- correct;
- pin/high-priority;
- mute/low-priority;
- archive;
- retract/delete;
- show revision diff;
- one-click revert a **projection edit** while preserving event provenance.

A user edit creates a new authoritative owner event; it does not rewrite old evidence.

Do not copy Nomi Mind Map as a second authority. Implement an evidence-linked graph/table projection only if useful.

---

## D27. Companion Journal / Presence Ledger — observable “life between chats”

Several mature local companions converge on journals/presence because invisible autonomy is hard to trust.

Add a **derived** companion-life surface:

```
PresenceEntry
  interval
  state
  active_purpose_ids
  activity_summary
  source_events/effects
  confidence

JournalEntry
  date
  narrative
  source_event_ids
  source_activity_ids
  model_version
  status
```

Rules:

1. Journal is a projection/narrative, never truth authority.
2. Journal must link to evidence.
3. “Nothing happened” is valid; never fabricate a life event.
4. No free-running expensive inner monologue is required.
5. User can inspect what XiaoYu actually did while away.

**1.0:** status/activity history can satisfy this without prose journal.
**1.x:** optional bounded nightly narrative.

---

## D28. Relationship Lifecycle — support formation, stability, distance and exit

Current RelationshipState needs lifecycle semantics without turning human emotion into fake numeric truth.

Suggested states:

```
NEW
FAMILIAR
ESTABLISHED
DISTANT
PAUSED
ENDED
```

These are interaction-policy states, not claims about human love/intimacy.

Store:

```
relationship_state
effective_from
source_events
interaction_preferences
boundaries
proactivity_policy
```

Required transitions include:

- user asks for more/less contact;
- long absence;
- return after pause;
- explicit “stop contacting me”;
- reset/archive/end;
- resume by explicit user action.

Do not implement “affection XP”, “love score”, or manipulative streak mechanics as authority.

This absorbs useful relationship-stage ideas from commercial companions while avoiding gamified dependency.

---

## D29. Offboarding / Pause Contract

Make exit a first-class product path.

Operations:

```
MUTE_PROACTIVITY
PAUSE_RELATIONSHIP
PAUSE_ALL_BACKGROUND_ACTIVITY
EXPORT_IDENTITY
EXPORT_MEMORY
RESET_RELATIONSHIP_PROJECTION
DELETE_SELECTED_MEMORY
DELETE_ALL_MANAGED_STATE
```

Rules:

- no guilt language;
- no escalating re-engagement attempts;
- no loss of export access because relationship is paused;
- background loops respect pause immediately;
- resume is explicit and auditable.

This is both UX and safety.

---

## D30. Context Space + Audience Scope matrix becomes mandatory before group/social features

Nomi, Kindroid, N.E.K.O and household agents reinforce that group conversation is not merely “another surface”.

For every durable candidate/event distinguish:

```
context_space
audience_scope
principal_set
visibility
memory_promotion_policy
```

Examples:

```
PERSONAL(owner)
GROUP(friend_group_1)
VISIT(companion_visit_2026...)
HOUSEHOLD
PROJECT(x)
```

Invariant:

Private owner evidence may influence owner-private generation, but must not silently affect guest/group generation through hidden profile state.

Before any group-chat release, add **Audience Context Reset**:

- clear private retrieval set;
- clear private profile projection from prompt assembly;
- clear provider session/KV when required;
- recompute permitted tools/delegations.

---

## D31. Multi-companion namespace — architecture compatibility only

Some products support multiple independent companions.

XiaoYu 1.0 remains one companion.

However, avoid schema assumptions that make a future second companion impossible.

Add `identity_id` / `companion_id` namespace to new authority tables where absent or ensure DB-level authority can be migrated cleanly.

Do **not** build multi-companion UI/runtime now.

Reason: this is cheap future-proofing, not scope expansion.

---

## D32. Shared Activities become a product primitive, not merely a ledger

Existing Shared Activity Ledger is correct but underspecified at UX level.

Define a common session contract:

```
activity_id
activity_type
participants
context_space
subject_ref
position/timeline
started_at
ended_at
artifacts
annotations
source_events
memory_candidates
```

Initial activity families:

- listening/music;
- co-reading;
- focus/work;
- game/co-play;
- watch/film later.

Required product rule:

Activity state is not chat history. It generates evidence that can later become memories.

N.E.K.O's co-play/social visit patterns and companion products' shared activities support this separation.

---

## D33. Multimodal Memory Authority

MOSAIC/VideoMemBench-style evidence shows that multimodal memory fails at multiple stages: representation, retrieval, delivery, reading.

Do not reduce future visual/audio memory to a text summary only.

Define:

```
MultimodalEvidenceRef
  modality
  source_id
  time_range
  content_digest
  derived_text optional
  retention_class
  privacy_class
```

For 1.0 Vision:
- raw media remains transient by default;
- semantic observation may become a candidate;
- provenance must preserve that it came from visual/audio evidence.

For future persistent multimodal memory, evaluation must separately measure:
- representation loss;
- retrieval loss;
- delivery/context loss;
- final reasoning loss;
- abstention.

---

## D34. Onboarding is a reliability subsystem

Tamanitomo/AIRI and commercial companions show that feature-rich systems can fail before first value because configuration is too complex.

Define a 1.0 onboarding success path:

```
install/start
-> provider connectivity
-> identity loaded
-> one conversation
-> one memory created/inspected
-> one optional proactive/purpose example
-> backup/status visible
```

Progressive disclosure:

Basic setup first. Advanced provider/router/memory/security controls stay hidden until needed.

Measure:
- first successful turn;
- first remembered detail;
- first recovery;
- setup failure reason.

No false “configured successfully” message before an operation is verified.

---

## D35. Continuity Migration Gate becomes product-facing

Model/provider continuity is not only a release test.

When switching a major model family, expose:

```
CURRENT MODEL
CANDIDATE MODEL
continuity test result
known behavior deltas
rollback
```

The companion must not claim identity continuity merely because state files loaded.

Promotion requires behavioral regression on:
- identity;
- relationship boundaries;
- memory use;
- tool/permission behavior;
- style-critical invariants.

---

## D36. Digital Legacy / Long-term Inactivity policy — later, but now reserve semantics

A long-lived personal identity system eventually faces:
- abandoned device/account;
- prolonged inactivity;
- owner death/incapacity;
- export or destruction wishes.

Do not build this for 1.0.

Reserve a future policy object:

```
LegacyPolicy
  inactivity_behavior
  export_delegate optional
  deletion_policy
  posthumous_access_policy
  disabled_by_default
```

Default is no posthumous simulation or third-party access.

This is a later lifecycle requirement, not a current companion feature.

---

# 3. Product feature inventory for acceptance

Use a product-level inventory in addition to technical gates.

## Pre-use
1. installation/onboarding;
2. privacy visibility;
3. provider/data locality;
4. identity/persona setup.

## Initiation
5. user starts conversation;
6. companion-initiated contact;
7. return after absence;
8. quiet-space behavior.

## Exploration
9. discoverability/tutorials;
10. customization;
11. memory inspection/correction;
12. limitations and boundaries.

## Intensification / long-term continuity
13. memory;
14. temporal understanding;
15. multimodal communication;
16. voice interruption/turn-taking;
17. relationship continuity;
18. shared activity;
19. promises/commitments;
20. recovery from mistakes.

## Mature use
21. cross-surface continuity;
22. purpose/task follow-through;
23. user control over proactivity;
24. offboarding/pause/export;
25. provider/model upgrade continuity.

Do not optimize engagement time as the product objective.

---

# 4. Product references and what to absorb

## Replika
Absorb:
- clear relationship-first product focus;
- user-visible memory controls;
- diary/backstory UX inspiration.

Do not absorb:
- cloud dependence or any engagement-maximizing behavior as authority.

## Nomi
Absorb:
- visible high-level memory projection;
- user correction/priority;
- revision-history/revert concept;
- identity continuity treated as a product problem;
- separate group/private memory contexts.

Do not absorb:
- Mind Map as truth authority.

## Kindroid
Absorb:
- distinct short/medium/retrievable memory roles;
- proactive timing/space requests;
- group/shared-context product lessons.

Do not copy proprietary cascaded-memory architecture without measured benefit.

## Character.AI
Absorb:
- very simple user-pinned-memory control.

XiaoYu can implement this more rigorously through evidence-linked priority.

## N.E.K.O
Absorb:
- cross-device same-companion framing;
- group-aware memory;
- visits/shared rooms as context-space examples;
- games/co-play and plugin ecosystem as future Shared Activity/Skill use cases.

Do not let social/community state become identity authority.

## YuriOS
Absorb:
- explicit promises;
- user-readable goals;
- journal/status for ambient life;
- night maintenance as bounded optional runtime.

Do not adopt free-running costly mind loops by default.

## Tamanitomo
Absorb:
- deterministic zero-LLM background routines;
- outbox/recoverable operations;
- local auditability;
- onboarding/product-readiness lesson;
- explicit contact limits;
- update without overwriting companion state.

Do not adopt heuristic emotion meters as canonical truth.

## AILIS
Absorb:
- companion + reliable agent unification;
- approval/recovery/evidence product UX;
- context compaction regression discipline;
- rollbackable release manifests.

## AIRI
Absorb:
- voice/plugin lifecycle engineering;
- separated provider adapters;
- avatar/body ecosystem ideas.

Do not rebuild its host runtime.

## Miru
Absorb:
- multi-device self-hosted pattern;
- auditable attention/mood/journal projections;
- raw screenshot discard pattern.

## Operit
Absorb:
- Android/device-agent lessons;
- Skill/workflow/backup marketplace mechanics;
- workspace rollback ideas.

Do not expand XiaoYu 1.0 into a full mobile automation OS.

## Household agents
Absorb:
- per-principal context;
- shared vs private state;
- guest/household separation.

## Wearable memory systems
Absorb:
- capture indication;
- offline buffering;
- explicit bystander consent/retention;
- sensor-state lifecycle.

---

# 5. Revised saturation stop test

After this re-audit, a new product/repository should reopen architecture only if it demonstrates at least one of:

1. a durable state family not expressible by current Core;
2. an authority/provenance boundary stronger than current event->claim->fact model;
3. a relationship lifecycle primitive not expressible by Relationship/Promise/Purpose/Activity;
4. a new actor/principal/delegation requirement;
5. a safer execution/isolation primitive;
6. a cross-device consistency requirement impossible under single authoritative Core;
7. a user-visible capability impossible under Capability Contract;
8. reproducible order-of-magnitude cost/resource improvement;
9. evidence that a current acceptance gate is measuring the wrong product outcome.

Otherwise classify it as:
- provider candidate;
- UX reference;
- benchmark;
- implementation reference;
- future surface.

---

# 6. Implementation priority impact

## Add before 1.0 freeze
- Promise candidate/ledger minimal semantics;
- memory priority/control semantics;
- onboarding verified-success path;
- relationship pause/offboarding semantics;
- `companion_id` namespace compatibility;
- multimodal evidence provenance type;
- audience context reset invariant.

## 1.0 product UI if time allows
- memory revision/priority UI;
- activity/status page;
- explicit pause proactivity.

## 1.x
- narrative journal;
- shared activities UI;
- group/social/visit contexts;
- richer relationship lifecycle;
- persistent multimodal memory;
- digital legacy policy.

No change to the fundamental v0.2 Core/Runtime split is required.
