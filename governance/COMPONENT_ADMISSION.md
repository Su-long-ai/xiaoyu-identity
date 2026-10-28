# XiaoYu External Component Admission Policy — 2026-10-27

Status: Build-vs-Reuse V2 operational policy

## Principle

"Reuse before build" does not mean "install whatever exists." A reusable component can reduce duplicated engineering while still adding maintenance, license, vulnerability, provenance, or lock-in risk.

## New external production-capable dependency

Before a component is promoted from `reference` / `trial` to `adopt`, the catalog entry must identify:

- exact component/package/repository;
- exact version, commit, or bounded version policy;
- source locator;
- license;
- owner;
- last verification date and review-after date;
- health/security status;
- decision ADR;
- evidence that known vulnerabilities and dependency health were checked;
- upgrade / replacement trigger.

Useful external evidence sources include package registry metadata, deps.dev/OSV and OpenSSF Scorecard. These checks happen during Lead admission/review, **not on every research lease**, so normal research remains fast and offline.

## Lifecycle

- `adopt`: approved standard/internal mechanism for the stated scope.
- `trial`: concrete component allowed for bounded research; not automatic production approval.
- `reference`: comparator/architectural reference; using it does not make it a production dependency.
- `hold`: do not use for new normal work until the recorded blocker/scope changes.
- `deprecated`: compatibility only; new normal claims fail closed.

A catalog change never rewrites an existing experiment decision. Active work remains bound to its stored decision; `reuse-doctor` reports drift and new work is evaluated against the current catalog.

## Current examples

- SQLite / FTS5 / online backup: adopt.
- FastEmbed 0.8.0 + BAAI/bge-small-en-v1.5 in the current Cognee lock: trial.
- LanceDB 0.39.0 in the current Cognee lock: trial.
- Hindsight pgvector: reference until the actual PostgreSQL extension version is verified; the Python `pgvector` package version is not sufficient proof.
- `existing_vector_backend` and `fastembed_existing`: deprecated aliases, blocked for new normal claims.
- STATE-Bench: hold only because procedural state-mutating agent work is outside current P1 scope, not because the benchmark is considered bad.
