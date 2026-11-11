# R49 v5 Lead semantic-guard reference — 2026-10-29

Status: **LEAD_REFERENCE_PASS / NOT_PRODUCT_PATCH / ZERO_PAID_CALLS**

## Purpose

R49 v5 already passed its broad OOD/regression/state/determinism suites, but an independent auditor found a narrow destructive-semantic grounding hole:

- neutral restatements/questions could be accepted as RETRACT/SUPERSEDE;
- explicit updates could install replacement anchors absent from the trusted source;
- the first auditor guard closed those holes but falsely rejected all 12 legitimate explicit-CONFLICT gold cases because the relation-scaffold token `may` was not literally present in source/target text.

This Lead reference freezes the exact v5/audit inputs and tests the minimum relation-aware repair without modifying the active Research Engineer workspace.

## Frozen inputs

Snapshot workspace:
`governance/lead_workspaces/r49_v5_semantic_guard_reference_20261029`

Input freeze:
`INPUT_FREEZE.json`

Exact candidate v5 SHA256:
`8d57bef1608fc4d207be42941b5c08ef57c7f203f07bb80dbe29239749b00d29`

## Reference rule

For destructive relations:

1. SUPERSEDE / CONFLICT / RETRACT require caller-derived relation intent.
2. SUPERSEDE / CONFLICT claim entity/value anchors must be grounded in the trusted source evidence quote and/or caller-owned target text.
3. CONFLICT alone permits the fixed relation-scaffold token `may`; this is not treated as a new semantic value.
4. No new target ID, authority, lifecycle, source identity, principal, or other caller-owned metadata is model-owned.
5. Low-overlap conflict clarification remains resolution-only and can select only one complete trusted R47 conflict component.

The reference deliberately does **not** broaden generic semantic inference.

## Results

- destructive semantic guard: **40 / 40 PASS**
- low-overlap conflict / ambiguity set: **32 / 32 PASS**
- original R49 semantic gold compatibility: **96 / 96 PASS**
- additional CONFLICT injection attacks: **36 / 36 PASS**
  - supported explicit conflict remains accepted;
  - source-absent city/value injection (e.g. Tokyo) is rejected;
  - source-absent numeric anchor injection (e.g. 999) is rejected.
- provider calls: **0**

Reference metrics:
`LEAD_REFERENCE_METRICS.json`

Guard SHA256:
`9f8e0d14c1790ea250653562abc446bd2d1e9dd3b45e3bfb9979aedf0e31362c`

## Closeout implication

This demonstrates that the current blocker does not require a new memory architecture, retriever, graph, vector DB, or benchmark expansion.

A product candidate should now be judged against the combined gate:

- existing v5 OOD / conflict / fanout suites remain exact;
- old regressions remain exact;
- hostile validator and R47-state tests remain exact;
- deterministic replay remains exact;
- destructive semantic guard 40/40;
- low-overlap conflict/ambiguity 32/32;
- original gold compatibility 96/96;
- CONFLICT source-absent value injection attacks 36/36.

Only an independently audited product implementation that passes the combined gate may close R49. This Lead reference itself is not ACCEPT_E1 and does not unlock E2 confirmatory execution.
