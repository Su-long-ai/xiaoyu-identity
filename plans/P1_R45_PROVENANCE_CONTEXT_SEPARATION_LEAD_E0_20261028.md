# P1 R45 Provenance / Context Separation — Lead E0

Date: 2026-10-28
Status: **Lead E0 only; R45 fresh Research submission is under independent audit**

## Trigger

R44 `sub-a22bcd5d53de47fb` was independently NEEDS_WORK.

The independent auditor preserved source identity, op, slot and value but widened each validated `evidence_quote` to the entire multi-sibling source message. The existing strict validator legitimately accepted those quotes because they were grounded in the source. R44 then serialized the accepted quote verbatim into model-visible `CANONICAL_EVENT` text.

After deleting one sibling:
- deleted source row absent: 80/80;
- deleted sibling plaintext still visible through surviving sibling projections: **80/80**.

Therefore source-row deletion and scope fencing were not sufficient. The failure was a representation-boundary leak.

## Lead E0 repair

Lead sandbox:
`governance/lead_workspaces/p1_r45_quote_separated_materialization_20261028`

Candidate boundary:
- raw `evidence_quote` remains inside the sealed validated provenance event;
- model-visible canonical memory contains only:
  - source_event_id
  - op
  - slot
  - value
  - source_anchor
  - effective_at
  - payload_hash
  - evidence_quote_sha256
  - source_text_sha256
- no raw evidence_quote or full source/target text is copied into canonical memory.

Lead E0 v2:
- 80/80 original R44 operational invariants retained;
- 80/80 seal/scope/effective_at mutation rejection retained;
- narrow quote semantic/materialization checks: 80/80;
- wide quote semantic/materialization checks: 80/80;
- R44 wide deleted-sibling leak: 80/80;
- R45 wide deleted-sibling leak: **0/80**.

The first Lead E0 iteration intentionally taught an additional lesson: deleting quote plaintext entirely made the old quote-only random-marker retrieval metric fail for CLEAR siblings. That old metric was retired for R45 because arbitrary provenance-only marker text is not a required model-visible memory representation. The retained requirement is exact event-local SET/CLEAR semantics plus opaque provenance binding.

## Second Lead falsifier: raw SOURCE/history

A separate Lead E0:
`governance/lead_workspaces/p1_r45_partial_erasure_raw_history_20261028`

demonstrates another path.

If a source says:

`drink DELETED ; music KEEP`

and erasure removes only the drink event, the R39/R43-style message-level history materializer can still emit the entire raw source as `user_history` because the music sibling survives. The deleted drink plaintext therefore remains model-visible even though current-state materialization is correct.

Candidate separation:
- immutable raw source remains non-model-visible provenance;
- model-visible history is event-local or separately redacted;
- surviving semantics remain visible;
- source hash remains bound.

Lead falsifier result: PASS.

## Architecture invariant

**Provenance and context are different surfaces.**

A string may be valid evidence/provenance while still being unsafe to expose after partial erasure.

Therefore P1 requires:
1. strict validator may validate a broad source-grounded quote;
2. sealed provenance may retain that raw quote;
3. canonical/current/history model-visible memory must not automatically replay the raw quote;
4. a partially erased multi-fact raw source must not be directly model-visible merely because another sibling remains active;
5. opaque source/quote hashes or equivalent references preserve audit binding;
6. event-local op/slot/value semantics are the canonical model-visible unit for this boundary.

This does not claim physical deletion of source logs/backups.

## Fresh R45 research evidence

Research A independently froze 96 fresh five-sibling cases before scoring:
- prior target overlap: 0;
- R44 baseline wide leak: 96/96;
- R44 adjacent-span leak: 96/96;
- R45 wide leak: 0/96;
- R45 adjacent leak: 0/96;
- narrow leak: 0/96;
- all narrow/wide/adjacent semantic, hash, restart, stale-rekey and reaffirmation checks: 96/96;
- all sealed-field mutation families: 96/96.

Submission: `sub-a650809e040046aa` (LEAD_READY / PENDING at time of this memo).

These fresh results are **not Lead evidence**; they belong to the Research A submission and require independent Auditor review.

## Nonclaims

- no secure physical erase claim;
- no claim that SHA256 hides low-entropy plaintext from offline guessing;
- no distributed trusted-time consensus;
- no natural-language time-extraction claim;
- no direct safety claim for arbitrary raw SOURCE/history exposure;
- no E2/production claim.
