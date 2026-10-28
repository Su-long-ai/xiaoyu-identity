# ADR-002 — Single authoritative SQLite portable identity

Status: Accepted E1 portability mechanism (tested scope; importer robustness advisories remain)
Date: 2026-10-27
Supersedes: future use of SQLite + duplicate identity.json + manifest ZIP as the authority format

## Context
The V2 ZIP export duplicates logical identity state across SQLite and JSON and creates parser/container race and ambiguity classes.

## Considered options
1. Keep patching the dual-view ZIP.
2. Use one SQLite online-backup snapshot as the authority artifact.
3. Create a new custom archive/container.

## Decision
Prefer option 2 for future P1/P2 portability. Keep V2 ZIP only as a legacy migration input.

## Consequences
Authentication, freshness/rollback, semantic validation, and deletion lineage remain separate requirements. A backup copy containing erased data must never become active merely because it is restored.

## Revisit when
A required portability property cannot be represented or validated from the authoritative SQLite snapshot plus standard external metadata/signature mechanisms.

## Independent E1 update — 2026-10-27

sub-08300cd8e3e44f62 was independently ACCEPT_E1 for the single authoritative SQLite snapshot claim. The audit also found two P2 nonblocking importer issues: late inspection failure can leave a destination that prevents simple retry, and metadata can change between source preflight and import without being covered by the business logical root. These do not restore the dual-view ZIP architecture; they remain importer-hardening debt before stronger production claims.
