# ADR-003 — Reuse generic provenance mechanics; keep XiaoYu identity semantics

Status: Accepted
Date: 2026-10-27

## Context
Cognee and Graphiti already provide lineage, source references, invalidation, temporal validity, transactional append and related provenance mechanics. XiaoYu additionally requires fail-closed source identity and user/assistant authority.

## Considered options
1. Build a general provenance platform in XiaoYu.
2. Adopt an external provenance product as the entire identity state.
3. Reuse/reference generic mechanics but keep a thin XiaoYu-specific evidence boundary.

## Decision
Use option 3.

## Consequences
Custom code is limited to stable source identity, semantic-conflict quarantine, source authority, correction/withdrawal state policy, and fail-closed coupling between evidence validity and identity mutation. Generic provenance vocabulary/storage machinery must not expand without a falsifier.

## Revisit when
A retained external mechanism proves the full XiaoYu fail-closed semantic contract or a new interoperability requirement appears.
