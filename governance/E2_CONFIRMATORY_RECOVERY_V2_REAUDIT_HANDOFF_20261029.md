# E2 Confirmatory Recovery V2 Independent Re-audit Handoff — 2026-10-29

Status: **READY FOR INDEPENDENT EXACT-BYTE RE-AUDIT / EXECUTION STILL FORBIDDEN**

This package exists because the first authorized confirmatory execution exposed two infrastructure failures:
1. HaluMem: 68 COMMITTED semantic calls + 1 durable UNKNOWN (`IncompleteRead`) plus session/checkpoint resume drift.
2. LongMemEval: full holdout deserialized before prediction seal, invalidating the current LME gold boundary.

This handoff authorizes **audit only**. It does not authorize provider calls, judge calls, calibration, gold reads, prediction sealing, recovery execution, or E2 promotion.

## Exact package identity

- Recovery manifest: `governance/E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json`
  - SHA256: `4cfa98d3a9fb3f68d19e370e2efb95db9821542425ebbf6da29fea90a1034507`
- Audit snapshot index: `governance/recovery_v2_audit_snapshot/4cfa98d3a9fb3f68/AUDIT_SNAPSHOT_INDEX.json`
  - SHA256: `b4ad314e17a45a135b4ea45596d1b2d634fa1b104489bbcdfea5c6d0167981c3`
  - files: 15
- HaluMem recovery runner SHA256: `d4515d558d2f3878bd52aefaa6ae2c6b51a6ad31f9d6679ac50db7b68588dc61`
- Shared UNKNOWN reconciliation SHA256: `efe30172dbfe9d2b895e9190fb969b096a36e0603513d95486eba7e7f58a15e4`
- Legacy 68-COMMITTED receipt index SHA256: `39adc5e2d3273a1fd0bfa6b20b46dc577b9f20eb039ed3674331ea9d2c5048f1`
- HaluMem qwen3.8-flash judge wrapper SHA256: `2e02bfa4f7014d06e68ef86ae797be4d89a49f7d15159aa574943b21264a4576`
- LME recovery runner SHA256: `3964d6344b852ae76f260e2aa4e383d171be4e091baa9a8614c13641441ea882`
- LME scoring wrapper SHA256: `68323f5a70e404ff5b332504c0c908e4d1f2f2bd8de34b76144988c46a6cb005`
- Offline test SHA256: `d5acff248a1b6708a548737b2ea622abdf5b41b7fb4f19744537c23caaa6702e`
- Recovery doctor SHA256: `a764f9bc3d77e678b7ff903e022e14cd68e6904605ad9d3a3e3712c1070ec0dd`

## Frozen live recovery facts

HaluMem durable ledger:
- COMMITTED: 68
- UNKNOWN: 1
- RESERVED: 0
- UNKNOWN case: `hm-c-m-8e00ab0ec2dd-s4-t24`
- UNKNOWN call: `api-9c5dcdb177334b69b1229d5880fe1a4f`
- error class: `IncompleteRead`
- response_text: null
- response_sha256: null
- provider retry: forbidden

All 68 legacy COMMITTED calls have exact old local receipts. The receipt index binds, for every case: case_id, call_id, old receipt path + SHA256, original `request_messages_sha256`, and durable `response_sha256`.

LongMemEval:
- confirmatory provider calls: 0
- current holdout status: `INVALIDATED_GOLD_BOUNDARY`
- recovery-v2 manifest deliberately sets `recovery_execution_candidate=false`
- no silent holdout substitution and no automatic reactivation are allowed.

## Required audit checks

Formal READY requires all of the following to be independently true:

1. `exact_manifest_and_bound_files` — recompute exact source/snapshot hashes and confirm no package drift.
2. `legacy_68_request_response_bindings_exact` — 68/68 old COMMITTED receipts bind exact case/call/request/response hashes.
3. `legacy_unknown_no_retry_no_semantic_state` — the single durable UNKNOWN remains UNKNOWN, is never retried/mutated, becomes only `TRANSPORT_ABSTAIN_NO_RETRY`, and creates no semantic claim/current user_state.
4. `checkpoint_crash_recovery_fail_closed` — each completed HaluMem session has an immutable SQLite checkpoint; progress advances only after checkpoint materialization; restart restores only the checkpoint referenced by progress; an unreferenced ahead-of-progress work DB/checkpoint cannot alter resumed request construction.
5. `new_call_request_intent_pre_dispatch` — a new never-attempted case writes immutable `request_messages_sha256` intent before provider dispatch; later COMMITTED-without-local-response-receipt reuse requires that exact intent.
6. `old_runtime_immutable` — old partial runtime/receipts/ledger are not rewritten to simulate success.
7. `halumem_only_track_authorized` — recovery final freeze, if later built, can authorize HaluMem only.
8. `longmemeval_remains_disabled` — LME same holdout remains invalidated and cannot execute under this recovery manifest.
9. `judge_calibration_post_seal_12_of_12` — fresh qwen3.8-flash 12/12 calibration remains required after prediction seal and before gold scoring; old judge receipts are not reusable.
10. `provider_calls_during_audit_zero`
11. `judge_calls_during_audit_zero`
12. `gold_reads_during_audit_zero`

## Lead-side evidence already run

`py -3.11 -m unittest -v governance.test_confirmatory_recovery_v2_offline`

Current result: **9/9 PASS**.

`py -3.11 governance/confirmatory_recovery_candidate/HALUMEM_CONFIRMATORY_RUNNER_V2.py preflight`

Current result: ok=true; dataset records read=0; provider calls=0; judge calls=0; execution_authorized=false; reason=recovery-v2 final freeze missing.

LME status: execution_authorized=false; reason=recovery track is not eligible for execution.

Recovery doctor: errors=[]; recovery_candidate_healthy=true; HaluMem recovery execution=false; LongMemEval execution=false; E2 claim=false.

These Lead results are not an independent acceptance claim.

## Required formal result format

The independent Auditor result must include:
- `classification: "READY_FOR_RECOVERY_V2_FREEZE"`
- `decision: "READY_FOR_RECOVERY_V2_FREEZE"`
- `manifest_sha256: "4cfa98d3a9fb3f68d19e370e2efb95db9821542425ebbf6da29fea90a1034507"`
- `findings: []` for formal READY
- `checks` containing every required boolean above as `true`

Any material P0/P1/P2 or any missing required check means NOT READY.

Required audit family: `audit.e2.confirmatory.recovery_v2_final`
Required Auditor identity: `xy-auditor-independent-20261026-01`

## After a valid READY only

Run: `py -3.11 governance/build_e2_confirmatory_recovery_v2_final_freeze.py`

That builder is already fail-closed and was verified to refuse execution before an exact submitted independent READY. It will authorize only `halumem`; it will keep LongMemEval disabled and `e2_claim_allowed=false`.

Do not edit the manifest or recovery candidate files after the audit begins. Any byte change requires rebuilding the manifest/snapshot and a fresh exact-byte re-audit.
