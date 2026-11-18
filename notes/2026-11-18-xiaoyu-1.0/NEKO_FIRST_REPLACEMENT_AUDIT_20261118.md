# N.E.K.O-first replacement audit — 2026-11-18

Status: **REPLACEMENT SPIKE / NO BIG-BANG CUTOVER**

Base frontier: `feat/reuse-first-credentials` @ `8f4d5d24ba399d30b0c510ad1dd3c3842c497103`

External source snapshots inspected:

- Project N.E.K.O: `e14f6196395a346ff422e0eb852c5eae3befc1cf`
- Cyrene-Agent: `852ec5765183ea62c45eba8a3db0a5aae2b74bbb`
- Psycheros/entity-core: `724987dc072a0bbc9914be58c73efc278154a410`

## 1. Decision

Do not extend XiaoYu as a parallel general-purpose companion/agent framework while this spike is active.

The preferred replacement hypothesis is:

> **Project N.E.K.O becomes the primary upstream product/runtime. XiaoYu becomes a thin conformance/policy delta.**

This is not yet a deletion or migration authorization. Existing XiaoYu authority remains frozen and usable until the replacement acceptance suite passes.

Cyrene-Agent remains a product/UX/channel reference, especially for Windows policy and QQ group behavior. Psycheros/entity-core remains an identity-continuity comparator. Neither should become a second identity/memory authority under N.E.K.O.

## 2. Why N.E.K.O is now the primary candidate

The source audit found substantially more overlap with XiaoYu than README-level research suggested.

### Memory / identity / relationship

N.E.K.O already implements:

- scoped long-term facts with provenance and speaker trust;
- temporal event windows and stale-state handling;
- persona correction with version history;
- private/scoped persona separation;
- formative/persona state and social/person-derived state;
- evidence-driven reflection/promotion;
- pinned important facts;
- explicit commitments with `open/done/expired`, due time or condition, proactive surfacing and completion;
- import/fusion of external memory.

### Erasure / restore safety

N.E.K.O has product semantics close to XiaoYu's strongest R9/R17 requirements:

- per-subject/scope erase generation;
- extraction generation captured before LLM work and rechecked before persistence;
- persistent forget tombstones written before recoverable copies are deleted;
- strict removal from active/archive/cold storage and FTS;
- restore/forget locking so restore cannot race forget and reappend old shards;
- fail-closed behavior when an erasure-relevant shard cannot be read;
- reflection/persona scoped-forget cleanup.

Dedicated upstream tests cover cold-store erasure, pending/dedup cleanup, embedding-worker generation fencing and restore/sync behavior.

A local directed pytest attempt did not reach collection because the machine's global Python lacks `nest_asyncio`; this is an environment dependency gap, not a test failure. No global environment was modified.

### QQ / NapCat / multi-surface

N.E.K.O already contains:

- OneBot v11 reverse WebSocket;
- `napcat_forward` forward WebSocket with reconnect/backoff;
- NapCat extension actions;
- private/group normalization;
- QQ Open Platform connectors;
- identity-scope regression tests;
- token redaction and connection lifecycle tests.

Therefore a separate Cyrene runtime is not justified solely for the existing NapCat/QQ requirement.

### Agent / task / extension surface

N.E.K.O already has:

- durable commissions/task ledger;
- task dispatch receipts and duplicate handling;
- durable outbox for task reports;
- restart/retry paths;
- tool/MCP permission gates;
- plugin SDK;
- adapter gateway pipeline:
  `Normalizer -> PolicyEngine -> RouteEngine -> PluginInvoker -> ResponseSerializer`;
- entry AOP hooks: before / after / around / replace;
- message/event/timer hooks.

This makes a thin XiaoYu policy/effect plugin plausible without forking the memory core.

## 3. Confirmed N.E.K.O gaps that still matter

### G1 — provider disclosure / privacy eligibility

The inspected provider registry and API profiles contain no equivalent of XiaoYu's:

- `privacy_class`;
- `privacy_eligible`;
- `data_class`;
- `audience_scope`;
- `owner_private` / `group_shared`;
- provider-session reset eligibility.

N.E.K.O supports many providers and runtime fallback, but no evidence was found that a private-context request is forbidden from falling back to a privacy-ineligible provider.

**Verdict:** retain a small XiaoYu provider disclosure/freshness policy layer.

### G2 — external side-effect uncertainty

N.E.K.O's task `Receipt` / ledger / outbox semantics cover task acceptance, task state and report delivery.

They are not equivalent to XiaoYu R6/R7's external-effect boundary:

> non-idempotent external call may have crossed the transport boundary, local ACK is lost, state becomes `UNKNOWN`, and the system reconciles instead of blindly retrying.

**Verdict:** retain a small XiaoYu high-risk Effect/UNKNOWN/reconciliation fence.

### G3 — exact historical point-in-time truth

N.E.K.O has temporal windows, correction history and stale-state semantics, but the source audit did not find an exact equivalent of XiaoYu's arbitrary historical point-in-time fact authority/query contract.

**Verdict:** do not preserve the whole R9 engine by default. Keep this capability only if a product acceptance case proves it is required.

### G4 — release semantics

N.E.K.O has release/update/health machinery, but no evidence yet that it needs or matches XiaoYu's full R18 semantic release authority.

**Verdict:** target a much thinner upstream-version pin + migration/conformance gate. Do not preserve R18 complexity merely for architectural symmetry.

## 4. R1–R22 replacement map

| XiaoYu area | N.E.K.O-first verdict | Permanent XiaoYu code target |
|---|---|---|
| R1 package seams | RETIRE as product architecture | migration shim only |
| R2 contracts/envelopes | REPLACE MOSTLY with N.E.K.O/plugin contracts | adapters at external boundaries only |
| R3 persistence/migrations | RETIRE as general persistence layer | one-way importer + cutover evidence |
| R4 canonical event authority | RETIRE MOSTLY | only effect/migration audit events if needed |
| R5 authorization | KEEP THIN | audience/provider/effect policy only |
| R6 transactional Effect/outbox | KEEP THIN | high-risk external side effects only |
| R7 receipts/delivery | KEEP THIN | UNKNOWN/reconciliation only |
| R8 Purpose/time/power | REPLACE MOSTLY | only missing miss/cancel semantics proven by tests |
| R9 temporal truth | REPLACE MOSTLY | historical point query only if benchmark requires it |
| R10 profile/relationship/promise | REPLACE | N.E.K.O persona/social/commitments |
| R11 memory use/context | REPLACE | upstream memory/context |
| R12 RuntimeHost/provider lifecycle | REPLACE MOSTLY | provider privacy/freshness admission fence |
| R13 resource/presence | REPLACE | upstream/product runtime + mature telemetry |
| R14 vision | REPLACE | N.E.K.O |
| R15 voice | REPLACE | N.E.K.O |
| R16 audience/guest isolation | KEEP THIN | cross-surface/provider disclosure conformance |
| R17 recovery/erasure/migration | REPLACE MOSTLY | importer + conformance tests; upstream owns storage erase |
| R18 release authority | RETIRE MOSTLY | upstream pin + migration smoke + integrity metadata |
| R19 Guardian/telemetry | RETIRE MOSTLY | external telemetry + acceptance/conformance tests |
| R20 memory/product controls | REPLACE MOSTLY | XiaoYu-specific UX policy only |
| R21 Desktop <-> QQ E2E | REPLACE IMPLEMENTATION | configure N.E.K.O OneBot/NapCat; keep E2E tests |
| R22 soak/freeze | KEEP AS VALIDATION | acceptance/soak only, not new runtime |

## 5. Replacement acceptance suite

No production cutover is allowed until the N.E.K.O-based spike demonstrates all of the following.

1. **Identity continuity:** same XiaoYu persona/state across restart, model swap and desktop/QQ surfaces.
2. **Private -> group isolation:** private memory cannot appear in group context unless explicitly admissible.
3. **Provider privacy:** private context cannot fall back to a provider marked privacy-ineligible.
4. **Correction:** a user correction stops obsolete facts/persona from being used as current truth.
5. **Erasure closure:** scoped forget removes active/archive/cold/index/derived state.
6. **No resurrection:** restoring an older snapshot cannot revive erased material.
7. **In-flight erase race:** extraction started before forget cannot write the erased fact back afterward.
8. **QQ identity scope:** NapCat private/group participant identity remains correctly scoped.
9. **Commitment continuity:** due/conditional commitments survive restart and can be completed/cancelled without duplicate proactive delivery.
10. **External effect ACK loss:** a non-idempotent action with uncertain result becomes UNKNOWN and is not blindly retried.
11. **Import/export:** current XiaoYu confirmed state can be imported deterministically with provenance and without widening scope.
12. **Product E2E:** desktop + voice/vision + QQ + agent tools remain usable under the same persistent companion identity.

The spike loses only when a missing behavior materially harms the project goal. Minor implementation differences are not failures.

## 6. Implementation rule during the spike

Until the acceptance suite resolves the architecture:

- continue blocker/red-team fixes that protect current user data or execution correctness;
- do not create new R-number product architecture merely because the old plan listed it;
- do not add a second memory/identity authority;
- prefer N.E.K.O plugin/adapter/hooks over upstream-core patches;
- deep-fork N.E.K.O only after a concrete extension-surface gap is demonstrated;
- Cyrene/Psycheros/Alicization/Miru remain mechanism references, not additional runtimes.

## 7. Target end-state if the spike passes

```text
Project N.E.K.O upstream
├─ companion UI / embodiment
├─ voice / vision / proactive presence
├─ memory / persona / social state / commitments
├─ scoped erasure / restore
├─ QQ / OneBot / NapCat
├─ MCP / plugins / tools
├─ task commissions / task-report outbox
└─ provider/product runtime

XiaoYu delta
├─ provider disclosure + freshness fence
├─ high-risk external Effect UNKNOWN/reconciliation
├─ XiaoYu persona/product policy
├─ current-data importer
├─ upstream-version/conformance gate
└─ acceptance + regression suite
```

The permanent XiaoYu implementation should aim to be a **small separable layer**, not a forked companion platform. A reasonable engineering target is a low-thousands-of-LOC production delta excluding tests and one-time migration code; this is a target to validate, not a claimed current result.

## 8. Current provisional verdict

**N.E.K.O is the only candidate found so far that simultaneously covers the companion product, memory/relationship system, strong erasure semantics, QQ/NapCat, agent/plugin runtime and extension surface closely enough to justify a mother-project replacement spike.**

Cyrene-Agent remains useful as a Windows/channel/policy reference. Psycheros/entity-core is not selected because its documented permanent-memory philosophy and snapshot restore semantics conflict with XiaoYu's deletion-no-resurrection requirement.

Do not merge architectures. Test N.E.K.O as the single primary upstream first.
