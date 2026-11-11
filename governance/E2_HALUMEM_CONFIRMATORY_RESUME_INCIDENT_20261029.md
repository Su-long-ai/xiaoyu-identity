# E2 HaluMem Confirmatory Resume/UNKNOWN Incident — 2026-10-29

Status: **FAIL-CLOSED / HALUMEM CONFIRMATORY COMPLETION BLOCKED**

## Evidence

Final execution freeze:
- authorized at 2026-10-29T12:59:19.228338+00:00
- HaluMem semantic scope: `proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1`

A prior post-freeze prediction attempt existed before the current continuation.

Durable research ledger:
- total HaluMem confirmatory semantic cases: 69
- COMMITTED: 68
- UNKNOWN: 1
- all 69 were created after final freeze

The only local prediction progress file:
- `m-8e00ab0ec2dd.json`
- completed_sessions: 4
- total_sessions: 65
- complete: false
- gold_fields_materialized: 0

The durable ledger nevertheless contains committed calls for session 4 through turn 22, followed by:
- `hm-c-m-8e00ab0ec2dd-s4-t24`
- status: `UNKNOWN`

On resume, the frozen runner stopped at:
- `hm-c-m-8e00ab0ec2dd-s4-t4`
- error: `local semantic receipt binding drift: request_messages_sha256`

The t4 local receipt and durable ledger agree on call_id, response SHA, scope and COMMITTED status, but the request hash recomputed from the resumed state differs from the original request hash.

## Interpretation

The evidence is consistent with a checkpoint/state atomicity gap:

1. the earlier run durably mutated the per-user SQLite state during session 4 and committed paid semantic calls;
2. the per-user prediction progress checkpoint was only persisted through completed session 3;
3. the run stopped during session 4 after an UNKNOWN provider outcome at t24;
4. a later resume opens the already-advanced SQLite state but restarts session 4 from its beginning;
5. the changed prior-state/candidate pool makes some previously COMMITTED request payloads non-identical, triggering the frozen request-hash guard.

This is exactly what the request binding guard is intended to detect. The local receipt must not be deleted/replaced to force a retry.

## Frozen-rule consequence

The final confirmatory manifest/runners require:
- duplicate paid work forbidden;
- RESERVED/UNKNOWN blocks retry;
- RESERVED/UNKNOWN blocks prediction seal;
- committed receipt request binding must be exact;
- serial state order per user/variant.

Therefore:
- do not retry the UNKNOWN t24 case;
- do not delete/rewrite COMMITTED semantic receipts;
- do not roll back/rebuild state and reissue already-paid case IDs;
- do not seal the current HaluMem prediction set;
- do not proceed to judge calibration or gold scoring.

## Gold boundary

No HaluMem confirmatory gold was opened by the current continuation.
The frozen Halu selective structural parser still reports zero gold fields materialized.
The failure is a prediction/resume integrity failure, not Halu gold contamination.

## Required disposition

HaluMem confirmatory track is scientifically incomplete under the current immutable execution protocol. Any future rerun would require a newly frozen execution generation/case namespace and an explicit governance decision; it cannot be silently treated as continuation of the current confirmatory run.
