# ADR-009 — Close trust-layer literature gaps; keep architecture thin

Status: Accepted planning decision
Date: 2026-10-27

## Context

The first external-saturation pass was strong on memory frameworks, retrieval mechanisms and general provenance, but it missed several 2026 research lines directly relevant to XiaoYu: provenance-role collapse, authority laundering, deletion closure, memory poisoning, retrieval admissibility, derived-state propagation, cross-model portability and storage-level rollback/tamper integrity.

A five-round gap-closure survey is recorded in plans/P1_TRUST_LAYER_EXTERNAL_GAP_CLOSURE_20261027.md.

## Decision

1. Keep the production direction thin: SQLite authoritative state + FTS5 + optional reused semantic backend + XiaoYu-specific source/authority/lifecycle/conflict policy.
2. Do not claim generic provenance, typed memory, portable memory, deletion closure or memory security as novel categories.
3. Add write-time origin-bound authority and query-time admissibility as explicit architecture requirements.
4. Add derived-state dependency/rule-version diagnostics and storage rollback/replay integrity to future gates.
5. Use public benchmarks/references for deletion, poisoning, admissibility, derived state, relational memory and procedural memory instead of inventing private equivalents.
6. Keep Mem0/Hindsight/Cognee/Graphiti as the frozen framework-comparator set; new papers below are mechanism/benchmark references, not new production backends.
7. Defer multimodal, multi-user/group and persistent procedural/tool memory until project scope requires them, while avoiding schema choices that make later support impossible.

## Consequences

- Reuse Guard gains selected research/benchmark references but no new heavy runtime dependency.
- Benchmark selection becomes more capability-complete.
- P1 custom work narrows further toward exact source identity, authority non-amplification, conflict quarantine, deletion/replay semantics and evidence-aware context admission.
- P3 persona work should use DyadMem/PersonaTree as external anchors.
- Future portability work must compare against existing portable-memory protocols before defining a custom wire format.

## Revisit when

A new capability class appears, a retained dependency materially changes, or prospective XiaoYu evidence falsifies the current architecture.


## Lead reconciliation with live P1 integration contract

After the external gap-closure report was compared against the live control plane, only R21 and R22 were promoted to required P1 integration stages. R23/R24/R25 are real but are held until P1 freeze; R26 remains P3 HOLD. This prevents literature discovery from automatically expanding the release-critical surface.

The P1 Integration Doctor now evaluates stage dependencies, so a locally accepted downstream semantic component does not count integration-ready while its required source/state/admissibility dependency is blocked.

See `plans/P1_TRUST_LAYER_LEAD_DIGEST_20261027.md`.
