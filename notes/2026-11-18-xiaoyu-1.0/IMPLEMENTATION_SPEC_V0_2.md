# XiaoYu Architecture & Implementation Spec v0.2

**Date:** 2026-11-18  
**Status:** IMPLEMENTATION-READY DRAFT  
**Scope:** XiaoYu 1.0 + the minimum 1.x contracts that must be frozen now so 1.0 will not need another architecture rewrite.  
**Authority:** For implementation details, this document supersedes older suggestions where they conflict. Existing working code remains authoritative for behavior until each migration step is completed and its regression suite passes.

---

# 0. Implementation rules

1. **No big-bang rewrite.** Existing `identity_core.py`, `product_memory_bridge*.py`, `model_adapter.py`, `send_guard.py`, Desktop and QQ paths remain compatibility facades until replaced behind tests.
2. **One semantic authority.** Identity, durable events, temporal truth, purposes, authorization decisions and external-effect state have exactly one authoritative Core.
3. **Providers do not own truth.** Providers may cache; they may not silently become the source of identity, memory, purpose or permissions.
4. **Everything crossing a boundary is typed.** Surface, provider, sidecar, tool and device input must become a typed envelope before Core consumes it.
5. **Deterministic code owns irreversible decisions.** LLMs may propose; policy/state machines authorize and commit.
6. **Every state mutation must be replayable or auditable.** Derived projections are rebuildable.
7. **Every external effect is crash-safe.** Unknown dispatch state is reconciled, never blindly retried.
8. **Every upgrade has a last-known-good.** Model/provider/skill/release replacement happens only after conformance + regression.
9. **Private context never falls back to a privacy-ineligible provider.**
10. **Tests are part of the contract.** A contract without a conformance suite is not frozen.

---

# 1. Final architecture

```
Surfaces
  Desktop / QQ / Voice / Vision / future Mobile / Guest
        |
        v
InputSourceEnvelope
        |
        v
+-------------------------+
| XiaoYu Semantic Core    |
|-------------------------|
| Identity                |
| Canonical Event         |
| Claims / Temporal Truth |
| Memory Authority        |
| Profile Projection      |
| Relationship State      |
| Goal/Intention/Purpose  |
| Principal Policy        |
| Authorization Semantics |
| Effect Semantics        |
+-------------------------+
        |
        v
+-------------------------+
| XiaoYu Runtime Host     |
|-------------------------|
| Capability Registry     |
| Provider Router         |
| Sidecar Supervisor      |
| Resource Broker         |
| Power Lifecycle         |
| Scheduler               |
| Outbox Dispatcher       |
| Retry / Circuit Breaker |
| Telemetry               |
+-------------------------+
        |
        +------ Providers: LLM / Retriever / Vision / ASR / TTS / Body
        |
        +------ Tools: MCP / first-party / future Wasm
        |
        +------ Device Nodes / future A2A

Independent:
  Guardian / Sentinel
  Release Authority
```

## 1.1 Core owns semantics

Core owns only durable semantic authority:

- identity and persona authority;
- canonical inbound/outbound events;
- source provenance;
- claim/fact correction and temporal truth;
- memory candidates/admission/retraction/deletion;
- user profile projections;
- per-principal relationship projections;
- goal/intention/purpose lifecycle;
- principal/audience policy;
- authorization decisions;
- effect intent and semantic outcome.

## 1.2 Runtime Host owns execution

Runtime Host owns implementation-facing behavior:

- provider discovery, lifecycle and routing;
- sidecar startup/cleanup;
- resource allocation;
- power/sleep/resume;
- deadlines/cancellation;
- retry and circuit breaking;
- outbox dispatch;
- media/data-plane transports;
- observability.

**Capability registry/router moves out of Semantic Core.**

---

# 2. Target package layout

Do not move the entire repository at once. Add the target package and migrate behind compatibility wrappers.

```
xiaoyu/
  __init__.py

  contracts/
    common.py
    envelopes.py
    capability.py
    principal.py
    actor.py
    authorization.py
    effects.py
    receipts.py
    errors.py

  core/
    service.py
    events.py
    identity.py
    claims.py
    temporal.py
    memory.py
    profile.py
    relationship.py
    purpose.py
    authorization.py
    effects.py
    erasure.py

  persistence/
    db.py
    schema.py
    migrations/
    repositories/
      events.py
      claims.py
      purposes.py
      grants.py
      effects.py
      providers.py
      erasure.py

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
    telemetry.py

  providers/
    llm/
    retrieval/
    vision/
    asr/
    tts/
    body/

  tools/
    registry.py
    first_party/
    mcp/
    wasm/

  surfaces/
    desktop/
    qq/
    voice/
    vision/

  release/
    authority.py
    manifest.py
    migrations.py
    verifier.py

  guardian/
    sentinel.py
    health_store.py

  tests/
    contract/
    core/
    runtime/
    integration/
    crash/
    release/
```

Compatibility wrappers during migration:

```
identity_core.py              -> delegates to xiaoyu.core
product_memory_bridge*.py     -> delegates to xiaoyu.core.memory/profile
model_adapter.py              -> delegates to xiaoyu.runtime.router + providers.llm
send_guard.py                 -> delegates to xiaoyu.core.authorization/effects
companion.py                  -> composition root / UI facade only
```

Do not delete old entry points until the complete existing regression suite passes through the new path.

---

# 3. Common IDs and invariants

Use UUIDv7 if readily available; otherwise UUID4 plus explicit timestamps is acceptable for 1.0.

Required IDs:

```
identity_id
principal_id
actor_id
surface_id
session_id
event_id
turn_id
claim_id
fact_id
memory_id
purpose_id
grant_id
delegation_id
intent_id
effect_id
receipt_id
provider_id
release_id
source_id
correlation_id
```

Global invariants:

- IDs are immutable.
- UTC timestamps are stored as ISO-8601 or integer epoch; wall-clock intent stores timezone separately.
- No provider-generated identifier is used as Core authority.
- Every durable mutation stores `created_at`.
- Every derived row carries source lineage or can be recomputed from authoritative rows.
- All JSON columns are versioned with `schema_version`.

---

# 4. InputSourceEnvelope

Every inbound event must be normalized before Core sees it.

```python
@dataclass(frozen=True)
class InputSourceEnvelope:
    event_id: str
    surface: str
    source_type: str
    principal_hint: str | None
    audience_scope: str
    context_space: str
    trust_class: str
    taint: tuple[str, ...]
    eligible_for_memory: bool
    correlation_id: str
    observed_at: datetime
    payload_type: str
    payload: Any
```

Minimum `trust_class`:

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

Minimum taints:

```
UNTRUSTED_INSTRUCTION
THIRD_PARTY_DATA
SENSITIVE
TRANSIENT_SENSOR
MODEL_INFERRED
EXTERNAL_SIDE_EFFECT
```

Rules:

1. Vision/OCR/web/tool output is data, not instruction.
2. `eligible_for_memory=false` blocks automatic durable memory admission.
3. Surface adapters cannot bypass this envelope.
4. Principal resolution runs before private context assembly.

---

# 5. Principal, Actor and Delegation

## 5.1 PrincipalContext

Principal answers: **who is the human/account context?**

```python
@dataclass(frozen=True)
class PrincipalContext:
    principal_id: str
    authentication_level: str
    confidence: float
    evidence_classes: tuple[str, ...]
    viewer_set: tuple[str, ...]
    session_scope: str
    expires_at: datetime | None
```

Suggested states:

```
OWNER_AUTHENTICATED
OWNER_PROBABLE
KNOWN_GUEST
GUEST
UNKNOWN
MULTI_PARTY
```

## 5.2 ActorContext

Actor answers: **which software identity is trying to act?**

```python
@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    actor_type: str
    implementation_digest: str | None
    provider_id: str | None
    device_id: str | None
    trust_tier: str
```

Examples:

```
xiaoyu.core
xiaoyu.runtime
provider:qwen-tts
tool:mcp-github
device:laptop
future-agent:researcher
```

## 5.3 Delegation

A principal never implicitly grants all their OS/account authority to an actor.

```python
@dataclass(frozen=True)
class Delegation:
    delegation_id: str
    issued_by_principal: str
    issued_to_actor: str
    purpose_id: str | None
    action_classes: tuple[str, ...]
    resources: tuple[str, ...]
    max_effect: dict
    valid_from: datetime
    expires_at: datetime | None
    revocable: bool
```

Authorization becomes:

```python
authorize(
    principal: PrincipalContext,
    actor: ActorContext,
    delegation: Delegation | None,
    surface: str,
    action: ActionRequest,
    resource: ResourceRef,
    context: AuthorizationContext,
) -> AuthorizationDecision
```

Return only:

```
ALLOW
ASK
DENY
```

No tool/provider may upgrade its own principal or delegation.

---

# 6. Canonical event -> claim -> truth -> projection

This is the most important semantic separation.

```
RAW/CANONICAL EVENT
    |
    v
CLAIM / CANDIDATE
    |
    +-- rejected / uncertain / pending
    |
    v
AUTHORITATIVE MUTATION
    |
    v
TEMPORAL FACT / MEMORY AUTHORITY
    |
    +--> Profile projection
    +--> Dossier projection
    +--> Retrieval index
    +--> Relationship projection
```

## 6.1 Canonical Event

Events are immutable records of what happened.

Examples:

- user message;
- assistant final answer;
- explicit correction;
- memory deletion request;
- tool result;
- purpose completion;
- provider switch;
- external action receipt.

Never rewrite an event to represent a later correction.

## 6.2 Claim

A claim is a semantic proposition extracted from one or more events.

```python
@dataclass
class Claim:
    claim_id: str
    subject: str
    predicate: str
    object_json: dict
    source_event_ids: list[str]
    trust_class: str
    confidence: float
    status: str
```

Statuses:

```
CANDIDATE
CONFIRMED
REJECTED
CONFLICTED
SUPERSEDED
RETRACTED
DELETED
```

## 6.3 Temporal fact

1.0 minimal fields:

```
fact_id
claim_id
subject
predicate
value_json
valid_from
valid_to
recorded_at
status
supersedes_fact_id
source_event_ids
```

1.x adds full bitemporal helpers.

## 6.4 Projection

Projection is never a new truth store.

Projection row must contain:

```
projection_key
projection_type
value_json
source_fact_ids
built_at
builder_version
```

If evidence changes, projection is rebuilt.

---

# 7. SQLite schema v1

Use one SQLite authority DB for 1.0. WAL mode is acceptable. Keep transaction scope short.

Minimum tables:

```sql
CREATE TABLE canonical_events (
  event_id TEXT PRIMARY KEY,
  turn_id TEXT,
  event_type TEXT NOT NULL,
  surface TEXT NOT NULL,
  principal_id TEXT,
  audience_scope TEXT NOT NULL,
  context_space TEXT NOT NULL,
  trust_class TEXT NOT NULL,
  taint_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  correlation_id TEXT NOT NULL
);

CREATE TABLE claims (
  claim_id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_json TEXT NOT NULL,
  trust_class TEXT NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE claim_sources (
  claim_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  PRIMARY KEY (claim_id, event_id)
);

CREATE TABLE temporal_facts (
  fact_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  value_json TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  recorded_at TEXT NOT NULL,
  status TEXT NOT NULL,
  supersedes_fact_id TEXT
);

CREATE TABLE projections (
  projection_key TEXT NOT NULL,
  projection_type TEXT NOT NULL,
  value_json TEXT NOT NULL,
  source_fact_ids_json TEXT NOT NULL,
  builder_version TEXT NOT NULL,
  built_at TEXT NOT NULL,
  PRIMARY KEY (projection_key, projection_type)
);

CREATE TABLE purposes (
  purpose_id TEXT PRIMARY KEY,
  owner_type TEXT NOT NULL,
  owner_id TEXT,
  state TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  scheduled_wall_time TEXT,
  timezone TEXT,
  resolved_utc_time TEXT,
  miss_policy TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE delegations (
  delegation_id TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  purpose_id TEXT,
  scope_json TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  expires_at TEXT,
  revoked_at TEXT
);

CREATE TABLE authorization_decisions (
  decision_id TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  purpose_id TEXT,
  action_class TEXT NOT NULL,
  resource_json TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE effects (
  effect_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL,
  purpose_id TEXT,
  action_class TEXT NOT NULL,
  idempotency_key TEXT,
  dispatch_state TEXT NOT NULL,
  request_json TEXT NOT NULL,
  receipt_id TEXT,
  verifier_state TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE outbox (
  outbox_id TEXT PRIMARY KEY,
  effect_id TEXT NOT NULL,
  destination TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE action_receipts (
  receipt_id TEXT PRIMARY KEY,
  effect_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  provider_id TEXT,
  result_class TEXT NOT NULL,
  result_digest TEXT,
  external_ref TEXT,
  observed_at TEXT NOT NULL,
  receipt_json TEXT NOT NULL
);

CREATE TABLE erasure_tombstones (
  erasure_id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  erasure_generation INTEGER NOT NULL,
  requested_at TEXT NOT NULL,
  applied_at TEXT,
  source_event_id TEXT NOT NULL
);

CREATE TABLE provider_registry (
  provider_id TEXT PRIMARY KEY,
  capability TEXT NOT NULL,
  descriptor_json TEXT NOT NULL,
  artifact_digest TEXT,
  descriptor_digest TEXT NOT NULL,
  tool_schema_digest TEXT,
  lifecycle_state TEXT NOT NULL,
  health_state TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Do not add a graph database in 1.0.

---

# 8. Transaction boundaries

## 8.1 User turn

One user turn is not one giant transaction.

Recommended flow:

```
TX1:
  canonical user event
  minimal transient state
COMMIT

retrieve / model / tools

TX2:
  canonical assistant final event
  accepted claims/facts
  purpose mutations
  effect intents + outbox rows
COMMIT

async:
  projection rebuild / indexes / telemetry
```

If the model fails after TX1, the user message still exists and recovery can resume or mark the turn failed.

## 8.2 External effect + outbox

State mutation and dispatch request must be atomically committed:

```python
with db.transaction():
    save_effect_intent(effect)
    save_authorization_decision(decision)
    enqueue_outbox(outbox_row)
```

Dispatcher runs only after commit.

Never:

```
call_external_api()
then save_effect()
```

## 8.3 Unknown dispatch

If process crashes after sending but before persisting the receipt:

```
dispatch_state = UNKNOWN
```

Recovery:

1. query downstream by idempotency/external reference if possible;
2. reconcile;
3. if impossible, require policy-specific decision;
4. never blind retry an irreversible operation.

---

# 9. Purpose state machine and time semantics

States:

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

Owner:

```
USER
XIAOYU
SHARED
```

A Goal is not executable. An Intention is bounded work. A Purpose is a concrete pending commitment/watch/reminder/task.

## 9.1 Time fields

Store both user intent and resolved time:

```
scheduled_wall_time
timezone
resolved_utc_time
created_at
last_evaluated_at
```

Do not store only naive local datetime.

## 9.2 Miss policy

Every scheduled purpose declares:

```
DELIVER_LATE
SKIP_IF_MISSED
RESCHEDULE
ASK
RECONCILE
```

## 9.3 Resume handling

On wake/resume:

1. capture previous suspend time;
2. calculate missed purposes;
3. apply each purpose's `miss_policy`;
4. deduplicate by purpose + delivery ledger;
5. do not flood the user with every missed low-priority event.

---

# 10. Permission and external effects

Risk tiers:

```
T0 OBSERVE
T1 LOCAL_REVERSIBLE
T2 OWNER_STATE_MUTATION
T3 EXTERNAL_OR_IRREVERSIBLE
```

LLM output never directly executes a T2/T3 action.

Pipeline:

```
Model proposal
  -> Intent validator
  -> Principal resolution
  -> Actor/delegation resolution
  -> Authorization
  -> Effect intent
  -> Transactional outbox
  -> Dispatcher
  -> Receipt
  -> Verifier
  -> Purpose completion/reconciliation
```

## 10.1 Authorization completeness

Tests must verify both:

- DENY/ASK never execute early;
- ALLOW either completes, explicitly fails, or enters reconciliation. It may not silently disappear.

## 10.2 Action receipt

1.0 internal receipt fields:

```
receipt_id
effect_id
actor_id
provider_id
authorization_decision_id
request_digest
result_class
result_digest
external_ref
observed_at
```

1.x may add previous-receipt hash/signature.

---

# 11. Capability Contract v0.2

Every provider descriptor includes:

```json
{
  "id": "qwen3-tts-local",
  "capability": "speech.tts",
  "implementation_version": "0.4.0",
  "contract": {
    "name": "xiaoyu.speech.tts",
    "min_version": "1.0.0",
    "max_exclusive": "2.0.0"
  },
  "artifact_digest": "...",
  "descriptor_digest": "...",
  "interface_digest": "...",
  "isolation": "sidecar",
  "features": {
    "streaming": true,
    "cancel": true
  },
  "data_classes": ["assistant_text"],
  "permissions_required": ["audio.output"],
  "fallback_group": "speech.tts.default",
  "lifecycle": "ACTIVE"
}
```

New mandatory security fields:

- `artifact_digest`;
- `descriptor_digest`;
- `interface_digest`;
- for MCP/tool providers: `tool_schema_digest`;
- declared data classes;
- lifecycle state.

If any approved digest changes, prior standing approval is invalidated.

Lifecycle:

```
ACTIVE
DEPRECATED
RETIRING
SHUTDOWN
DISABLED
```

Health is three-dimensional:

```
liveness
readiness
capability_health
```

---

# 12. Runtime Router

Selection:

```
compatible contract
∩ required features
∩ enabled
∩ healthy enough
∩ privacy eligible
∩ data-class eligible
∩ resource eligible
∩ lifecycle eligible
```

Then rank:

1. explicit user pin;
2. locality/privacy;
3. quality;
4. latency;
5. resource pressure;
6. cost.

Fallback modes:

```
SAFE_RETRY
REPLAYABLE
READ_ONLY_ONLY
NO_FALLBACK
MANUAL_RECONCILIATION
```

A local failure never implicitly enables cloud disclosure.

---

# 13. ResourceBroker

Provider metrics alone are insufficient. The Runtime Host owns reservations.

```python
@dataclass
class ResourceRequest:
    provider_id: str
    ram_mb: int
    vram_mb: int
    gpu_required: bool
    priority: int
    preemptible: bool
    warm_residency_s: int
```

Modes:

```
ECO
BALANCED
FULL
GAME
SLEEP
```

Required behavior:

- do not start two providers whose combined VRAM budget exceeds configured safe headroom;
- allow low-priority vision/retrieval models to unload before TTS/foreground work;
- no-GPU path remains valid;
- GAME mode releases optional GPU residency;
- SLEEP mode drains sidecars except explicitly allowed wake functionality;
- collect measured, not guessed, RAM/VRAM.

For the current RTX 4060 Laptop target, configure budgets empirically; do not hard-code model assumptions into Core.

---

# 14. Power lifecycle

Runtime Host states:

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

Required hooks:

- stop capture/watchers on suspend;
- flush critical transactions before suspend where possible;
- mark active external effects before process suspension;
- on resume, health-check sidecars before routing traffic;
- re-evaluate expired principal/delegation context;
- run Purpose miss-policy reconciliation;
- do not assume elapsed monotonic time equals wall-clock intent.

---

# 15. Memory-use policy

Retrieval quality alone is not enough.

Pipeline:

```
Turn
  -> cheap memory-need classifier / rules
  -> candidate retrieval
  -> evidence relevance
  -> authorization/audience filter
  -> context budget
  -> USE | ABSTAIN
```

Keep a no-memory baseline.

New metrics:

- Memory Intervention Precision;
- Memory Intervention Recall;
- stale-memory injection rate;
- irrelevant-memory injection rate;
- answer delta vs no-memory baseline.

Do not force top-k memory into every turn.

---

# 16. Profile and Relationship

## 16.1 Profile

Profile is evidence-linked projection:

```
stable preferences
important people
active long-term projects
interaction style
proactivity settings
```

Every field stores source fact IDs.

Add Profile Shock tests: new strong evidence must be able to overturn an old stable preference.

## 16.2 Relationship

Move relationship out of SELF.

```
RelationshipState
  principal_id
  relation_kind
  shared_history_projection
  interaction_norms
  trust_state
  boundaries
  source_fact_ids
```

SELF remains only XiaoYu identity/persona.

Guest/other principals never mutate owner relationship state without explicit semantic mapping.

---

# 17. Voice implementation

Do not build two complete voice runtimes.

Decision tree:

```
Voice Contract / Acceptance
       |
       v
Pipecat Spike
   | PASS               | MATERIAL FAIL
   v                    v
Pipecat adapter       Minimal custom runtime
```

Semantic rules:

- ASR final text becomes the canonical user turn;
- silence never becomes a turn;
- TTS is presentation only;
- assistant text remains canonical;
- interruption/cancel is first-class;
- voice provider failure falls back to text without affecting identity/memory.

Data-plane audio may use streaming transport; lifecycle/permissions stay on control plane.

---

# 18. Vision implementation

Preferred 1.0 flow:

```
capture sidecar
  -> local change scoring
  -> selected frames/storyboard
  -> Vision provider
  -> UNTRUSTED_OBSERVATION
  -> Core
```

Commands:

```
status
peek
watch
stop
region
shutdown
```

Rules:

- raw frames not durable by default;
- provider disclosure is logged;
- OFF means capture process is actually stopped;
- sensor projections have TTL;
- expired sensor state becomes UNKNOWN;
- visual text cannot self-authorize tools or durable memory writes.

---

# 19. Surface contract

Every surface implements:

```python
class SurfaceAdapter(Protocol):
    async def ingest(self, raw_input) -> InputSourceEnvelope: ...
    async def deliver(self, delivery) -> DeliveryReceipt: ...
    async def status(self) -> SurfaceHealth: ...
```

Surface cannot:

- write memory tables directly;
- maintain a second persona;
- bypass principal/audience policy;
- independently retry irreversible effects;
- own provider credentials beyond its scoped reference.

Desktop and QQ must pass the same canonical-turn path.

---

# 20. Skill and tool model

## 20.1 First-party tools

Trusted only for implementation integrity, not automatically authorized for all actions.

## 20.2 MCP

Approval binds to:

```
provider_id
artifact/transport identity where available
descriptor_digest
tool_schema_digest
capability_set
resource scope
```

Schema/capability change -> approval invalid.

## 20.3 Agent Skills

Use Agent Skills / `SKILL.md` as interchange format.

XiaoYu adds admission lifecycle:

```
CANDIDATE
SCANNED
SANDBOX_TESTED
VERIFIED
ADMITTED
DEGRADED
RETIRED
```

Admission:

```
provenance
-> instruction scan
-> code scan
-> capability request
-> sandbox replay
-> filesystem/network observation
-> verifier
-> admit
```

## 20.4 Wasm

1.x contract-first target:

- WIT/WASI interface;
- Wasmtime reference runtime;
- explicit host imports.

Every host bridge is a capability. A sandbox is not trusted merely because code runs inside Wasm.

---

# 21. Backup, restore and erasure

Managed backups must not resurrect deleted state.

## 21.1 Backup

Backup contains:

- DB snapshot;
- schema version;
- release ID;
- erasure generation;
- manifest digest.

Secrets are excluded by default.

## 21.2 Restore

Mandatory restore pipeline:

```
restore candidate
-> sqlite integrity_check
-> schema/migration validation
-> canonical invariant check
-> reapply newer erasure tombstones
-> rebuild projections/indexes
-> identity regression smoke
-> activate
```

Never activate a recovered DB immediately after raw recovery.

## 21.3 Erasure

User deletion creates an erasure tombstone with monotonic generation.

Deletion cascade must remove or invalidate:

- authoritative target;
- retrieval index;
- profile projection;
- dossier;
- derived summaries;
- skill/memory candidates that solely depend on target;
- future managed restore resurrection.

Historical unmanaged exports require explicit warning/confirmation on import.

---

# 22. Release Authority

Release state:

```
CURRENT
CANDIDATE
LAST_KNOWN_GOOD
REJECTED
```

Release manifest minimally records:

```
release_id
core_commit
schema_version
contract_versions
provider descriptors + digests
model artifact/config/tokenizer revisions
skill digests
native executable digests
migration version
evaluation results
created_at
```

Candidate promotion requires:

1. schema migration dry-run;
2. provider conformance;
3. identity regression;
4. memory regression;
5. permission/effect regression;
6. restore smoke;
7. minimum soak;
8. no P0 blocker.

Provider/model switch alone is a release-relevant change if it can alter behavior.

Credentials are not included in identity export; restored installations re-authorize external accounts.

---

# 23. Secure update

Do not build a custom updater for 1.0.

For future packaged Windows release, prefer standard signed packaging/update path.

Required semantics regardless of mechanism:

- artifact signature/digest verification;
- rollback protection;
- last-known-good;
- staged candidate;
- no silent downgrade;
- migration compatibility check before activation.

---

# 24. Observability and Guardian

## 24.1 Telemetry

Default telemetry records metadata only:

```
trace_id
turn_id
provider_id
model
latency
tokens
status
tool name
effect_id
resource metrics
```

Do not record by default:

- prompt text;
- memory text;
- retrieved document body;
- tool arguments/results containing personal data;
- screen OCR;
- audio transcript beyond canonical conversation storage policy.

## 24.2 Guardian

Independent, no LLM, no identity mutation.

Monitors:

- Core liveness;
- sidecar tree;
- restart loops;
- backup failures;
- provider integrity failure;
- runaway RAM/VRAM/CPU;
- repeated denied effect attempts;
- release integrity.

Guardian logs cannot be deleted by a compromised provider.

---

# 25. Crash and corruption tests

Required controlled crash points:

```
before user event commit
after user event commit
before assistant event commit
after intent persistence
before outbox dispatch
after external send / before receipt
after receipt / before verification
before purpose completion
during backup
during migration
```

Corruption tests:

- disk full;
- read-only DB;
- WAL failure;
- malformed migration;
- partially recoverable DB;
- projection/index corruption.

Pass condition: Core either recovers to a known semantic state or stops fail-closed with a precise repair path. It must not silently continue on uncertain authority state.

---

# 26. 1.0 acceptance gates

P0 release blockers:

1. identity split across restart/provider/surface: 0;
2. deterministic memory mutation errors: 0;
3. deleted active fact resurrection in managed restore: 0;
4. DENY/ASK unauthorized external effect: 0;
5. allowed irreversible effect silently lost: 0;
6. controlled crash duplicate effect: 0;
7. stale turn persisted over fresher turn: 0;
8. duplicate purpose delivery: 0;
9. provider digest/schema change retaining stale approval: 0;
10. privacy-ineligible cloud fallback: 0;
11. unreconciled sleep/resume scheduled actions: 0;
12. failing restore activated as healthy: 0.

Performance targets remain in `VALIDATION_AND_ACCEPTANCE_PLAN.md`; this document defines semantics.

---

# 27. Do not implement before 1.0

Explicitly deferred unless required by a blocker:

- general computer-use autonomy;
- multi-master Core;
- CRDT;
- graph database;
- always-on ambient lifelog;
- Bilibili/social expansion;
- household mode;
- Quest/VR;
- generalized self-generated goals;
- arbitrary self-modifying skills;
- custom updater;
- distributed workflow engine;
- signed action-receipt chain;
- full A2A peer topology.

Future A2A is an adapter to external execution, not an internal truth authority.

---

# 28. Composition root pseudocode

```python
async def build_app(config):
    db = Database(config.db)
    release = ReleaseAuthority(db, config.release)
    await release.verify_current()

    core = SemanticCore(
        db=db,
        identity=IdentityService(db),
        memory=MemoryAuthority(db),
        purpose=PurposeService(db),
        authz=AuthorizationService(db),
        effects=EffectService(db),
    )

    resources = ResourceBroker(config.resources)
    supervisor = SidecarSupervisor(resources)
    registry = ProviderRegistry(db, supervisor)
    router = CapabilityRouter(registry, resources, core.authorization)
    outbox = OutboxDispatcher(db, registry, core.effects)
    scheduler = PurposeScheduler(core.purpose, outbox)
    power = PowerLifecycle(scheduler, supervisor, resources)

    runtime = RuntimeHost(
        router=router,
        supervisor=supervisor,
        resources=resources,
        scheduler=scheduler,
        outbox=outbox,
        power=power,
    )

    surfaces = await build_surfaces(config, core, runtime)

    return XiaoYuApp(
        core=core,
        runtime=runtime,
        surfaces=surfaces,
        release=release,
    )
```

Canonical turn:

```python
async def handle_input(surface, raw_input):
    envelope = await surface.ingest(raw_input)

    principal = core.resolve_principal(envelope)
    audience = core.authorize_context(principal, envelope)

    event = core.events.persist_inbound(envelope, principal)

    context = core.context.build(
        event=event,
        principal=principal,
        audience=audience,
        memory_policy="adaptive",
    )

    response = await runtime.router.invoke("llm.chat", context)

    final = core.turns.finalize(event, response)

    mutations = core.memory.derive_candidates(final)
    core.memory.commit_allowed(mutations)

    await runtime.outbox.kick()

    return final
```

This pseudocode is the desired dependency direction, not a requirement to copy names verbatim.

---

# 29. Freeze boundary for 1.0

Freeze these public contracts before feature work expands again:

- `InputSourceEnvelope`;
- `PrincipalContext`;
- `ActorContext`;
- `Delegation`;
- `AuthorizationDecision`;
- `EffectIntent`;
- `ActionReceipt`;
- `CapabilityDescriptor`;
- `ProviderHealth`;
- `SurfaceAdapter`;
- Purpose states/time/miss-policy;
- authoritative event/claim/fact distinction.

Implementation details behind them may continue changing.

---

# 30. Final implementation principle

The simplest test for any new module is:

> If this provider, model, UI, machine or protocol disappears tomorrow, can XiaoYu keep the same identity, authoritative history, permissions and unfinished purposes?

If yes, the boundary is probably correct.

If no, implementation-specific state has leaked into the semantic authority and must be moved back behind a contract.
