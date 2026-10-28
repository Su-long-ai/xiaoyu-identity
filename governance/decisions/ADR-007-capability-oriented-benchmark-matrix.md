# ADR-007 — Capability-oriented benchmark matrix

Status: Accepted planning decision
Date: 2026-10-27

## Context
No single long-memory benchmark covers extraction/update hallucination, explicit temporal recall, implicit conversational use, latent goals/values, and procedural stateful action.

## Decision
Select benchmarks by missing capability rather than by framework:
- LongMemEval / OmniMemEval path: long-horizon retrieval, temporal/update and assistant-origin evidence.
- HaluMem: extraction/update/QA operation-level hallucination.
- LOCOMO-CONV: implicit/composed conversational memory use and end-to-end response quality.
- LoCoMo-Plus: latent user state/goals/values under cue-trigger disconnect.
- STATE-Bench: defer until XiaoYu actually enters state-mutating/tool/procedural agent scope.

## Consequences
Do not unlock all benchmarks at once. Each benchmark must answer a frozen capability question under a cost budget.

## Revisit when
A benchmark duplicates existing coverage or project scope expands to procedural tool actions.
