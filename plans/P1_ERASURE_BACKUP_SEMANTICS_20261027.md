# XiaoYu Erasure / Backup Semantics — 2026-10-27

Status: **architecture requirement clarification**

## Required semantics

1. Live current-state views must stop exposing erased evidence once an erasure is committed.
2. Managed descendants, indexes and exports must preserve durable deletion/invalidation lineage.
3. An old backup/snapshot that still physically contains erased bytes is **not authoritative current state**.
4. Before any restored snapshot is exposed to retrieval or answer generation, restore must re-apply durable erasure/invalidation information that is newer than or external to that snapshot, or reject the restore as stale.
5. Backups containing erased data that cannot be immediately overwritten must be treated as **beyond use**: they are retained only for bounded backup purposes and cannot be queried, repurposed, or restored into active state without the erasure reconciliation step.
6. Retention/overwrite policy for old copies must be explicit and testable.

## Non-claim

XiaoYu does **not** currently claim secure physical erasure of every historical disk block, filesystem copy, external backup, or previously exported artifact. A single-SQLite portable snapshot simplifies authority and restore semantics but does not magically erase bytes from old copies.

## Prospective tests

- restore a pre-erasure snapshot after a durable erasure marker exists: erased memory must remain inactive;
- restore an old export without the required erasure lineage: fail closed;
- unrelated evidence survives reconciliation;
- post-erasure user reaffirmation creates a new source lineage and may become active without resurrecting the old source;
- expired backup copies follow retention/overwrite policy and are never used for normal retrieval.

This separates **logical erasure / beyond-use / replay prevention** from unsupported claims of immediate physical secure erase.
## Trust-layer re-saturation addendum — behavioral deletion closure

The external gap-closure pass found that record absence is not sufficient evidence of effective forgetting.

Before any E2 erasure claim, add an AfterDelete-style behavioral control:

1. construct matched cases for NEVER_EXPOSED and EXPOSED_THEN_DELETED;
2. delete/invalidate the authoritative source;
3. reconcile all managed descendants, summaries, indexes, derived states and restore paths;
4. probe both direct recall and reconstruction from fragments/derivatives;
5. require deleted information to remain unavailable without damaging unrelated evidence;
6. distinguish privacy erasure from capacity eviction and ordinary retrieval miss.

A pre-erasure backup remains non-authoritative and must reconcile newer erasure lineage before any model-visible retrieval. This addendum does not expand the claim to immediate physical erasure of every historical copy.

Reference: plans/P1_TRUST_LAYER_EXTERNAL_GAP_CLOSURE_20261027.md


## Continuous erasure-fence freshness — Lead E0 addendum

A one-time restore-before-activation reconciliation is insufficient when the trusted external erasure fence can advance after activation. Lead deterministic E0 reproduced the race in 200/200 cases: after successful reconciliation, a second tombstone committed to the external fence remained visible through the restored store's old active gate 200/200.

P1 therefore requires a continuing exposure invariant: before retrieval/model-visible memory is authorized, the store's `reconciled_fence_revision` must equal the current trusted fence revision (or carry an equivalent monotonic freshness proof). Revision mismatch fails closed until reconciliation succeeds.

With this gate, the same 200/200 cases blocked before exposure, then re-reconciliation removed the newly erased source while preserving the prior erasure. Evidence: `governance/lead_workspaces/p1_erasure_fence_freshness_20261027/erasure_fence_freshness_metrics.json`.

This remains logical erasure/replay prevention. It does not strengthen the claim to physical secure erasure of historical media.


## Provenance / model-visible context separation — R44/R45 update (2026-10-28)

A partial erasure can fail even when the deleted database/source row is gone.

Two concrete P1 falsifiers are now frozen:

1. **Wide evidence quote:** a validator-accepted quote spanning multiple sibling facts was copied verbatim into surviving canonical event text. R44 removed the deleted source row but still exposed deleted sibling plaintext through surviving records.
2. **Raw multi-fact SOURCE/history:** a raw message can remain needed because one sibling event survives, while the same raw string still contains an erased sibling.

Accordingly, erasure closure now distinguishes:
- immutable/sealed provenance;
- model-visible canonical/current/history representations.

Raw evidence quote/source plaintext may remain in provenance according to retention policy, but after partial erasure it is not automatically admissible as model context. Model-visible memory must use an independently safe event-local or redacted representation. Opaque quote/source hashes may preserve provenance binding but are not claimed as secrecy mechanisms.

R45 is the required P1 gate for this boundary. R43's ACCEPT_E1 touched-scope replacement remains valid within its accepted scope and does not imply raw-source history safety.
