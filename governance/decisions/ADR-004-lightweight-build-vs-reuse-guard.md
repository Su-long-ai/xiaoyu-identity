# ADR-004 — Lightweight local Build-vs-Reuse guard

Status: Accepted
Date: 2026-10-27

## Context
The project needs machine-enforced reuse decisions, but its policy set is small and local. Mature Policy-as-Code and catalog systems exist, but installing one would add another platform to operate.

## Considered options
1. Prompt-only guidance.
2. Keep stdlib + SQLite control plane with machine-readable catalog, decision logs, tests, lifecycle and prior-work checks.
3. Add OPA/Cedar/Backstage/MLflow as mandatory project infrastructure.

## Decision
Use option 2. Borrow schema validation, lifecycle, searchable prior work, decision revision and audit-log ideas without adding a separate service.

## Consequences
The guard remains fast/offline and cannot become a general policy platform. OS-level permissions remain outside its boundary.

## Revisit when
Policy count, team size, multi-repository scope, or authorization complexity makes local rules demonstrably unmanageable.
