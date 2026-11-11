# R49 v5 exact-snapshot Lead finding — 2026-10-29

Status: **CURRENT V5 SNAPSHOT NEEDS WORK / NO PAID AUTHORIZATION**

Exact Research Engineer snapshot:
- source: `governance/workspaces/fish-ec14df2b088b4b95/r49_semantic_contract_v5.py`
- snapshot SHA256: `f13328853756edc811ef0ea74edb73c77555e8a5b24a233a341d151a85ebc115`
- snapshot was byte-stable during Lead copy.
- provider calls during Lead evaluation: 0.
- confirmatory users read: 0.

## What the snapshot fixes

Pre-frozen registry/OOD gate:
- **120 / 120 PASS**
- shared_anchor_distinct 20/20
- duplicate_with_registry 20/20
- duplicate_without_registry 20/20
- incomplete_registry 20/20
- single_relevant_plus_unrelated 20/20
- two_distinct_relevant 20/20

The candidate correctly separates lexical relevance from explicit equivalence membership.

## What still fails

RE-B's independently pre-frozen supplemental gate:

### Conflict families
- ordinary conflict resolution: **30 / 30 PASS**
- two independent conflicts: **10 / 20 PASS**
- conflict + lexically overlapping unrelated fact: **0 / 20 PASS**

The 10 two-conflict failures are the value-first clarification form:
`To clarify, tea is my drink preference.`

They fail with `binding_mode=none`: lexical relevance alone does not recover the
correct drink conflict component because the wording does not share enough tokens
with the original claim.

All 20 conflict+unrelated cases fail with two components / ambiguous because a
shared value token such as `Harbor` makes both:
- home-city conflict component, and
- unrelated gym-membership state
lexically relevant.

This is the exact boundary independently demonstrated by the Auditor reference:
resolution requires a durable caller-owned state-object identity, not a stronger
text regex or lexical threshold.

### Fan-out
Supplemental fan-out:
- 25: PASS
- 32: PASS
- 48: PASS
- 64: PASS
- 96: PASS
- 128: PASS
- 192: PASS
- **256: FAIL**
- 512: PASS by explicit incomplete/fail-closed

At exactly 256 returned rows, `DISCOVERY_STEPS=(24,48,96,192,256)` cannot
distinguish an exactly-complete 256-row result from truncation, therefore
`candidate_pool_complete=false` and the correct target is not authorized.

Minimal discovery correction: add a higher probe step (e.g. 512) so a 256-row
pool can be proven complete; a saturated 512 pool may remain explicit incomplete
and fail closed under the already-frozen supplemental rule.

## Required next delta

Do not generalize lexical grouping or add more text heuristics.

The next candidate must add a **durable caller-owned object/state identity**
(or equivalently strong registered state-object key) that:
- is bound before destructive authorization;
- can identify the intended conflict component across paraphrase / value-first
  clarification;
- isolates lexically overlapping but object-distinct state;
- remains model-nonowned;
- keeps user_conflict resolution-only;
- preserves explicit equivalence registry semantics.

Lead feasibility controls already prove this direction is satisfiable:
- frozen OOD 120/120;
- durable-object supplemental conflict 70/70;
- fan-out 9/9 through 512 under the frozen acceptance semantics;
- 0 provider calls.

This finding is a pre-execution correctness gate only and does not authorize a
new HaluMem paid canary, HaluMem QA, confirmatory access, or E2 acceptance.
