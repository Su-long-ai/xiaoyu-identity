# ADR-001 — SQLite FTS5 over handwritten lexical postings

Status: Accepted
Date: 2026-10-27
Supersedes: production intent of the handwritten `evidence_terms(term, doc_key)` prototype

## Context
XiaoYu needs global source-aware lexical retrieval without the newest-1000 blind spot. A research prototype implemented its own posting table, DF lookup, rebuild and deletion path.

## Considered options
1. Keep the handwritten posting engine.
2. Use SQLite FTS5 + `fts5vocab` while keeping XiaoYu tokenizer/authority/ranking policy.
3. Add an external search service.

## Decision
Use option 2. The matched 3,202-document E0 probe preserved 180/180 user+assistant retrieval and lifecycle/authority behavior while improving build and query latency. Do not add a search service.

## Consequences
XiaoYu owns retrieval policy, not posting infrastructure. Handwritten postings remain research evidence only.

## Revisit when
FTS5 is prospectively falsified on a required correctness, language, scale, or transaction property.
