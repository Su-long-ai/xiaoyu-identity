# R49 Minimal Closeout Path v2 — 2026-10-29

Status: LEAD INTEGRATION DIRECTION / NO PROVIDER CALLS

## Decision

For the current E2 R49 closeout, use one authoritative write-serialization owner:

destructive proposal -> persistent pending action -> explicit confirm -> one BEGIN IMMEDIATE -> freshness/source-lifecycle recheck -> frozen R47 target/component validation + mutation

Do not mechanically stack the auditor's store-level BEGIN IMMEDIATE wrapper underneath a confirmation layer that already owns BEGIN IMMEDIATE.

Direct composition reproduced: OperationalError: cannot start a transaction within a transaction.

## Minimal current candidate

Research pre-candidate: governance/workspaces/fish-f3685b8e45924e3e/r49_atomic_confirmed_transition.py
SHA256: 5c9856abc47ab83e57225340adb3e947b33d9f6b4b89a03b6d4fb308c96be277

It already demonstrates offline:
- frozen destructive suite 80/80;
- pending nonmutation 80/80;
- valid confirmed 32/32 and invalid rejected 48/48;
- tamper 6/6;
- competing NEW writer blocked 8/8;
- Lead atomic serialization reference 8/8;
- replay/restart/crash/multi-target regressions retained;
- provider calls 0.

It is not yet the formal exact candidate. Two known lifecycle omissions remain:
1. no durable explicit cancel();
2. no source-lifecycle inadmissibility precheck before confirmation mutation.

Both already have a Lead E0 implementation reference in governance/lead_workspaces/r49_integrated_candidate_blackbox_20261029/r49_confirmed_transition.py.

## Required minimal merge before Research submission

The exact Research candidate should:
1. retain the Research atomic confirm implementation / equivalent single write boundary;
2. add durable cancel(action_id, identity_id) with restart-stable terminal status;
3. reject confirmation if the bound source already exists with non-active lifecycle;
4. retain HMAC/action/payload/source/binding tamper checks;
5. retain exact-source crash recovery;
6. retain reject/replay/restart/stale/cross-identity/multi-target behavior;
7. expose destructive execution only through this confirmation API.

No model prompt, canary case set, paid scope, or semantic-classifier change is needed.

## Raw R47 boundary

Frozen R47 direct destructive ingestion has a reproduced validation-before-write race.
For this R49 closeout it may remain the internal substrate only if the execution/product layer proves destructive mutation cannot directly call raw R47 ingest.

The historical 16-call canary runner does call raw store.ingest(), but its scope is exhausted, all 22 observed proposals were NEW, no destructive historical mutation is implicated, and it must not be extended/reused for future destructive relations.

Any future HaluMem execution amendment with SUPERSEDE / RETRACT / CONFLICT must be hash-bound to the confirmed-transition entrypoint.

## Store-level atomicity reference

Independent Auditor results:
- direct destructive race baseline: 48/48 double-commit;
- store-atomic reference: 48/48 exactly one admitted;
- sequential equivalence 40/40;
- conflict resolution 24/24;
- same-source replay 24/24;
- multi-component 16/16;
- cross-process 8/8;
- NEW-only median latency 2.0901 ms baseline vs 2.0931 ms reference.

This is valuable defense-in-depth, but combining it with confirmation requires a single transaction-owner API. That separate integration change should not be mechanically stacked into the current R49 patch.

## Closeout condition

R49 closes only when Research submits exact candidate bytes with the minimal merge above, Lead exact-candidate gate passes, destructive product-entrypoint bypass is closed/fail-closed, and an independent Auditor reviews the exact submitted bytes and returns ACCEPT_E1. Confirmatory execution remains locked.

No E2/E3 claim follows automatically.
