# XiaoYu Trust-Layer External Survey — Lead Digestion / Integration Decision

Date: 2026-10-27
Status: **DIGESTED INTO P1/P2/P3 BOUNDARIES**

This note is deliberately shorter than the external-gap survey. It records what actually changes the project after Lead reconciliation with the live integration contract, backlog and control plane.

## Accepted as immediate P1 architecture requirements

### 1. Origin-bound authority / non-amplification

Authority is metadata established at trusted source ingress. It is not inferred from text and cannot silently increase because the same claim is:
- summarized;
- repeated;
- consolidated;
- assigned high model confidence;
- echoed by a tool;
- restated by an assistant.

R17 remains the trusted-message authority projection gate.
R21 is now a separate required P1 lifecycle falsifier for poisoning/laundering/repair.

### 2. Persistent-memory poisoning is distinct from ordinary hallucination

HaluMem-style extraction/update/QA correctness does not by itself prove resistance to a durable malicious memory that later changes behavior.

R21 is therefore a required P1 integration stage:
- write/admission;
- authority laundering attempts;
- retrieval/context exposure;
- downstream steering;
- selective repair;
- non-recurrence.

No new scanner or security framework is authorized; it must reuse the accepted source/authority/validation stack.

### 3. Retrieval admissibility precedes model-visible context

Relevance and admissibility are separate.

The P1 chain is now:

source/evidence
→ validated projection
→ typed state
→ source-aware retrieval candidates
→ **principal/scope/authority/lifecycle admissibility**
→ model-visible context
→ answer

R22 is a required P1 stage.

Wrong-principal, wrong-scope, deleted, quarantined or otherwise inadmissible memory may not be exposed to the model and then suppressed by prompting.

## Accepted, but explicitly deferred to P2

These are real capability gaps but must not steal P1 research slots:

- R23 — derived-state dependency/rule-version propagation;
- R24 — behavioral deletion closure / reconstruction counterfactual;
- R25 — whole-store rollback/replay/control-state integrity.

All three are now `status=hold` with explicit P1-freeze unlock conditions.

This is important: discovering a valid future problem does not make it a current integration blocker.

## Accepted, but deferred to P3 / scope expansion

- R26 portable-memory interoperability remains HOLD.
- Relationship/persona memory uses DyadMem/PersonaTree as later references.
- Procedural/action memory uses public benchmark references rather than a private benchmark.
- Multimodal, group and multi-agent memory remain schema-compatibility concerns, not current implementation scope.

## What does NOT change

The production direction remains thin:

immutable/trusted source
→ origin-bound authority
→ validated semantic events
→ typed current/history state
→ SQLite/FTS5 + reused optional semantic mechanism
→ deterministic admissibility
→ source-aware context
→ answer
→ response/evidence validation

No evidence justifies replacing this with Mem0, Hindsight, Cognee, Graphiti, a graph DB, a new vector DB, a generic provenance platform or another memory framework.

## Integration contract changes made by Lead

`governance/P1_INTEGRATION_CONTRACT.json` now contains two additional required P1 stages:

- `memory_security_lifecycle` → R21
- `retrieval_admissibility` → R22

`context_packing` now explicitly depends on admissibility.

The integration doctor is also dependency-aware:
- an individually accepted/ready stage is not counted integration-ready if its upstream stage is blocked;
- missing dependency IDs make the contract unhealthy;
- blocked dependencies are readiness blockers, not false contract errors.

The current dependency chain explicitly connects:
- semantic extractor + source identity → response validation;
- source identity + validated response → trusted authority;
- trusted authority + validated response → typed state;
- typed state → source-aware retrieval;
- retrieval → admissibility;
- admissibility → context;
- trusted authority + context → memory-security lifecycle;
- typed state + retrieval → erasure/restore reconciliation.

## Backlog phase correction

The external survey originally left R23/R24/R25 as active P2 rows. Because `continuation.py` selects any active task by priority, that would have allowed later-phase work to consume P1 slots.

Corrected:
- R21/R22: P1_REQUIRED, priority 0, active;
- R23/R24/R25: P2_AFTER_P1_FREEZE, HOLD;
- R26: P3_INTEROP, HOLD.

A live `_specs()` check confirms only R21/R22 from R21–R26 are auto-assignable.

## Machine-readable policy changes

`policy.json` now includes:
- `authority_is_origin_bound_and_cannot_be_silently_amplified_by_derivation`;
- `inadmissible_memory_must_be_filtered_before_model_visible_context`;
- a `trust_layer` section binding R17/R21/R22 and listing deferred P2/P3 gates.

## Validation

Latest governance regression after reconciliation:
- **87/87 PASS**

P1 Integration Doctor:
- contract_errors: []
- warnings: []
- contract_healthy: true
- required stages: 11
- integration_ready: false
- e2_claim_allowed: false

The increase from the prior 9 required P1 stages to 11 is intentional and limited to the two trust-layer properties that affect safety of the current text-memory pipeline.

## Final interpretation

The survey is valuable because it changes **trust semantics**, not because it adds more memory machinery.

The key refinement is:

> memory correctness is not enough; a P1 memory must also preserve source authority and be admissible for the current context before the model can see it.

All other newly identified capabilities remain scheduled behind the current P1 freeze unless their explicit unlock condition is met.
