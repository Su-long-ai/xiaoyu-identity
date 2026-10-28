# ADR-006 — Freeze broad memory-framework collection

Status: Accepted
Date: 2026-10-27

## Context
Mem0, Hindsight, Cognee and Graphiti already span extraction, source attribution, vector/graph retrieval and temporal graph designs. Additional framework collection risks benchmarking products instead of resolving XiaoYu requirements.

## Decision
Keep Mem0/Hindsight/Cognee/Graphiti as the retained reference set plus OmniMemEval as a shared harness. Add a new framework only when it tests a materially missing capability.

## Consequences
New external research should prefer benchmark-capability gaps over vendor/framework count.

## Revisit when
A concrete XiaoYu requirement cannot be falsified with the retained references or a materially different architecture emerges.
