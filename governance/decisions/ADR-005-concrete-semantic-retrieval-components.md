# ADR-005 — Concrete versioned semantic-retrieval components

Status: Trial
Date: 2026-10-27
Supersedes: generic `fastembed_existing` and `existing_vector_backend` permissions

## Context
A generic backend alias hides implementation/version/security changes. Current local Cognee source concretely pins FastEmbed 0.8.0 and LanceDB 0.39.0; Hindsight exposes pgvector but its server extension version has not yet been verified.

## Decision
Deprecate generic aliases for new claims. Name concrete implementation/version entries in the reuse catalog. Treat FastEmbed/LanceDB as trial research components and Hindsight pgvector as reference-only until exact server version is verified.

## Consequences
Upgrades or backend substitutions require a catalog revision instead of silently inheriting old approval. Semantic fallback remains optional and must earn a benchmark advantage.

## Revisit when
A production semantic fallback is selected, versions change, a security advisory applies, or Chinese-language retrieval quality is inadequate.
