# PRODUCT_REUSE_GATE_V1

Date: 2026-11-18

Status: ADOPTED

## Decision

Commodity product capability is reuse-first. XiaoYu keeps only authority/policy semantics that mature external components cannot own without weakening identity, privacy, freshness, erasure, execution or release invariants.

The implementation CI therefore machine-checks guarded commodity areas. A PR touching one of those areas must declare a reviewed component from `REUSE_CATALOG.json` whose component kind matches the affected area. Direct reuse is preferred. Bounded XiaoYu-specific glue is allowed only as `extend` or `custom_policy` with an explicit gap and `no_new_infrastructure=true`.

## Initial adopted/trial substrates

- Provider transport: LiteLLM, single selected-provider attempt only.
- Credentials: Python keyring / host OS credential store.
- Resource telemetry: psutil and NVIDIA NVML bindings.
- Vision capture: MSS.
- Voice orchestration: Pipecat.
- Observability: OpenTelemetry.
- Retrieval: SQLite FTS5 with FastEmbed semantic trials.

## Explicit boundary

This decision does not outsource XiaoYu semantic authority. Temporal truth, principal/delegation authorization, Purpose/occurrence semantics, Effect/outbox reconciliation, audience/freshness fences, erasure/restore and release semantic gates remain XiaoYu-owned unless a later evidence-backed architecture decision supersedes them.

## Enforcement

- Policy: `governance/IMPLEMENTATION_REUSE_POLICY.json`
- Gate: `governance/implementation_reuse_gate.py`
- Per-change decisions: `governance/implementation_reuse_decisions/*.json`
- Catalog: `governance/REUSE_CATALOG.json`
- CI: `.github/workflows/implementation-v1.yml`
