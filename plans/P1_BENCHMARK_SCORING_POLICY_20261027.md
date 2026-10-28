# XiaoYu Memory Benchmark Scoring Policy — 2026-10-27

Status: **frozen evaluation policy for future matched retrieval studies**

## Problem

XiaoYu can store several representations linked to one original conversation source:
- raw source event / turn;
- validated structured event;
- current-state projection;
- historical/superseded state;
- source-linked retrieval descendants.

A retrieval system can appear better or worse depending only on which representation receives credit. Therefore "gold fact string appeared somewhere" is not a sufficient universal metric.

## Required scoring target

Every retrieval benchmark/probe must declare one primary target before execution:

- **RAW** — the exact original source/turn is the target.
- **SOURCE** — a descendant is creditable only when it is explicitly and validly linked to the gold source under the benchmark rule.
- **CANONICAL_CURRENT** — only the currently authoritative state representation receives primary credit; stale/superseded descendants do not.
- **TASK_DEFINED** — only when an external benchmark formally defines a different target; record that definition unchanged.

Do not silently switch targets after seeing results.

## XiaoYu default

- source-evidence/retrieval diagnostics: report RAW and SOURCE separately;
- current preference/state questions: CANONICAL_CURRENT is primary, with source evidence recall as a secondary diagnostic;
- temporal/history questions: use a task-defined time-conditioned canonical target;
- assistant-origin history: preserve assistant source attribution; do not promote it to user-current-state credit.

## Save once, rescore cheaply

When feasible, persist the full ranked retrieval output with:
- stable source IDs;
- descendant/canonical IDs;
- authority/source role;
- temporal validity/supersession state;
- score/rank;
- frozen query ID and benchmark target metadata.

Scoring-policy audits should rescore these saved outputs without rerunning paid extraction/retrieval/model calls.

## Claim rule

A reported improvement must state the scoring target. If the winner or conclusion changes across reasonable RAW/SOURCE/CANONICAL_CURRENT targets, report that sensitivity rather than selecting the favorable target.

This policy prevents source-linked derived memories from receiving accidental double/relaxed credit and reduces expensive benchmark reruns.
