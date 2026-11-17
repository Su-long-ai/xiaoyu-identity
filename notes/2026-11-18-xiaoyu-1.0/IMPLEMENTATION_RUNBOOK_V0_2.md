# XiaoYu Implementation Runbook v0.2

**Date:** 2026-11-18  
**Purpose:** Execute `IMPLEMENTATION_SPEC_V0_2.md` with the smallest safe sequence.  
**Rule:** Do not skip a gate because a later feature appears more interesting.

---

# R0. Reconcile and freeze current baseline

## Goal

Establish the exact working baseline before architecture migration.

## Actions

1. Pull/reconcile the freshest local workspace when local access is available.
2. Preserve all uncommitted API-only/runtime-worker fixes.
3. Record:
   - current commit;
   - Python version;
   - provider config shape;
   - DB schema version;
   - existing identity ID;
   - current regression result;
   - Desktop/QQ status.
4. Run the entire existing test suite.
5. Create a baseline artifact containing test counts and failures.

## Commands

Preferred:

```powershell
python -m pytest -q
```

If repository has known non-pytest runners, run them in addition. Do not replace the existing validation path with a new harness before baseline is captured.

## Exit gate

- baseline commit/state recorded;
- every pre-existing failure classified;
- no migration begins on an unknown dirty state.

---

# R1. Add package skeleton and compatibility seams

## New files

```
xiaoyu/__init__.py
xiaoyu/contracts/__init__.py
xiaoyu/core/__init__.py
xiaoyu/persistence/__init__.py
xiaoyu/runtime/__init__.py
xiaoyu/providers/__init__.py
xiaoyu/surfaces/__init__.py
xiaoyu/release/__init__.py
xiaoyu/guardian/__init__.py
```

## Do not move existing implementation yet

Existing files remain functional:

```
identity_core.py
product_memory_bridge.py
product_memory_bridge_base.py
model_adapter.py
send_guard.py
companion.py
```

## New test

```
test_architecture_imports.py
```

Verify:

- package imports;
- importing package does not start providers/sidecars;
- no DB is opened on import;
- no network call on import.

## Exit gate

Old tests unchanged + architecture import test passes.

---

# R2. Freeze contract dataclasses

## Implement

```
xiaoyu/contracts/common.py
xiaoyu/contracts/envelopes.py
xiaoyu/contracts/principal.py
xiaoyu/contracts/actor.py
xiaoyu/contracts/authorization.py
xiaoyu/contracts/effects.py
xiaoyu/contracts/receipts.py
xiaoyu/contracts/capability.py
xiaoyu/contracts/errors.py
```

## Required types

- `InputSourceEnvelope`
- `PrincipalContext`
- `ActorContext`
- `Delegation`
- `ActionRequest`
- `AuthorizationContext`
- `AuthorizationDecision`
- `EffectIntent`
- `ActionReceipt`
- `CapabilityDescriptor`
- `ProviderHealth`

Use stdlib dataclasses/enums unless an already-installed project dependency clearly improves compatibility. Do not add a new validation framework only for these objects.

## Serialization

Each durable contract type must have deterministic JSON representation.

Rules:

- enum values are strings;
- timestamps are timezone-aware;
- unknown fields are rejected for authority-changing input;
- version field exists for persisted JSON contracts.

## Tests

```
test_contract_roundtrip.py
test_contract_unknown_fields.py
test_contract_timezone_awareness.py
```

## Exit gate

Round-trip equality for all durable contracts.

---

# R3. Add schema/migration framework without changing semantics

## Implement

```
xiaoyu/persistence/db.py
xiaoyu/persistence/schema.py
xiaoyu/persistence/migrations/
```

## Database wrapper responsibilities

- connection creation;
- WAL/pragmas;
- transaction context manager;
- migration version;
- integrity check;
- online backup helper;
- no business semantics.

## Migration table

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

## First migration

Create the new v0.2 tables from the implementation spec, but do not yet switch reads/writes from legacy tables if that risks current behavior.

## Migration rule

Every migration must have:

- precondition;
- forward function;
- verification function;
- no destructive cleanup in the same release as first migration unless unavoidable.

## Tests

```
test_migration_empty_db.py
test_migration_existing_db_copy.py
test_migration_idempotent.py
test_integrity_check.py
```

Use a copy of realistic DB fixtures, never the live identity DB.

## Exit gate

A current DB copy migrates and all old tests still pass.

---

# R4. Canonical event ingestion seam

## Implement

```
xiaoyu/core/events.py
xiaoyu/surfaces/base.py
```

## Goal

Make every new input enter through `InputSourceEnvelope` without rewriting memory logic yet.

## Adapter order

1. Desktop;
2. QQ;
3. later ASR;
4. later Vision.

## Event repository

```
xiaoyu/persistence/repositories/events.py
```

API:

```python
append_event(envelope, principal_context) -> CanonicalEvent
get_event(event_id) -> CanonicalEvent | None
list_turn(turn_id) -> list[CanonicalEvent]
```

Canonical events are append-only.

## Compatibility

Legacy turn path may continue to execute after canonical event persistence.

## Tests

- same Desktop message writes one event;
- same QQ message writes one event;
- retry with same event ID does not duplicate;
- malformed surface payload never reaches Core;
- untrusted visual/tool payload is tainted.

## Exit gate

Existing product flow works with event ledger shadow-writing enabled.

---

# R5. Principal + Actor + Authorization v1

## Implement

```
xiaoyu/core/authorization.py
xiaoyu/persistence/repositories/grants.py
```

## Start narrow

For 1.0 principal evidence:

- Desktop local owner session;
- QQ owner allowlist/private session;
- UNKNOWN.

Do not implement speaker/face identity yet.

## Actor IDs

At minimum:

```
xiaoyu.core
xiaoyu.runtime
surface.desktop
surface.qq
provider:<id>
tool:<id>
```

## Policy

Implement pure deterministic function first:

```python
decision = policy.evaluate(
    principal,
    actor,
    delegation,
    action,
    resource,
    context,
)
```

Persistence records decision after evaluation.

## Compatibility adapter

`send_guard.py` should delegate high-risk decision logic to this service while preserving its old public entry points.

## Tests

Create matrix:

```
owner + T0 -> ALLOW
owner + T1 -> ALLOW or configured
owner + T2 -> policy
owner + T3 -> ASK unless explicit valid grant
unknown + private context -> DENY
expired delegation -> DENY/ASK
wrong actor -> DENY
wrong resource -> DENY
changed tool digest -> prior grant invalid
```

## Exit gate

100% deterministic policy matrix + old send guard regressions.

---

# R6. Effect intent + transactional outbox

## Implement

```
xiaoyu/core/effects.py
xiaoyu/runtime/outbox.py
xiaoyu/persistence/repositories/effects.py
```

## Effect states

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

## Outbox states

```
PENDING
CLAIMED
SENT
FAILED_RETRYABLE
FAILED_FINAL
NEEDS_RECONCILIATION
```

## Critical invariant

Authorization decision + effect intent + outbox enqueue are one SQLite transaction.

## Dispatcher

Single-process 1.0 implementation is enough.

Pseudo-loop:

```python
while running:
    rows = claim_due_outbox_rows(limit=20)
    for row in rows:
        dispatch_one(row)
```

Claim rows atomically to avoid duplicate local workers.

## Retry

Retry only if action contract says replayable/idempotent.

## Crash suite

Inject crash at:

1. before transaction;
2. after transaction;
3. before external call;
4. immediately after external call;
5. after receipt;
6. before verification.

## Exit gate

Controlled crash suite produces zero duplicate effects for idempotent test tool, and unknown non-idempotent dispatch becomes `NEEDS_RECONCILIATION`.

---

# R7. Action receipts and delivery ledger

## Implement

```
xiaoyu/contracts/receipts.py
xiaoyu/persistence/repositories/effects.py
```

Add delivery semantics for Desktop/QQ notifications.

Logical notification ID must be independent of carrier attempt.

Example:

```
notification_id
purpose_id
chosen_surface
delivery_state
attempts
delivered_at
```

## Required property

One Purpose -> one logical delivery unless explicit repeat policy says otherwise.

## Tests

- Desktop success means QQ fallback does not duplicate;
- Desktop unavailable -> QQ exactly once;
- restart after transport success -> reconcile;
- duplicate OneBot acknowledgement does not duplicate logical delivery.

## Exit gate

Duplicate logical delivery = 0 in deterministic suite.

---

# R8. Purpose/time/power skeleton

## Implement

```
xiaoyu/core/purpose.py
xiaoyu/runtime/scheduler.py
xiaoyu/runtime/power.py
xiaoyu/persistence/repositories/purposes.py
```

## First supported purpose kinds

Do not generalize prematurely.

Support:

```
REMINDER
BOUNDED_WATCH
FOLLOW_UP
TASK_COMPLETION_DELIVERY
```

## Required fields

- state;
- owner type;
- exact source event;
- scheduled wall time;
- timezone;
- resolved UTC;
- miss policy;
- quiet-hour class;
- duplicate key.

## Time tests

- Asia/Shanghai normal date;
- DST timezone transition;
- clock moved backward;
- computer sleeps over due time;
- computer resumes much later;
- restart before due;
- restart after due;
- reschedule;
- cancel.

## Power integration

On suspend:

- stop/flush optional workers;
- persist scheduler checkpoint.

On resume:

- invalidate expired principal/delegation;
- recalculate due purposes;
- apply miss policies.

## Exit gate

Explicit cancellation/reschedule/completion suite 100%; no duplicate late delivery.

---

# R9. Event -> claim -> temporal fact migration

## Implement

```
xiaoyu/core/claims.py
xiaoyu/core/temporal.py
xiaoyu/core/memory.py
xiaoyu/persistence/repositories/claims.py
```

## Important migration strategy

Do not replace current ProductMemoryBridge all at once.

Phase A:
- shadow-write new events/claims/facts;
- current retrieval still reads legacy/current proven path.

Phase B:
- compare semantic outputs.

Phase C:
- switch selected profile/current-fact queries to new authority.

## Minimal claim extraction

Use deterministic paths for explicit corrections/deletions where possible.

Model-derived claims remain candidates until admission policy accepts them.

## Required operations

```
assert_fact
correct_fact
retract_fact
delete_fact
get_current_fact
get_fact_at_time
```

## Tests

Core deterministic examples:

```
city=Nanjing
city=Suzhou
ask current -> Suzhou
ask historical -> Nanjing
retract Suzhou -> current state follows defined semantics
delete target -> not active/retrievable
```

## Exit gate

Authoritative mutation deterministic suite 100%.

---

# R10. Projection builders

## Implement

```
xiaoyu/core/profile.py
xiaoyu/core/relationship.py
```

## Profile v1 fields

- stable preferences;
- important people;
- active long-term projects;
- interaction style;
- proactivity settings.

## Rules

- evidence links mandatory;
- deterministic rebuild;
- unsupported inference stays absent/UNKNOWN.

## Relationship v1

For 1.0 owner only, but schema must be per-principal.

Fields:

- relation kind;
- shared-history projection;
- interaction norms/boundaries;
- source facts.

## Rebuild command

Provide an internal command:

```
rebuild_projections(all=True)
```

No manual DB surgery needed.

## Tests

- correction changes projection;
- deletion removes dependent projection;
- provider switch does not change deterministic projection;
- complete rebuild equals incremental state;
- Profile Shock scenario can overturn stale preference.

## Exit gate

Projection rebuild deterministic.

---

# R11. Adaptive memory-use gate

## Goal

Stop treating memory retrieval as mandatory for every turn.

## Implement

Prefer simple deterministic/cheap gate first in current memory bridge.

Output:

```
USE_MEMORY
NO_MEMORY
MAYBE
```

MAYBE may run bounded retrieval; retrieval evidence can still result in ABSTAIN.

## Log/eval only

Do not expose these labels to user.

## Regression dataset

Include:

- obvious recall;
- implicit useful continuity;
- casual greeting;
- unrelated technical question;
- stale-topic trap;
- no-evidence question;
- profile-relevant request.

## Metrics

- intervention precision;
- recall;
- irrelevant injection rate;
- answer delta vs no-memory baseline.

## Exit gate

Must improve total product quality without forcing memory into casual turns. If complex classifier does not beat simple rules, retain simple rules.

---

# R12. Runtime Host + provider registry v0.2

## Implement

```
xiaoyu/runtime/host.py
xiaoyu/runtime/provider_registry.py
xiaoyu/runtime/router.py
xiaoyu/runtime/supervisor.py
xiaoyu/runtime/circuit_breaker.py
```

## Migrate model_adapter behind router

`model_adapter.py` remains facade.

## Descriptor verification

At load:

1. parse descriptor;
2. check contract compatibility;
3. verify descriptor digest;
4. verify artifact/interface digest when applicable;
5. check lifecycle;
6. evaluate privacy/data class;
7. start;
8. health;
9. advertise features.

## Approval invalidation

For tools/MCP:

```
descriptor_digest changed
OR tool_schema_digest changed
OR capability_set changed
=> standing approval invalid
```

## Exit gate

Provider swap does not alter canonical identity state; broken provider degrades without breaking text-only Core.

---

# R13. ResourceBroker

## Implement

```
xiaoyu/runtime/resources.py
```

## Start with measured static budgets

Configuration:

```json
{
  "mode": "BALANCED",
  "max_ram_mb": 4096,
  "max_vram_mb": "MEASURED_SAFE_VALUE",
  "vram_headroom_mb": "MEASURED_SAFE_VALUE"
}
```

Do not commit fake numeric GPU limits. Benchmark the actual machine and write the measured config.

## Provider hooks

```
estimate_resources()
prepare()
warm()
drain()
unload()
```

## Policy

Foreground priority order example:

1. current interactive LLM;
2. TTS while speaking;
3. ASR while listening;
4. explicit Vision request;
5. retrieval;
6. background bounded watch.

Exact ranking is configurable.

## Tests

- simulated insufficient VRAM;
- preempt low priority;
- provider refuses unload;
- GAME mode;
- SLEEP mode;
- no-GPU fallback.

## Exit gate

No test scenario starts a provider after broker has denied its reservation.

---

# R14. Vision sidecar

## First spike

Do not modify Core internals.

Adapter flow:

```
Node sidecar
-> typed observation envelope
-> Vision provider
-> untrusted observation
-> existing canonical turn/runtime
```

## Commands

```
status
peek
watch
stop
region
shutdown
```

## Required measurement

- startup ms;
- idle RAM;
- watch CPU;
- raw frames;
- selected frames;
- provider calls;
- stop cleanup.

## Security

Visual instruction text is never promoted to executable instruction.

## Exit gate

- OFF = process/capture stopped;
- static screen does not repeatedly call Vision;
- region watch ignores outside changes;
- no orphan process after restart.

---

# R15. Voice decision spike

## Build exactly one small Pipecat path first

```
mic
-> VAD
-> ASR
-> XiaoYu canonical turn
-> existing LLM path
-> TTS
-> audio
```

Do not build full custom streaming runtime in parallel.

## Measure

- speech end -> ASR final;
- model first token;
- first audible audio;
- interruption latency;
- RAM/VRAM;
- cleanup.

## Required semantics

- silence -> no turn;
- ASR final -> normal user event;
- TTS does not create new assistant event;
- cancel stops playback;
- TTS failure leaves canonical text intact.

## Decision

PASS acceptance -> retain Pipecat as voice session engine.

Material overhead/dependency failure -> implement minimal custom engine using the same voice contracts.

---

# R16. Backup, erasure and recovery hardening

## Implement

```
xiaoyu/core/erasure.py
xiaoyu/release/migrations.py
```

## Managed backup metadata

- release ID;
- schema version;
- erasure generation;
- backup timestamp;
- manifest digest.

## Erasure generation

Monotonic integer stored in authority DB.

Every deletion increments/records generation.

## Restore

A restored backup older than current erasure history must reapply later tombstones before activation.

## Corruption fixtures

Create disposable test DBs for:

- invalid page/corruption;
- missing index;
- stale projection;
- migration interrupted marker;
- disk-full simulation where practical.

## Exit gate

Managed backup cannot resurrect a deterministically deleted active fact.

---

# R17. Release Authority

## Implement

```
xiaoyu/release/manifest.py
xiaoyu/release/verifier.py
xiaoyu/release/authority.py
```

## First version need not sign artifacts

It must at least calculate/store digests and compare them.

Manifest sections:

- Core;
- DB schema;
- contracts;
- providers;
- models;
- skills;
- native sidecars;
- test evidence.

## Promotion

```
candidate
-> verify
-> migrate copy
-> contract tests
-> identity/memory/auth/effect regression
-> restore smoke
-> promote CURRENT
-> previous CURRENT becomes LAST_KNOWN_GOOD
```

## Exit gate

A provider/model descriptor can be rolled back without changing identity ID or durable semantic state.

---

# R18. Telemetry + Guardian

## Telemetry first

Record structured metadata with privacy-safe defaults.

## Guardian later in same lane

Independent process/service only after Core/runtime health interfaces exist.

Monitor:

- liveness;
- restart count;
- backup age/failure;
- provider digest mismatch;
- resource runaway;
- integrity failure.

No LLM.

## Exit gate

Provider/Core crash is observable without the crashed component needing to write the final alert itself.

---

# R19. Desktop <-> QQ product E2E

Only after Core seams are stable.

## Scenarios

1. QQ user message -> Desktop continuation;
2. Desktop -> QQ continuation;
3. Purpose completion delivered once;
4. restart between surfaces;
5. stale race;
6. provider fallback;
7. QQ disabled/unpaired fail-closed;
8. group path remains private-context denied until audience-scoped memory exists.

## Exit gate

- identity split 0;
- duplicate memory 0;
- duplicate delivery 0;
- stale persistence 0.

---

# R20. Full 1.0 soak and release freeze

## Soak scenarios

- idle;
- normal text;
- many memory turns;
- Desktop + QQ;
- bounded Vision;
- Voice;
- provider errors;
- sleep/resume;
- network loss;
- low disk;
- repeated restart.

## Track

- RAM trend;
- VRAM trend;
- process count;
- DB growth;
- outbox backlog;
- purpose backlog;
- duplicate effects;
- log growth;
- backup status.

## Release condition

All P0 gates in `IMPLEMENTATION_SPEC_V0_2.md` and `VALIDATION_AND_ACCEPTANCE_PLAN.md` pass.

Then tag/status:

```
XIAOYU_1_0_DONE
```

---

# Parallel work lanes

After R0-R3 are complete, safe parallelization:

```
Lane A: event / claims / temporal / profile
Lane B: authorization / effects / outbox
Lane C: Runtime Host / provider registry / resources
Lane D: Vision spike
Lane E: Voice spike
Lane F: release / backup / corruption fixtures
```

Do not allow two agents to modify the same authority files concurrently without an explicit integration owner.

---

# Recommended commit granularity

One commit should contain one reversible semantic step.

Good examples:

```
feat(contracts): add principal actor delegation contracts
feat(db): add v0.2 authority tables
feat(events): shadow-write canonical surface events
feat(auth): delegate send guard to deterministic policy
feat(effects): add transactional outbox
feat(purpose): add timezone and miss-policy semantics
feat(memory): add event-claim-fact shadow projection
feat(runtime): add provider registry v0.2
feat(resources): add reservation broker
test(crash): cover post-dispatch unknown state
```

Avoid commits combining schema migration + provider rewrite + UI changes.

---

# Rollback rule

At the end of every R-step:

1. old entry path still works, or migration has an explicit rollback;
2. database backup fixture can restore;
3. tests are green;
4. only then start the next authority-changing step.

If a new architecture layer causes broad regressions, revert the layer. Do not patch dozens of callers merely to preserve a bad abstraction.

---

# Definition of implementation-ready

A task is ready to hand directly to a coding agent only if it specifies:

- exact files;
- public interface;
- state changes;
- DB changes;
- failure behavior;
- tests;
- exit gate.

The R-steps above meet that requirement. Individual coding prompts can therefore be generated directly from one R-step without reopening architecture research.
