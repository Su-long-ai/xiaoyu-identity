# R49 NEEDS_WORK remediation handoff — 2026-10-29

Target submission: `sub-215bdcf6765845f1`  
Receipt-bound candidate SHA256:  
`15c7ac6e8390620e720282032c29f30e866752e2f6c98138c7749194ac6bd315`

Formal E1 decision: **NEEDS_WORK**.

This handoff combines the formal independent review with two additional Lead exact-byte black-box findings. The next R49 candidate should fix all three together; fixing only the formal TOCTOU finding is insufficient for R49 closeout.

## Blocking repairs

### 1. P1 — freshness check → R47 ingest TOCTOU

Formal independent review: `review-667f107afce44422`.

Exact receipt-bound candidate reproduced:
- pre-confirm competing write: stale rejected 8/8;
- same competing NEW inserted after `current_generation()` but before R47 `ingest()`: confirmation applied 8/8;
- both competing and confirmed current claims active: 8/8.

Required:
- expected trusted generation/component freshness check and authoritative R47 transition admission share one SQLite write-serialized transaction or equivalent CAS;
- target-active validation remains necessary;
- rerun exact auditor interleaving plus restart/crash/replay.

Formal evidence:
`governance/workspaces/fish-ebf4918625a24f13/confirmation_ingest_toctou_metrics.json`

### 2. P1 closeout — terminal source lifecycle preservation

Lead exact-byte black-box showed:
- a pending source identity already marked `deleted` reaches R47 `source_metadata_conflict`;
- it is not reactivated, but terminal lifecycle changes `deleted -> quarantined`.

Required:
- inside the same serialized confirmation boundary, inspect any pre-existing pending `source_message_id`;
- if lifecycle != `active`, reject before R47 ingest;
- preserve deleted/tombstoned lifecycle unchanged.

Evidence:
`governance/lead_workspaces/r49_integrated_candidate_blackbox_20261029/FINDING.json`

### 3. P1 closeout — explicit durable cancel

Receipt-bound candidate has durable `reject` but no explicit `cancel`.

Required:
- authenticated `pending -> canceled`;
- non-mutating;
- persistent across restart;
- repeated cancel idempotent;
- canceled action never confirmable without a new proposal;
- audit event persisted.

Evidence:
same Lead black-box finding above.

## Already validated minimal repair direction

Lead-only reference, **not product evidence**:

`governance/lead_workspaces/r49_integrated_candidate_blackbox_20261029/LEAD_REMEDIATION_REFERENCE_METRICS.json`

Reference result:
- existing 80-case candidate regression preserved;
- replay 32/32;
- restart 16/16;
- stale 8/8;
- cross-identity 8/8;
- crash-before 8/8;
- crash-after 8/8;
- multi-target 24/24;
- tamper 6/6;
- lifecycle/cancel/restart black-box 9/9;
- atomic serialization probe 8/8: competing writer blocked inside freshness→ingest boundary, 0/8 inserted inside, 8/8 succeeded after transition commit.

Reference SHA:
`9719a5ec790600b0cbdbefe89b046ffcf6d9bfad6eb1026c2a253c3c8e56dc16`

The reference uses `BEGIN IMMEDIATE` across locked freshness recheck + R47 ingest admission, a pre-ingest source-lifecycle guard, and durable cancel. It demonstrates feasibility only; the Research Engineer must implement and test its own exact candidate bytes.

## Preserve

Do not reopen/rewrite:
- accepted R47 store architecture;
- R49 structural v5 caller-owned component membership;
- pending nonmutation;
- HMAC payload/binding/source integrity;
- replay/restart/crash recovery;
- multi-target full-component closure.

No provider calls are required for this remediation. Confirmatory users remain untouched. E2 claim remains false.
