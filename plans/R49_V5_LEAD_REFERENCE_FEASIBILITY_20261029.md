# R49 v5 Lead reference feasibility — 2026-10-29

Status: **REFERENCE FEASIBLE / NOT PRODUCTION / NO PAID AUTHORIZATION**

This reference exists only to prove that the pre-frozen v5 gate is internally
satisfiable using caller-owned state already available from R47. It does not
replace the Research Engineer implementation and is not eligible for E1.

## Frozen gate

- Gate: `governance/lead_workspaces/r49_v5_gate_20261029/R49_V5_LEAD_PREFREEZE_GATE.json`
- Gate SHA256: `5f5b5c68130be348cdb6e454ad0ee67e51976326320cd33fe2c3943ce3853347`
- Exact v4 negative control: FAIL, 40/120 OOD plus fanout/conflict/overgroup P1s.

## Reference rule

The Lead reference separates:

1. **relevance** — lexical scoring may rank admissible targets;
2. **equivalence/object membership** — only explicit caller-owned
   `equivalence_key/equivalence_size` may merge claims;
3. **conflict membership** — only the trusted R47 active conflict graph may
   expose a complete conflict component, and only on an explicit resolution path.

No lexical overlap is allowed to invent destructive component membership.

Candidate discovery evaluates the complete admissible lexical match set before
bounded exposure. This is a reference correctness implementation, not a final
performance design.

## Frozen OOD result

`r49_v5_reference_ood_metrics.json`

- total: **120/120**
- shared_anchor_distinct: 20/20
- duplicate_with_registry: 20/20
- duplicate_without_registry: 20/20
- incomplete_registry: 20/20
- single_relevant_plus_unrelated: 20/20
- two_distinct_relevant: 20/20
- provider calls: 0

## Boundary result

`r49_v5_reference_boundary_metrics.json`

- fanout >24 correct target recovered: **5/5**
- explicit conflict clarification exposes complete conflict component: **4/4**
- cross-subject lexical overgroup: **0/16**
- provider calls: 0

## What this proves

The v4 failures are not an unavoidable tradeoff between recall and safety.

It is possible to:
- recover a target beyond the old top-24 prefilter;
- preserve conservative ambiguity for multiple distinct relevant claims;
- atomically authorize explicitly registered duplicate state;
- resolve an existing R47 conflict using its complete caller-owned component;
- avoid mutating a lexically similar but object-distinct sister claim.

## What it does not prove

- no semantic model quality;
- no HaluMem QA;
- no paid canary quality;
- no production performance bound;
- no universal equivalence solver;
- no E2 acceptance.

RE-B must independently implement and freeze its own candidate against the same
gate. The independent Auditor must review the exact submitted bytes.
