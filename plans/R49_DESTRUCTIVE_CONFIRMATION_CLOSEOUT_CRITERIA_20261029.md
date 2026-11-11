# R49 E2 closeout criteria — destructive semantic uncertainty boundary — 2026-10-29

Status: **LEAD CLOSEOUT CRITERIA / NOT A PASS DECISION**

## Why the closeout criterion changes

Prospective evidence has falsified deterministic lexical/regex destructive-semantic authorization as sufficient:

- independent Auditor prospective80: current v6 **40 / 80**;
- Lead prospective150: current v6 **98 / 150**;
- the current paid 16-case HaluMem canary contains **0 actual destructive proposals** and **0 source positions with componentized target + destructive intent**.

At the same time, current v6 remains strong as a structural safety layer on its development/regression suites.

Therefore R49 no longer requires a model or lexical rule to be trusted as an autonomous destructive-state authority. It requires a safe boundary for semantic uncertainty.

## Required architecture

### Layer A — deterministic structural authority

Retain v6/R47 deterministic ownership for:

- source identity and source role;
- target candidate membership;
- complete conflict components;
- authority / lifecycle / principal;
- exact evidence quote and source hash;
- generation / replay identity;
- R47 state mutation mechanics.

A model never owns these fields.

### Layer B — untrusted semantic proposal

The semantic projector may propose:

- NEW;
- SUPERSEDE;
- RETRACT;
- CONFLICT.

For destructive relations, the proposal is **not authoritative**.

A destructive proposal must enter a pending state containing at least:

- relation;
- proposed claim;
- exact evidence quote;
- source hash;
- exact caller-owned target component;
- current R47 generation/revision;
- immutable proposal identity.

### Layer C — destructive confirmation boundary

Until confirmed:

- authoritative R47 state is byte/semantic unchanged;
- current view is unchanged;
- supersession/retraction/conflict edges are not activated;
- proposal cannot become retrieval-authoritative current state.

Confirmation must be bound to the exact pending proposal, source hash, target component and current generation.

Required operations:

- confirm;
- reject/cancel;
- expiration/invalidation;
- replay/retry.

### Layer D — optional semantic adjudicator

The frozen semantic adjudicator may be evaluated as **research evidence to reduce unnecessary confirmations**.

An adjudicator `approve` is not, by itself, product authorization for destructive memory mutation.

Product auto-apply would require a separate future policy and evidence gate.

## Mandatory confirmation-boundary falsifiers

A candidate cannot close R49 unless an independent Auditor demonstrates all of the following:

1. **Unconfirmed non-mutation**
   - supported and unsupported SUPERSEDE/RETRACT/CONFLICT proposals leave authoritative state unchanged.

2. **Exact confirmation binding**
   - confirmation applies only to the exact pending proposal/source/target/generation.

3. **Stale generation rejection**
   - if target state changes after proposal creation, old confirmation fails closed.

4. **Cross-branch / cross-target rejection**
   - a confirmation for one component cannot authorize another component or relation.

5. **Source-drift rejection**
   - same text under a different source identity/hash cannot reuse confirmation.

6. **One-shot / replay safety**
   - duplicate confirmation/retry cannot apply the transition twice or create duplicate descendants.

7. **Reject/cancel**
   - rejected or cancelled proposal never mutates authoritative state and cannot later be confirmed without a new proposal.

8. **Ambiguous component fail-closed**
   - ambiguous/missing target binding never enters a confirmable destructive mutation path.

9. **Conflict resolution integrity**
   - confirmation that resolves one complete conflict component cannot silently consume an incomplete/foreign component.

10. **Erasure/lifecycle freshness**
    - confirmation cannot revive an erased, tombstoned, stale or otherwise inadmissible target/source.

11. **Restart persistence**
    - pending/confirmed/rejected state survives restart consistently; a crash between confirmation and commit cannot create partial destructive state.

12. **Prospective semantic false positives become harmless**
    - at minimum the independent prospective80 and fresh prospective150 false-positive destructive proposals must be demonstrably non-mutating before confirmation.

## Required non-safety metrics

Safety alone is not enough for capability quality. Report separately:

- confirmation rate per real destructive opportunity;
- false-confirmation burden / unnecessary-confirmation rate;
- missed destructive opportunities;
- confirmation-to-apply success;
- user-facing ambiguity rate;
- latency/cost if semantic adjudicator is used.

These are usability/research metrics, not permission to weaken the safety boundary.

## Natural HaluMem coverage

The existing 16 paid HaluMem canary cannot support destructive closeout because it exercised no destructive proposal.

A future natural-path packet may use only already-exposed pilot source history and must:

- process earlier raw source normally rather than fabricate prior targets;
- prove a complete caller-authorized prior component exists before the later destructive source;
- avoid memory_points, original_memories, questions, answers and gold;
- remain nonpromotional.

Current discovery candidate:
`governance/lead_workspaces/r49_semantic_adjudicator_20261029/HALUMEM_NATURAL_DESTRUCTIVE_PACKET_CANDIDATE.json`

It is **not paid-authorized and not independently labeled**.

## E2 closeout rule

R49 can close only when:

- the product candidate preserves the accepted structural v6/R47 invariants;
- independent E1 audit accepts the destructive confirmation boundary;
- all material P0/P1 findings are closed;
- any paid evidence cited is bound to committed proxy call IDs and actually covers the claimed path;
- confirmatory E2 remains separately locked until its own protocol transition.

Semantic adjudicator quality can strengthen R49 capability evidence, but R49 safety closeout must not depend on trusting an unconfirmed model destructive decision.
