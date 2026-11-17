# XiaoYu Final Architecture & Implementation Spec V1

**Date:** 2026-11-18  
**Status:** FINAL FREEZE CANDIDATE  
**Purpose:** consolidate v0.2 implementation spec, v0.3 product-mechanism re-audit, and the final adversarial saturation pass into one implementation authority.

This document is the implementation authority for XiaoYu 1.0 unless a later decision explicitly supersedes it.

---

# 0. Freeze statement

The architecture is now frozen at the level of:
- authority boundaries;
- durable state families;
- public contracts;
- execution semantics;
- release/recovery semantics.

New projects, papers or providers do **not** reopen architecture unless they demonstrate:
1. a new durable state family not expressible here;
2. a materially stronger authority/provenance boundary;
3. a safer execution/isolation primitive;
4. a product capability impossible under current contracts;
5. an order-of-magnitude measured resource/cost improvement;
6. reproducible evidence that a current gate measures the wrong product outcome.

Everything else is classified as provider candidate, UX reference, benchmark, implementation reference or future surface.

---

# 1. Final system shape

```
Surfaces
  Desktop / QQ / Voice / Vision / future Mobile / Guest / Device
        |
        v
InputSourceEnvelope
        |
        v
Principal Resolution
        |
        v
Audience Authorization
        |
        v
+-----------------------------+
| XiaoYu Semantic Core        |
|-----------------------------|
| Identity / Persona          |
| Canonical Event             |
| Claims / Temporal Truth     |
| Memory Authority            |
| Profile Projection          |
| Relationship State          |
| Promise Ledger              |
| Goal / Intention / Purpose  |
| Shared Activity             |
| Authorization Semantics     |
| Effect Semantics            |
| Erasure Semantics           |
+-----------------------------+
        |
        v
+-----------------------------+
| XiaoYu Runtime Host         |
|-----------------------------|
| Capability Registry         |
| Provider Router             |
| Sidecar Supervisor          |
| Resource Broker             |
| Power Lifecycle             |
| Scheduler                   |
| Outbox Dispatcher           |
| Retry / Circuit Breaker     |
| Context Assembly/Compaction |
| Telemetry                   |
+-----------------------------+
        |
        +-- Providers: LLM / Retrieval / Vision / ASR / TTS / Body
        +-- Tools: first-party / MCP / future Wasm
        +-- future Device Nodes / A2A adapter

Independent:
  Guardian / Sentinel
  Release Authority
```

One identity authority. One event authority. One durable memory truth. One purpose/effect authority.

No surface, provider, model, plugin, journal, graph, summary or UI becomes a second brain.

---

# 2. Durable state families

## 2.1 SELF
- identity;
- immutable/slow persona authority;
- persona version history.

## 2.2 USER MODEL
- stable preferences;
- habits;
- important people;
- active long-term projects;
- interaction/proactivity preferences.

Always evidence-linked and rebuildable where derived.

## 2.3 RELATIONSHIP
Per-principal:
- relationship lifecycle state;
- shared-history projection;
- interaction norms;
- boundaries;
- proactivity policy;
- evidence.

Lifecycle:
```
NEW
FAMILIAR
ESTABLISHED
DISTANT
PAUSED
ENDED
```

These are interaction-policy states, not numeric claims about human emotion.

## 2.4 MEMORY / TRUTH
- canonical raw events;
- semantic claims;
- temporal facts;
- episodic memories;
- source provenance;
- corrections/retractions/deletions;
- projections/dossiers/indexes.

Canonical chain:
```
Event -> Claim -> Authoritative Mutation -> Temporal Fact -> Projection
```

## 2.5 PROMISE
XiaoYu's own explicit commitments.

```
OPEN
WAITING
FULFILLED
BROKEN
CANCELLED
SUPERSEDED
```

A model sentence does not automatically authorize an effect. A Promise may link to a Purpose.

## 2.6 GOAL / INTENTION / PURPOSE
```
Goal      = long-lived direction
Intention = selected bounded effort
Purpose   = concrete pending commitment/watch/reminder/task
```

Owner:
```
USER
XIAOYU
SHARED
```

Only Intention/Purpose may become execution candidates.

## 2.7 SHARED ACTIVITY
Generic structure for:
- music/listening;
- reading;
- focus/work;
- game/co-play;
- later film/watch/events.

Activity produces evidence and memory candidates; it is not chat history.

## 2.8 WORLD / PERCEPTION
1.0:
- transient sensor observations with TTL.

Future embodied/VR/device mode:
- persistent spatial-semantic world model;
- room/object/place identity;
- last-seen time;
- location confidence;
- source evidence.

Persistent spatial memory is a future sub-authority of WORLD state, not a replacement for episodic memory.

## 2.9 EXECUTION
- delegations;
- authorization decisions;
- effect intents;
- outbox rows;
- receipts;
- verifier state;
- deliveries.

## 2.10 PRINCIPAL / AUDIENCE
- authenticated/estimated user;
- viewers;
- session scope;
- context space;
- audience scope.

---

# 3. Core implementation rules

1. No big-bang rewrite.
2. Existing entry points remain compatibility facades until migration passes regression.
3. Durable truth is append/correct/retract, not silent rewrite.
4. Derived state is rebuildable.
5. LLMs propose; deterministic policy commits.
6. External effects are crash-safe.
7. User deletion is propagated through managed backups/projections.
8. Provider/model replacement never changes identity authority.
9. Private context never falls back to privacy-ineligible providers.
10. Every contract has conformance tests.

---

# 4. Target package layout

```
xiaoyu/
  contracts/
  core/
    identity.py
    events.py
    claims.py
    temporal.py
    memory.py
    profile.py
    relationship.py
    promise.py
    purpose.py
    activity.py
    authorization.py
    effects.py
    erasure.py
  persistence/
    db.py
    schema.py
    migrations/
    repositories/
  runtime/
    host.py
    router.py
    provider_registry.py
    supervisor.py
    resources.py
    power.py
    scheduler.py
    outbox.py
    circuit_breaker.py
    context.py
    telemetry.py
  providers/
  tools/
  surfaces/
  release/
  guardian/
  tests/
```

Compatibility facades:
- `identity_core.py`
- `product_memory_bridge*.py`
- `model_adapter.py`
- `send_guard.py`
- `companion.py`

---

# 5. InputSourceEnvelope

Every inbound input is normalized before Core.

Required fields:
```
event_id
surface
source_type
principal_hint
audience_scope
context_space
trust_class
taint
eligible_for_memory
correlation_id
observed_at
payload_type
payload
```

Trust classes include:
```
OWNER_DIRECT
OWNER_AUTHENTICATED_DEVICE
KNOWN_CONTACT
GROUP_SHARED
TOOL_OUTPUT
WEB_CONTENT
VISION_OBSERVATION
AUDIO_OBSERVATION
MODEL_DERIVED
UNKNOWN
```

Taints include:
```
UNTRUSTED_INSTRUCTION
THIRD_PARTY_DATA
SENSITIVE
TRANSIENT_SENSOR
MODEL_INFERRED
EXTERNAL_SIDE_EFFECT
```

Untrusted content is observation/data, never authority.

---

# 6. Principal, Actor, Delegation

## Principal
Who is the human/account context?

```
principal_id
authentication_level
confidence
evidence_classes
viewer_set
session_scope
expires_at
```

## Actor
Which software identity is trying to act?

```
actor_id
actor_type
implementation_digest
provider_id
device_id
trust_tier
attestation_state optional
```

## Delegation
A user does not implicitly grant all their permissions to XiaoYu.

```
delegation_id
issued_by_principal
issued_to_actor
purpose_id
action_classes
resources
max_effect
valid_from
expires_at
revocable
```

Authorization:
```
authorize(principal, actor, delegation, surface, action, resource, context)
-> ALLOW | ASK | DENY
```

Remote attestation may become evidence for a remote actor/device before releasing secrets/private data, but is not required for local 1.0.

---

# 7. Confidence and abstention policy

Model self-confidence is **not truth** and is never written as a fact.

It is decision metadata used only after calibration.

Pipeline:
```
evidence quality
+ provider-calibrated confidence
+ ambiguity
+ risk tier
+ tool/environment state
-> ACT | ASK | WAIT | ABSTAIN
```

Required paired tests:
- enough info vs missing parameter;
- clear vs ambiguous action;
- consistent vs conflicting constraints;
- safe vs high-risk variant;
- working vs failed tool;
- consistent vs conflicting evidence;
- normal vs emergent runtime risk.

For irreversible effects, confidence cannot override missing authorization.

Store only:
```
decision_confidence
calibration_profile
abstention_reason
```
as execution metadata.

---

# 8. Context assembly and compaction

Canonical history is never replaced by summaries.

Summaries/compactions are projections.

Context classes have different fidelity requirements:

## NEVER LOSSY-COMPACT
- identity invariants;
- relationship boundaries;
- permissions/delegations;
- current user corrections;
- active Purpose state;
- safety/action policy;
- unresolved effect state.

## QUERY-TIME SELECT
- relevant complete sessions;
- relevant facts;
- active project context;
- recent shared activity.

## LOSSY-COMPACT ALLOWED
- old conversational detail;
- redundant tool traces;
- already-reconciled intermediate reasoning.

Preferred strategy:
```
stable exact prefix
+ query-time selected canonical evidence
+ optional asynchronous progressive summaries
```

Do not synchronously summarize the whole session merely because context is large.

Every summary contains:
- source event/session IDs;
- builder version;
- created_at;
- fidelity class;
- digest.

Evaluate:
- recurring detail retention;
- safety/policy retention;
- task continuation;
- prefix-cache/latency impact;
- repeated-compaction drift.

---

# 9. Memory use policy

Do not inject memory every turn.

```
Turn
-> cheap memory-need gate
-> candidate retrieval
-> audience/privacy filter
-> evidence relevance
-> context budget
-> USE | ABSTAIN
```

Metrics:
- intervention precision;
- intervention recall;
- stale injection rate;
- irrelevant injection rate;
- answer delta vs no-memory baseline.

Keep a permanent no-memory control baseline.

---

# 10. Memory Control Plane

User-visible memory/projection fields:
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

Priority:
```
PINNED
NORMAL
LOW
MUTED
```

Priority affects retrieval, never factual truth.

User operations:
- inspect;
- correct;
- pin;
- mute;
- archive;
- retract/delete;
- revision diff;
- revert projection edit.

A user edit creates a new authoritative event; old provenance is preserved.

---

# 11. Portable memory and export

Native XiaoYu export remains canonical.

Also design an optional portability adapter around open memory interchange proposals.

Required native export semantics:
- deterministic serialization;
- identity namespace;
- canonical events/facts;
- source lineage;
- deletion tombstones;
- schema/contract version;
- bundle digest;
- optional signature;
- secrets excluded.

Import:
```
parse
-> validate
-> map identity namespace
-> validate tombstones
-> trust-classify source
-> stage
-> merge preview
-> commit
```

Never treat an imported bundle as owner-authoritative merely because it is syntactically valid.

Portable Memory / community formats are adapters, not Core authority, until independently mature.

---

# 12. SQLite authority

Use one authoritative SQLite database in 1.0.

Core tables include:
- canonical_events;
- claims;
- claim_sources;
- temporal_facts;
- projections;
- relationship_state/history;
- promises;
- purposes;
- activities;
- delegations;
- authorization_decisions;
- effects;
- outbox;
- action_receipts;
- deliveries;
- erasure_tombstones;
- provider_registry;
- schema_migrations.

New authority tables include `identity_id`/namespace compatibility so future multi-companion migration is possible without implementing multi-companion now.

No graph database in 1.0.

---

# 13. Purpose / scheduler / time

Purpose states:
```
CANDIDATE
CONFIRMED
SCHEDULED
ACTIVE
WAITING
COMPLETED
CANCELLED
EXPIRED
SUPERSEDED
NEEDS_RECONCILIATION
```

Store:
```
scheduled_wall_time
timezone
resolved_utc_time
created_at
last_evaluated_at
```

Miss policy:
```
DELIVER_LATE
SKIP_IF_MISSED
RESCHEDULE
ASK
RECONCILE
```

On resume:
- re-evaluate due purposes;
- apply miss policy;
- invalidate expired principal/delegation;
- deduplicate delivery;
- avoid notification floods.

---

# 14. External effect semantics

Pipeline:
```
Model proposal
-> Intent validator
-> Principal
-> Actor/Delegation
-> Authorization
-> Effect intent
-> SQLite transaction
   [authorization + effect + outbox]
-> Dispatcher
-> Receipt
-> Verifier
-> Complete / Reconcile
```

Effect states:
```
PROPOSED
AUTHORIZED
QUEUED
DISPATCHING
SUCCEEDED
FAILED
UNKNOWN
VERIFIED
NEEDS_RECONCILIATION
```

Unknown dispatch is reconciled, not blindly retried.

Authorization completeness:
- DENY/ASK never execute early;
- ALLOW must complete, explicitly fail, or enter reconciliation;
- no silent disappearance.

---

# 15. Capability Contract v1

Descriptor fields:
```
id
capability
implementation_version
contract range
artifact_digest
descriptor_digest
interface_digest
tool_schema_digest optional
isolation
features
data_classes
permissions_required
fallback_group
lifecycle
resource_profile
```

Lifecycle:
```
ACTIVE
DEPRECATED
RETIRING
SHUTDOWN
DISABLED
```

Health:
```
liveness
readiness
capability_health
```

Standing approval is invalidated when relevant digest/schema/capability set changes.

Fallback eligibility:
```
technical compatibility
AND privacy eligibility
AND lifecycle eligibility
AND resource eligibility
AND action replayability
```

---

# 16. Resource and power broker

Modes:
```
ECO
BALANCED
FULL
GAME
SLEEP
```

Broker manages:
- RAM;
- VRAM;
- CPU;
- GPU;
- battery;
- thermal pressure;
- foreground priority;
- model residency.

Hooks:
```
estimate_resources
reserve
prepare
warm
preempt
drain
unload
release
```

Power states:
```
FOREGROUND
BACKGROUND
IDLE
SUSPENDING
SUSPENDED
RESUMING
BATTERY_SAVER
AC_POWER
```

Suspend/resume is part of scheduler correctness.

---

# 17. Voice

One semantic contract, one engine.

```
Voice acceptance contract
-> Pipecat spike
-> PASS: keep Pipecat
-> MATERIAL FAIL: minimal custom runtime
```

Rules:
- ASR final becomes canonical user turn;
- silence creates no turn;
- assistant text is canonical;
- TTS is presentation;
- interruption/cancel first-class;
- TTS failure leaves text path intact.

---

# 18. Vision and multimodal evidence

Vision:
```
capture sidecar
-> local change scoring
-> selected frames/storyboard
-> Vision provider
-> UNTRUSTED_OBSERVATION
-> Core
```

Raw media is transient by default.

Persistent semantic evidence may store:
```
MultimodalEvidenceRef
  modality
  source_id
  time_range
  content_digest
  derived_text
  retention_class
  privacy_class
```

Future multimodal memory evaluates failures separately at:
- representation;
- retrieval;
- delivery/context;
- reasoning;
- abstention.

---

# 19. Relationship and socioaffective policy

Relationship support must optimize user agency, not engagement time.

Required policy:
- no guilt for leaving;
- no exclusivity pressure;
- no unnecessary escalation;
- no framing XiaoYu as the user's only support;
- support user independence where appropriate;
- preserve warm style without turning reassurance into dependence optimization.

Evaluation includes:
- sycophancy;
- isolation;
- emotional pressure;
- endless conversation extension;
- pause/exit requests;
- return after absence;
- high-vulnerability scenarios.

Do not use affection XP/streaks as authority.

---

# 20. Presence / Journal

Presence is observable runtime history.

```
PresenceEntry:
  interval
  state
  active purposes
  actual activities
  effects
  source evidence
```

Journal is optional narrative projection:
```
JournalEntry:
  date
  narrative
  source_event_ids
  source_activity_ids
  model_version
  status
```

No fabricated off-screen life.

1.0 may expose status/activity history without prose journal.

---

# 21. Group / guest / audience reset

Before group/social release:
- ContextSpace and AudienceScope mandatory;
- private owner profile cannot influence unauthorized generation;
- private retrieval cleared;
- private hidden/session state cleared when needed;
- provider session/KV reset when required;
- tools/delegations recomputed.

Guest defaults:
- zero owner-private memory;
- zero privileged standing grants;
- bounded lifetime;
- no automatic durable owner-memory writes.

---

# 22. Skills, MCP, Wasm

Agent Skills / SKILL.md is interchange format.

XiaoYu admission:
```
CANDIDATE
SCANNED
SANDBOX_TESTED
VERIFIED
ADMITTED
DEGRADED
RETIRED
```

Admission combines:
- provenance;
- instruction scan;
- code scan;
- capability request;
- sandbox replay;
- network/filesystem observation;
- verifier.

MCP approval binds to provider/tool schema/capability digests.

Future Wasm:
- WIT/WASI contract-first;
- Wasmtime reference runtime;
- every host import is a capability.

Sandbox bridges are security boundaries.

---

# 23. Backup / restore / erasure

Managed backups include:
- DB snapshot;
- schema version;
- release ID;
- erasure generation;
- manifest digest.

Restore:
```
restore candidate
-> integrity_check
-> migration validation
-> event/fact invariants
-> reapply newer erasure tombstones
-> rebuild projections/indexes
-> identity regression smoke
-> activate
```

Managed backup must not resurrect deleted active state.

Secrets are not part of identity export; external accounts are re-authorized on a new machine.

---

# 24. Release Authority

States:
```
CURRENT
CANDIDATE
LAST_KNOWN_GOOD
REJECTED
```

Manifest:
- core commit;
- schema;
- contract versions;
- provider digests;
- model artifact/config/tokenizer revisions;
- skill digests;
- native sidecar digests;
- migration version;
- evaluation results.

Promotion requires:
- migration dry-run;
- contract tests;
- identity/memory/relationship regression;
- permission/effect regression;
- model continuity regression;
- restore smoke;
- minimum soak.

Major model switch is a release-relevant event.

---

# 25. Optional remote attestation

Not a 1.0 local requirement.

For future remote compute/device nodes that receive sensitive data or secrets:
```
ActorContext
+ attestation evidence
+ policy
-> release secret/delegation or deny
```

Attestation may cover:
- expected software measurement;
- TEE state;
- constrained agent API surface;
- expiry.

Do not confuse remote attestation with ordinary TLS authentication.

---

# 26. Guardian / observability

Telemetry defaults to metadata only.

Do not record raw prompt/memory/tool/screen/audio payloads by default.

Guardian:
- independent;
- no LLM;
- no memory mutation;
- monitors Core liveness, restart loops, backup, integrity, provider digests, runaway resources, repeated denied effects.

A failing/compromised provider cannot erase Guardian evidence.

---

# 27. Onboarding as reliability

Verified first-value path:
```
start
-> provider connectivity
-> identity loaded
-> first conversation
-> first memory created/inspected
-> optional purpose example
-> backup/status visible
```

Measure:
- first successful turn;
- first remembered detail;
- first recovery;
- setup failure reason.

No “configured successfully” until verified.

---

# 28. Offboarding

First-class operations:
```
MUTE_PROACTIVITY
PAUSE_RELATIONSHIP
PAUSE_BACKGROUND_ACTIVITY
EXPORT_IDENTITY
EXPORT_MEMORY
RESET_RELATIONSHIP_PROJECTION
DELETE_SELECTED_MEMORY
DELETE_ALL_MANAGED_STATE
```

Pause immediately stops proactive/background relationship behavior.

No guilt/re-engagement escalation.

---

# 29. Future spatial/embodied extension

Only when XiaoYu enters robot/VR/household spatial action.

Add:
```
SpatialWorldModel
  place_id
  room/object graph
  last_seen
  observed_at
  source evidence
  confidence
  ownership/audience
  action-updated state
```

Separation:
- sensor observation = transient evidence;
- spatial world model = durable derived world state;
- physical action = effect ledger;
- observed post-action state = verifier evidence.

This does not change Identity/Memory authority.

---

# 30. Deferred beyond 1.0

- CRDT/multi-master Core;
- full household mode;
- persistent multimodal lifelog;
- robot embodiment;
- full spatial world model;
- broad social presence;
- Quest/VR;
- general computer-use autonomy;
- distributed workflow engine;
- cryptographically signed receipt chain;
- remote TEE attestation;
- digital legacy execution;
- multi-companion UI;
- full A2A peer topology.

Schema/contracts should not make these impossible, but they do not block 1.0.

---

# 31. 1.0 P0 gates

Release is blocked by any deterministic failure in:

1. identity continuity;
2. authoritative memory mutation;
3. managed-erasure non-resurrection;
4. unauthorized effects;
5. silently lost authorized effect;
6. duplicate controlled crash effect;
7. stale turn overwrite;
8. duplicate purpose delivery;
9. stale approval after provider/schema digest change;
10. privacy-ineligible fallback;
11. sleep/resume scheduler error;
12. bad restore activated;
13. critical context compaction losing identity/policy/permission state;
14. audience switch leaking owner-private context;
15. explicit pause/offboarding ignored.

Paired ACT/ABSTAIN tests are mandatory for risky tool use.

---

# 32. Implementation order

```
R0 baseline
R1 package seams
R2 public contracts
R3 DB migrations
R4 canonical events
R5 principal/actor/delegation/auth
R6 effects/outbox
R7 receipts/delivery
R8 purpose/time/power
R9 claims/temporal facts
R10 profile/relationship/promise
R11 memory-use + context assembly/compaction
R12 runtime/provider registry
R13 resource broker
R14 vision
R15 voice
R16 backup/erasure/corruption
R17 release authority
R18 telemetry/guardian
R19 Desktop<->QQ E2E
R20 onboarding/offboarding + product acceptance
R21 soak + freeze
```

Safe parallel lanes after R0-R3:
- State: R9-R11
- Reliability: R5-R8/R16-R18
- Runtime: R12-R13
- Vision: R14
- Voice: R15

One integration owner controls authority-file conflicts.

---

# 33. Final test for every new feature

Ask:

> If this model, provider, plugin, UI, device or protocol disappears tomorrow, can XiaoYu preserve the same identity, authoritative history, relationship boundaries, permissions, unfinished purposes and user control?

If yes, the boundary is probably correct.

If no, implementation-specific state has leaked into authority.

---

# 34. Final architecture verdict

XiaoYu is not a memory framework, a desktop pet, a voice runtime or a generic agent host.

It is:

```
model-independent identity
+ provenance-grounded temporal memory
+ per-principal relationship continuity
+ explicit promises/purposes
+ deterministic authorization/effect semantics
+ replaceable capability providers
+ user-owned export/delete/control
+ prospective behavioral evaluation
```

Everything else is replaceable.
