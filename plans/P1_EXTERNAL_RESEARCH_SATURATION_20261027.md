# XiaoYu External Research Saturation Review — 2026-10-27

Status: **SATURATED FOR CURRENT P1 DECISIONS**

## Scope

Multi-round external survey covered:
- software catalog / component lifecycle / ownership;
- Policy-as-Code and decision logging;
- experiment tracking / prior-work search / reproducibility;
- dependency security, licensing and maintenance health;
- AI memory frameworks and agent persistence;
- long-memory benchmark coverage;
- benchmark scoring-target sensitivity;
- provenance / event identity boundaries;
- erasure / backups / replay semantics;
- procedural/stateful-agent evaluation;
- failure modes of the anti-reinvention mechanism itself.

The survey stopped when additional searches mostly repeated the same patterns (lifecycle, searchable decisions/runs, health metadata and revision tracking). The last materially new finding was benchmark scoring-target sensitivity for raw/source-linked/canonical memory representations.

## External findings that changed XiaoYu

### 1. A static allowlist is too weak

Mature software catalogs treat lifecycle and ownership as first-class metadata. Reuse approval must therefore be versioned and revisitable, not permanent by component name.

Implemented:
- REUSE_CATALOG v2;
- lifecycle adopt/trial/reference/hold/deprecated;
- owner/source/version/license/health/verified_at/review_after/decision_ref;
- hold/deprecated blocked for new normal work;
- reuse-doctor revision/staleness checks.

### 2. "Reuse first" can itself create supply-chain risk

Open-source health/security practices require maintenance, vulnerability, license, dependency and release provenance review. A generic backend alias can hide material version changes.

Implemented:
- centralized COMPONENT_ADMISSION.md;
- concrete FastEmbed 0.8.0 + BGE-small-en-v1.5 and LanceDB 0.39.0 trial entries;
- generic fastembed/vector aliases deprecated;
- Hindsight pgvector kept reference-only until actual server extension version is verified;
- security/maintenance review happens at Lead admission/review, never on each lease.

### 3. Infrastructure de-duplication is not enough; experiments also duplicate

Experiment tracking systems make runs, parameters, code/data versions, metrics and artifacts searchable. XiaoYu previously stopped duplicate infrastructure but could still repeat an old hypothesis under a new family name.

Implemented:
- control.py prior-work;
- self-directed V2 plan must list reviewed historical leases and >=50-char novelty;
- same family or lineage always requires historical review;
- exact already-submitted hypothesis is blocked unless intentional falsification/replication;
- no MLflow/DVC service added.

### 4. Decisions need durable context and supersession history

Architecture-decision practices preserve context, alternatives, consequences and revisit conditions instead of silently replacing the old answer.

Implemented:
- seven ADRs under governance/decisions;
- every major catalog choice references an ADR;
- old active lease decisions remain bound to the catalog revision they started with;
- reuse-doctor reports catalog drift; only new leases re-evaluate against V2.

### 5. One long-memory benchmark cannot cover identity continuity

The external benchmark landscape separates operation-level hallucination, explicit long-horizon recall, implicit/composed conversational use, latent user goals/values and procedural stateful outcomes.

Implemented:
- capability-oriented benchmark matrix;
- LongMemEval/OmniMemEval + HaluMem retained now;
- LOCOMO-CONV and LoCoMo-Plus reserved as targeted future E2 candidates after P1 freeze;
- STATE-Bench held until real state-mutating/tool workflow scope exists;
- broad memory-framework collection remains frozen.

### 6. Memory benchmark conclusions can change only because the scoring target changes

Raw turns, derived/source-linked memories and canonical current state are not interchangeable gold targets.

Implemented:
- P1_BENCHMARK_SCORING_POLICY_20261027.md;
- future matched retrieval must predeclare RAW / SOURCE / CANONICAL_CURRENT / TASK_DEFINED;
- save ranked outputs with source/authority/temporal linkage and rescore offline;
- if the winner changes across reasonable targets, report sensitivity instead of choosing the favorable target.

### 7. Erasure and backup semantics needed a precision fix

A system can make data logically erased and beyond normal use even when old backup media has not yet been physically overwritten. Restore is the dangerous boundary.

Implemented:
- P1_ERASURE_BACKUP_SEMANTICS_20261027.md;
- old snapshots are not current authority;
- restore must reconcile newer erasure/invalidation lineage before active retrieval or fail closed;
- no claim of immediate physical secure erase of every historical copy/export.

### 8. XiaoYu-specific provenance boundary remains justified custom work

Generic event/provenance standards and external frameworks cover source IDs, lineage, revision/invalidation and temporal metadata, but do not establish XiaoYu's fail-closed same-source semantic conflict quarantine and user-vs-assistant authority contract.

Decision:
- keep XiaoYu source identity / authority / quarantine / correction-deletion policy thin and custom;
- continue reusing generic storage/lineage/temporal mechanics;
- do not build a general provenance/event platform.

## Explicitly rejected overengineering

The survey did **not** justify adding:
- Backstage;
- OPA or Cedar;
- MLflow or DVC services;
- a new graph/vector/ANN database;
- another generic memory framework;
- another benchmark harness;
- network security scans on every lease.

Their useful design patterns were absorbed into the existing stdlib + SQLite control plane.

## Validation

Latest full governance regression: **77/77 PASS**.

Latest reuse-doctor:
- catalog version: 2;
- components: 24;
- error_count: 0;
- warning_count: 2;
- healthy: true;
- enforcement_clean: true;
- active_unguarded: 0;
- pending_unguarded_e1: 0.

The two warnings are expected catalog-revision drift for already-running V1 Research A/B leases. They contain no blocked component and remain frozen to their original scientific decision. Their next lease will use V2.

Backlog replay against current V2 catalog: **13/13 PASS**.

Real negative/positive dry-runs:
- same-lineage new self-directed hypothesis with no prior review: expected FAIL;
- after reviewing the two closest material prior leases and stating novelty: PASS;
- deprecated generic vector backend alias: expected FAIL.

## Saturation conclusion

For the current P1 architecture, further broad external searching is unlikely to change the main build-vs-reuse boundary. New research should now be event-driven: reopen external surveying only when a concrete capability gap, component upgrade/security advisory, benchmark scope change, or prospective falsification appears.

The highest-value remaining work is not more catalog/framework collection; it is integrating the accepted XiaoYu-specific semantics into the frozen P1 pipeline and validating that pipeline on the capability-oriented benchmark matrix.
## Scope correction and re-saturation addendum — 2026-10-27

The original SATURATED FOR CURRENT P1 DECISIONS conclusion remains valid for the broad memory-framework / component-selection question, but it was too broad if read as research-frontier saturation.

A later exact local coverage audit found that the earlier survey did not include several 2026 trust-layer lines such as Agent Zero Memory, MemIR, provenance laundering / origin-bound authority, AfterDeleteBench, persistent-memory poisoning, retrieval admissibility, MemDerive, portable-memory interoperability and storage rollback/tamper work.

A five-round targeted gap-closure survey has now been completed and is frozen in:

- plans/P1_TRUST_LAYER_EXTERNAL_GAP_CLOSURE_20261027.md
- governance/decisions/ADR-009-trust-layer-gap-closure-and-resaturation.md
- plans/P1_BENCHMARK_CAPABILITY_MATRIX_20261027.md

New top-level capability gaps found and added to planning:
- write-time authority non-amplification;
- persistent-memory poisoning;
- principal/scope/admissibility before model-visible context;
- behavioral deletion closure;
- derived-state dependency propagation;
- intrinsic memory-state evaluation separate from final QA;
- storage tamper/replay/rollback integrity;
- cross-model memory portability references;
- relationship-specific memory;
- future multi-party, procedural and multimodal scope markers.

The final search round mostly returned additional work within those same classes rather than a new architecture dimension. Broad external searching is therefore closed again for current P1/P2 decisions and becomes event-driven.

This addendum supersedes any interpretation that the first survey had exhausted the 2026 trust-layer literature.
