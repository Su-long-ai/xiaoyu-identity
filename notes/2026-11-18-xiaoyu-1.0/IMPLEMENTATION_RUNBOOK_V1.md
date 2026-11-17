# XiaoYu Implementation Runbook V1

**Date:** 2026-11-18  
**Authority:** execute `IMPLEMENTATION_SPEC_V1.md`.  
**Rule:** smallest reversible step -> tests -> product E2E -> freeze.

---

# R0 Baseline reconciliation

Record current local commit, dirty state, Python/runtime versions, DB schema, identity ID, provider config, Desktop/QQ status and full current regression.

Run all existing tests before any authority migration.

Exit: known baseline, classified pre-existing failures.

---

# R1 Package seams

Create `xiaoyu/{contracts,core,persistence,runtime,providers,tools,surfaces,release,guardian,tests}`.

Do not move legacy files yet. No import may start DB/network/provider processes.

Exit: old suite green + import test.

---

# R2 Freeze public contracts

Implement:
- InputSourceEnvelope
- PrincipalContext
- ActorContext
- Delegation
- AuthorizationDecision
- EffectIntent
- ActionReceipt
- CapabilityDescriptor
- ProviderHealth
- SurfaceAdapter
- MultimodalEvidenceRef

Require deterministic JSON, timezone-aware timestamps, schema version.

Exit: round-trip/conformance tests.

---

# R3 DB migration framework

Add schema migration table, transactional DB wrapper, integrity check, online backup helper.

Create V1 authority tables in a migrated copy without switching product reads yet.

Include identity/companion namespace compatibility.

Exit: empty DB + realistic existing DB copy migrate safely and idempotently.

---

# R4 Canonical event shadow-write

Desktop and QQ inputs become InputSourceEnvelope and append immutable canonical events before legacy flow continues.

Tool/web/vision outputs carry trust/taint.

Exit: one input -> one event; retries dedupe; no semantic product regression.

---

# R5 Principal / Actor / Delegation / Authorization

1.0 supports:
- Desktop owner;
- QQ owner/private allowlist;
- UNKNOWN.

Create explicit actor IDs for Core/Runtime/surfaces/providers/tools.

Route legacy send_guard through deterministic policy.

Paired tests cover ALLOW/ASK/DENY, expired/wrong actor/wrong resource/digest changes.

Exit: deterministic matrix 100%.

---

# R6 Effect + transactional outbox

Atomically persist:
- authorization decision;
- effect intent;
- outbox row.

Dispatcher operates post-commit.

UNKNOWN dispatch -> reconcile, never blind retry.

Crash injection at pre/post send and receipt points.

Exit: zero duplicate controlled idempotent effects; non-idempotent uncertainty -> NEEDS_RECONCILIATION.

---

# R7 Action receipt + delivery ledger

Separate logical notification from carrier attempts.

Receipt records actor/provider/auth/request/result metadata.

Exit: Desktop/QQ fallback yields exactly one logical delivery.

---

# R8 Purpose/time/power

Implement first:
- REMINDER
- FOLLOW_UP
- BOUNDED_WATCH
- TASK_COMPLETION_DELIVERY

Store wall time + timezone + resolved UTC + miss policy.

Implement suspend/resume reconciliation.

Exit: cancel/reschedule/complete/resume deterministic suite 100%.

---

# R9 Event -> Claim -> Temporal Fact

Shadow-write claims/facts while proven legacy retrieval remains active.

Implement explicit correction/retraction/delete deterministically.

Core operations:
- assert_fact
- correct_fact
- retract_fact
- delete_fact
- get_current_fact
- get_fact_at_time

Exit: temporal mutation regression 100%.

---

# R10 Profile / Relationship / Promise

Profile remains evidence-linked projection.

Relationship becomes per-principal.

Add minimal Promise candidate/ledger for explicit XiaoYu commitments only.

Tests:
- correction/deletion rebuilds projections;
- Profile Shock can overturn stale preference;
- promise can link to purpose;
- promise does not self-authorize action.

Exit: deterministic rebuild equality.

---

# R11 Memory-use + context assembly/compaction

Implement adaptive memory-use gate before sophisticated classifier.

Context fidelity classes:

NEVER LOSSY:
- identity
- boundaries
- permissions
- active purposes
- current corrections
- unresolved effects

QUERY-TIME SELECT:
- relevant full sessions/facts/project context

LOSSY ALLOWED:
- redundant old conversational/tool detail

Canonical history is never replaced.

Summaries are evidence-linked projections.

Tests:
- no-memory casual turns;
- useful recall;
- stale trap;
- repeated compaction;
- safety/identity/policy preservation;
- recurring detail retention.

Exit: no critical invariant lost across repeated compaction; adaptive memory improves total quality over always-inject/no-memory baselines.

---

# R12 Runtime Host / Provider Registry

Move provider lifecycle/routing behind Runtime Host while keeping model_adapter facade.

Descriptor verification:
- contract;
- digest;
- lifecycle;
- data class;
- privacy;
- health;
- features.

Changed tool/schema/capability digest invalidates standing approval.

Exit: provider failure does not break Core; provider swap preserves identity.

---

# R13 ResourceBroker + Ambient Presence Engine

ResourceBroker manages RAM/VRAM/CPU/GPU/battery/priority.

Modes:
- ECO
- BALANCED
- FULL
- GAME
- SLEEP

Add optional deterministic Ambient Presence Engine in presentation/runtime layer:
- idle movement/body state;
- routine/status transitions;
- no LLM required;
- no durable persona/memory mutation;
- no artificial need that pressures user.

Exit: companion remains visually/presentationally alive with LLM unavailable, while Semantic Core stays unchanged.

---

# R14 Vision sidecar

Use bounded capture/change selection.

Output becomes UNTRUSTED_OBSERVATION.

Raw media transient by default.

Sensor state TTL.

Exit: OFF actually stops capture; static screen suppresses repeated calls; no orphan process.

---

# R15 Voice spike

Pipecat-first:
mic -> VAD -> ASR -> canonical turn -> existing LLM -> TTS -> audio.

Silence = no turn.
TTS = presentation.
Interruption/cancel first-class.

Exit: measured latency/resource gates; choose Pipecat or minimal custom engine, not both.

---

# R16 Audience reset / guest preparation

Before any group/private sharing expansion:
- context_space;
- audience_scope;
- principal set;
- permitted profile/retrieval subset;
- provider-session reset when required;
- recomputed tool/delegation set.

Exit: owner-private memory/profile cannot influence unauthorized group/guest generation.

---

# R17 Backup / erasure / portable export

Managed backup metadata:
- release;
- schema;
- erasure generation;
- manifest digest.

Restore:
integrity -> migration -> invariants -> tombstones -> rebuild -> identity smoke -> activate.

Native export:
- deterministic;
- provenance;
- tombstones;
- no secrets.

Add optional portability adapter only behind conformance tests; external format never becomes authority.

Exit: managed restore cannot resurrect deleted active state.

---

# R18 Release Authority

Manifest:
- core commit;
- schema;
- contracts;
- provider/model/tokenizer/config digests;
- skills;
- native sidecars;
- test evidence.

States:
CURRENT / CANDIDATE / LAST_KNOWN_GOOD / REJECTED.

Major model switch runs identity/relationship/memory/tool continuity regression.

Exit: rollback preserves semantic state and identity ID.

---

# R19 Telemetry / Guardian

Privacy-safe telemetry metadata only by default.

Independent Guardian watches:
- liveness;
- restart loops;
- backup;
- integrity;
- provider digest;
- resource runaway;
- repeated denied effects.

Exit: crash/integrity failure observable independently of failed component.

---

# R20 Onboarding / Memory Control / Offboarding

Onboarding verifies:
- provider connectivity;
- identity loaded;
- first turn;
- first memory inspect/correct;
- backup/status visible.

Memory control:
- source;
- revision;
- PINNED/NORMAL/LOW/MUTED;
- correction/archive/delete.

Offboarding:
- mute proactivity;
- pause relationship/background;
- export;
- reset relationship projection;
- delete selected/all managed state.

Exit: pause/exit is immediate and non-manipulative; no fake success screens.

---

# R21 Desktop <-> QQ E2E

Scenarios:
- QQ -> Desktop;
- Desktop -> QQ;
- purpose delivery once;
- restart;
- stale race;
- provider fallback;
- unpaired fail-closed.

Exit:
identity split 0;
duplicate memory 0;
duplicate delivery 0;
stale persistence 0.

---

# R22 Long soak + freeze

Soak:
- idle;
- long chat with repeated compaction;
- memory-heavy;
- Desktop+QQ;
- Vision;
- Voice;
- provider error;
- network loss;
- sleep/resume;
- low disk;
- repeated restart;
- background presence with LLM unavailable.

Track RAM/VRAM/processes/DB/outbox/purpose/log/backup trends.

Run all P0 gates from IMPLEMENTATION_SPEC_V1.md.

Then mark:
```
XIAOYU_1_0_DONE
```

---

# Parallel lanes after R0-R3

Lane A — State:
R4, R9, R10, R11

Lane B — Reliability:
R5-R8, R16-R19

Lane C — Runtime:
R12-R13

Lane D — Vision:
R14

Lane E — Voice:
R15

Lane F — Product:
R20-R21

One integration owner controls semantic-authority files.

---

# Future-only tracks

Do not block 1.0:
- persistent spatial world model;
- robot/physical action;
- multi-master/CRDT;
- household;
- remote TEE attestation;
- persistent multimodal lifelog;
- multi-companion UI;
- social platform;
- VR/Quest;
- A2A peer topology;
- digital legacy execution.

When embodiment starts, external environment remains the judge:
```
observation -> world projection -> proposed physical effect -> action -> observed post-state -> verifier
```

Internal world memory never overrides contradictory live evidence.

---

# Coding-agent handoff format

Every coding task should reference:
1. `IMPLEMENTATION_SPEC_V1.md`;
2. one R-step from this runbook;
3. the current baseline commit;
4. required tests;
5. the exit gate.

Do not ask coding agents to reinterpret the full architecture independently.
