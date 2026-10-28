# P1 CI Integrity-Contract Repair — Lead E0 — 2026-10-27

## Status

**LEAD E0 REPAIR PASS — FORMAL REPLICATION QUEUED AS R10.**

Original candidate `sub-839517a177254863` remains **NEEDS_WORK**. This Lead workspace does not edit or overwrite its submitted artifacts.

Lead isolation workspace:
`governance/lead_workspaces/ci_integrity_contract_20261027`

## Independent-audit P1

The submitted runner froze:
- required gate IDs;
- canonical SHA256 of each gate definition.

But top-level `integrity_files` remained manifest-controlled. A manifest could omit `erasure_e0.py` from integrity coverage, substitute a same-name script, keep the gate definition unchanged, and still pass 4/4.

## Repair design

The runner now additionally freezes an exact `REQUIRED_INTEGRITY_SHA256` mapping:
- 13 required integrity paths;
- exact SHA256 for every path.

Before any file preflight or gate execution, `validate_integrity_contract()` requires:
- `integrity_files` is a list;
- exact required membership;
- no missing rows;
- no unknown extra rows;
- no duplicates;
- no malformed rows;
- every manifest SHA equals the runner-frozen SHA;
- row count exactly equals the required set.

Only after this contract passes does normal actual-file SHA preflight occur.

Legitimate changes therefore require an explicit runner trust-root update; the manifest cannot weaken its own coverage.

## Focused integrity-contract mutations

11/11 fail closed **before any gate executes**:

1. empty integrity list;
2. unrelated-only integrity list;
3. omit migration gate script coverage;
4. omit erasure gate script coverage;
5. omit response gate script coverage;
6. omit budget gate script coverage;
7. independent-audit shape: omit erasure row + same-name substitute;
8. substitute erasure integrity hash in manifest;
9. duplicate integrity row;
10. unknown extra integrity row;
11. substitute a non-gate dependency hash.

All produced:
- overall FAIL;
- exit 2;
- fatal `required_integrity_contract_failed`;
- 0 gate executions.

Evidence:
`ci_integrity_contract_repair_metrics.json`

## Original runner mutation regression

The original 13 isolated runner mutations were rerun with the new integrity layer disabled only inside that isolated mutation harness, so they still exercise their original code paths rather than trivially failing earlier.

Result:
- 13/13 fail closed;
- stale PASS metrics still removed;
- PASS.

Evidence:
`p1_ci_mutation_metrics.json`

## Clean frozen suite

Patched runner + unchanged frozen manifest:

- gate contract: exact;
- integrity contract: 13/13 exact;
- migration_source_identity: PASS;
- erasure_replay: PASS;
- response_safety_boundary: PASS;
- model_budget: PASS;
- overall: **PASS 4/4**;
- exit 0.

Evidence:
`lead_integrity_contract_clean_run.json`

## Real domain-regression injection

The clean manifest was kept unchanged. In a disposable copy, the actual required `erasure_e0.py` bytes were replaced with the existing real erasure regression mutant.

Observed:
- integrity contract itself: valid;
- actual SHA preflight: erasure SHA mismatch;
- overall FAIL;
- exit 2;
- fatal `integrity_preflight_failed`;
- **0 gates executed**;
- no erasure metrics file produced.

This proves a same-name domain-regression substitution is rejected before execution even when the manifest is not modified.

Evidence:
`ci_real_erasure_regression_metrics.json`

## Boundaries

This repair does not remove the P2 portability debt: several frozen integrity entries are absolute paths into another historical research workspace. The exact-set contract makes those dependencies tamper-evident but does not make them portable.

This is Lead E0, not E1. R10 must independently reproduce:
- the original P1;
- clean 4/4;
- original 13 mutants;
- exact integrity mutations;
- real domain regression;
before the CI candidate can return to independent E1 audit.
