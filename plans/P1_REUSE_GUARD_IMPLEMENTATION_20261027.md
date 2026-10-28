# P1 Build-vs-Reuse Guard Implementation Checkpoint — 2026-10-27

## Result

**IMPLEMENTED AND LIVE.**

The earlier de-duplication finding is now enforced in the research control plane rather than depending on prompts or Lead memory.

## Enforcement chain

1. `REUSE_CATALOG.json` is the machine-readable registry of retained standard/external mechanisms.
2. Every new post-epoch `research_engineer` lease passes `Governance.reuse_check()`.
3. Self-directed work must provide a reuse plan; static backlog tasks use Lead-vetted plans and callers cannot replace them.
4. Component IDs must already exist in the catalog.
5. `new_dependencies` must be empty; new frameworks/dependencies require a Lead catalog update before claim.
6. Capability-specific baselines require each research class to anchor to at least one retained mechanism.
7. Known duplicate-wheel rules fail closed even after family renaming when the hypothesis still requests the prohibited infrastructure.
8. The lease receives an immutable `REUSE_DECISION.json`; its SHA256 is stored in registry.sqlite3.
9. Guarded submission requires exact `reuse_compliance`: same components, no new dependencies, no new infrastructure, no undeclared deviation.
10. Altering/deleting the reuse decision blocks submission.
11. `next` and heartbeat refuse post-epoch unguarded active leases.
12. Post-epoch unguarded submission cannot be ACCEPT_E1.
13. `reuse-audit` continuously exposes active/pending deployment gaps.
14. `reuse-retrofit` exists only for an ACTIVE deployment-gap lease and requires a valid current plan plus reason.
15. Exact recovery of a pre-guard stale lease is allowed only at identical family + lineage + capability + hypothesis; duplicate-wheel rules still apply.

## Frozen duplicate-wheel classes

- handwritten lexical posting/inverted-index infrastructure -> SQLite FTS5;
- future ZIP + duplicate JSON/SQLite identity archive patch treadmill -> single SQLite backup candidate; ZIP legacy-only;
- generic provenance platform -> reuse/reference Cognee/Graphiti mechanics; keep only XiaoYu fail-closed source/authority semantics;
- custom graph DB / vector DB / ANN -> existing backend;
- broad memory-framework collection -> frozen Mem0/Hindsight/Cognee/Graphiti + OmniMemEval reference set;
- CI supply-chain expansion -> retain only minimal accepted P1 gate/hash trust root.

## Regression / live validation

Governance suite:
- **72/72 PASS**.

Guard-specific tests cover:
- missing self-directed reuse plan;
- unknown component;
- undeclared new dependency;
- handwritten posting without FTS5;
- renamed custom vector DB;
- ZIP patch outside legacy/falsification mode;
- backlog-plan substitution;
- reuse-decision tampering;
- missing/incorrect submission compliance;
- exact pre-guard recovery;
- post-epoch unguarded heartbeat/next/submit blocking;
- ACTIVE deployment-gap retrofit;
- post-epoch unguarded E1 promotion blocking;
- auditor exemption.

Live dry-runs:
- R09 Lead-vetted FTS5 plan: PASS and matched `no_handwritten_lexical_postings`.
- renamed family `clever.renamed.route` + hypothesis `Build a custom vector database...`: rejected before claim.
- all current backlog plans against latest catalog: **13/13 PASS**.
- all currently active guarded research leases against latest catalog: **2/2 PASS**.

## Deployment-gap incident

There was one real lease created during the approximately minute-scale rollout gap after policy epoch activation but before the new `control.py` was fully deployed:
- lease: `fish-f61f5acaa4fb4453`;
- submission: `sub-cdfaf336a8574b46`;
- level: `EVIDENCE_ONLY`;
- state: submitted, not active;
- not pending E1;
- workspace inspected: reused governed DeepSeek classification + deterministic authority join; no new vector/graph/index infrastructure.

It was intentionally **not** retroactively modified after submission. Current `reuse-audit` retains it as historical unguarded E0 evidence while reporting:
- active_unguarded: 0;
- pending_unguarded_e1: 0;
- enforcement_clean: true.

## Scientific/operational boundary

The guard is designed to prevent accidental architecture duplication without slowing normal experiments. It is stdlib/SQLite/local-file work only and performs no model/API call.

It is not an OS sandbox. A malicious or noncompliant process with broad local tools could still write arbitrary code outside this control plane. Such work cannot obtain a normal guarded lease/submission/E1 promotion through the control path, but operating-system tool permissions remain a separate security layer.
