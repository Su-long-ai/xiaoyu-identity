# Duplicate research lease release — 2026-10-30

Lease: fish-300f3dfb7f1b4a5c
Agent: fish_re_a_20261026_t04_9b72
Family: product.memory.authoritative_physical_delete_concurrent

Decision: RELEASE_AS_DUPLICATE_PRIOR_FINAL_CANDIDATE

Reason:
The active hypothesis is already satisfied by released lease fish-3c07eabbd8c64d96.
That prior final candidate already contains BEGIN IMMEDIATE before the standalone
existence read and already reports:
- cold-start deletion boundary: 16/16
- legacy-v2 deletion boundary: 16/16
- rollback/retry/idempotence: 16/16
- online bridge delete/restart: 16/16
- missing-source fail-closed: 16/16
- export/import no model-visible resurrection: 16/16
- two concurrent writers: 32/32
- four concurrent writers: 16/16
- caller-owned transaction rollback: 16/16
- current product regression under candidate import precedence: 38/38

The first unserialized candidate's 0/32 concurrency failure was already falsified
and repaired inside that same prior lease; rerunning the same research hypothesis
would be duplicate work.

Remaining real gap:
Independent exact-byte audit of candidate SHA
8e35244993ecc225684edd1998150a75c71340698e85e2b2a5407b865f43778d
before any root product integration.

No product bytes are modified by this release decision.
