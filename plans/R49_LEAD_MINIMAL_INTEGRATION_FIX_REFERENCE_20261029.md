# R49 Lead minimal integration fix reference — 2026-10-29

Status: **E0 REFERENCE ONLY / DO NOT SUBSTITUTE FOR RE SUBMISSION**

Exact RE snapshot tested:
`r49_confirmed_transition.py`
SHA256:
`15c7ac6e8390620e720282032c29f30e866752e2f6c98138c7749194ac6bd315`

## Lead black-box finding on exact snapshot

Initial black-box: **7/8 PASS**.

Material closeout gaps:

1. `deleted` pending-source identity could be rewritten to `quarantined` when confirmation reached the R47 metadata-conflict path. It was not reactivated, but terminal erasure lifecycle was mutated.
2. No explicit durable `cancel` action/state existed.

Everything else tested on the snapshot already failed closed or recovered correctly:
- target lifecycle deletion after proposal;
- source identity drift;
- pending payload HMAC tamper;
- wrong confirmation key;
- restart persistence;
- reject terminality;
- crash after mutation / before action status with exact retry recovery.

## Minimum reference change

A Lead-only copy was modified with exactly two conceptual changes:

### A. Pre-ingest source lifecycle guard

Before destructive confirmation calls R47 ingest:

- inspect any existing row for the pending `source_message_id`;
- if it exists and `lifecycle != active`, reject with
  `confirmation_source_inadmissible_lifecycle`;
- do not call R47 ingest;
- therefore a `deleted`/tombstoned source remains byte/semantically terminal.

This does not replace the P1 erasure fence. Product integration must still preserve the existing trusted erasure/freshness boundary; this guard only closes the demonstrated R47-local lifecycle mutation path.

### B. Explicit durable cancel

Add `cancel(action_id, identity_id)` with:

- authenticated pending-row verification;
- exact identity binding;
- only `pending -> canceled`;
- `applied` cannot cancel;
- repeated cancel -> `already_canceled`;
- canceled action cannot confirm;
- canceled state/audit persists over SQLite restart.

## Lead reference result

After only those changes:

**9 / 9 PASS**

- reject terminal + nonmutation
- cancel terminal + nonmutation + restart persistence
- target lifecycle stale rejection
- source identity drift rejection
- source tombstone remains deleted
- pending row tamper rejection
- restart confirmation persistence
- wrong confirmation key rejection
- mutation-before-status crash recovery

Artifacts:
- `governance/lead_workspaces/r49_integrated_candidate_blackbox_20261029/SNAPSHOT.json`
- `.../FINDING.json`
- `.../BLACKBOX_METRICS.json`
- `.../blackbox_candidate.py`

Provider calls: **0**  
Private data: **false**  
E2 claim: **false**

## Product closeout implication

These results reduce the 12-falsifier matrix's three partial points to concrete, locally demonstrated integration behavior, but they are **not** product E1 evidence.

R49 still requires:
1. Research Engineer candidate implementing equivalent or stricter behavior on its own exact bytes;
2. exact candidate regression + 12-falsifier coverage;
3. independent Auditor ACCEPT_E1;
4. backlog closeout.

Do not copy the Lead reference blindly if the RE candidate has evolved; re-run the same black-box attacks against the exact submitted candidate.
