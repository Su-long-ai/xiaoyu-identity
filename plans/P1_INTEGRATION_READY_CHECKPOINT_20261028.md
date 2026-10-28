# XiaoYu P1 Integration-Ready Checkpoint — 2026-10-28

Status: **P1 INTEGRATION READY / E2 NOT UNLOCKED**

This checkpoint freezes the first complete P1 text-identity integration contract after independent R45 acceptance and Lead cross-stage closeout.

## Hard result

`governance/p1_integration_doctor.py --require-ready`:
- required stages: **12**
- ready required stages: **12**
- blocked required stages: **0**
- direct blockers: **0**
- dependency-only blockers: **0**
- contract errors: **0**
- warnings: **0**
- closeout sync: PASS
- `contract_healthy=true`
- `integration_ready=true`
- **`e2_claim_allowed=false`**

Full governance regression after finalization/lifecycle-fixture repair:
- **122 / 122 PASS**

Core control files also pass `py_compile`.

Research Engineer continuation after P1 closeout returns:
- `continue_research=false`
- `next_step=P1_RESEARCH_CLOSEOUT_COMPLETE`

Therefore P1 completion does not silently auto-open P2 or self-directed research.

## Frozen file hashes

At the P1 freeze boundary:

- `governance/P1_INTEGRATION_CONTRACT.json`
  - SHA256 `b8dcb1659f40886e984a3531dcaf11f4858d38252935d70bb3ca3332dc9e4668`
- `governance/P1_INTEGRATION_CANDIDATE.json`
  - SHA256 `2a20aa552c4bc50356f6bffeaa08cb58b8f40d1c9302586aea8b43c4bc78fe83`
- `governance/RESEARCH_BACKLOG.json`
  - SHA256 `1d0938a7c2e01f8669e601796c65bdfce9ca2e7025124b0e2216d69c4da69c52`
- `governance/policy.json`
  - SHA256 `8db794b89d4968c98e8e49f5b16f8e5c965018234be4c6a020f4d125035d6191`

The backlog/policy may intentionally change when Lead opens P2; the contract/candidate above are the P1 integration baseline to regression-test against.

## Final P1 erasure boundary

R44 `sub-a22bcd5d53de47fb` was NEEDS_WORK after an independent auditor showed validator-accepted wide evidence quotes resurrected deleted sibling plaintext through surviving canonical projections in **80/80** attacks.

Successor R45:
- Research submission: `sub-a650809e040046aa`
- Decision: **ACCEPT_E1**
- Independent reviewer: `xy-auditor-independent-20261026-01`
- Review: `review-666472161432409f`
- P0/P1 material findings: **0**
- P2 advisories: **2**
- receipt integrity: PASS

Fresh Research evidence:
- 96 frozen cases
- R44 full-wide leak: 96/96
- R44 adjacent leak: 96/96
- R45 narrow/wide/adjacent leak: **0/96**
- semantic/hash/restart/stale-rekey/reaffirmation checks: 96/96
- 11 binding mutation families: 96/96 fail closed

Independent blind audit:
- 64 cases frozen before candidate reveal
- five validator-valid quote geometries
- R44 full/adjacent/tail-evasion leak: 64/64
- R45: **0/64**
- all semantic/hash/restart/freshness/binding checks: 64/64
- surviving CLEAR was separately checked on the Research 96-case set: 77/77 surviving CLEAR cases pass across narrow/wide/adjacent variants.

## Cross-stage Lead integration gate

R45 component acceptance alone is not enough.

P1 also requires:
`governance/lead_workspaces/p1_r45_event_local_history_bridge_20261028/r45_event_local_history_bridge_metrics.json`

Schema:
`xiaoyu-r45-partial-erasure-event-local-history-bridge-e0-v1`

Result: PASS.

The frozen composition rule is:

- untouched source history may retain the existing raw representation;
- a source touched by event-level erasure/invalidation becomes raw-provenance-only;
- surviving model-visible history is event-local;
- surviving SET, CLEAR and assistant-history semantics remain retrievable;
- deleted sibling plaintext is absent;
- trusted erasure lineage selects this mode;
- unknown lineage source fails closed.

This closes both:
1. raw `evidence_quote` replay through canonical projections;
2. raw multi-fact SOURCE/history replay after partial sibling erasure.

## R45 nonblocking P2 advisories

1. **Alternate validator-valid quote widths**
   - source_event_id is stable, but the current canonical projection includes `evidence_quote_sha256`;
   - semantically identical retries with another valid quote width fail closed as `source_id_conflict` instead of converging idempotently;
   - no stale overwrite/privacy leak observed;
   - P2 liveness/compatibility question.

2. **Deterministic plaintext digests**
   - model-visible canonical rows keep deterministic SHA256 references to quote/source text;
   - raw plaintext is absent, but low-entropy text may permit equality/dictionary testing;
   - no secrecy claim is made;
   - stronger unlinkability/confidentiality belongs to P2+.

An independent Auditor has already opened a follow-up on quote-independent canonical representation. It is advisory/P2 unless new reproducible P0/P1 evidence emerges.

## P1 nonclaims

This checkpoint does **not** claim:
- E2 prospective scientific validation;
- E3/product readiness;
- secure physical erasure of every historical copy;
- secrecy of low-entropy text from deterministic hashes;
- distributed trusted-time consensus;
- completed cross-model/vendor interoperability;
- unlocked 95M benchmark phase.

## Next phase

P2 may now be opened explicitly by Lead. Initial frozen candidates:
- R24 behavioral deletion closure;
- R25 whole-store rollback/replay/control-state integrity;
- R23 derived-state dependency/rule propagation.

R26 portable-memory interoperability remains P3 HOLD.

P2 work must preserve the P1 contract as a regression baseline rather than silently rewriting it.
