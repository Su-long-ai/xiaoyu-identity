# ADR-010 — Stop P1 CI hardening at the accepted static trust root

Status: Accepted
Date: 2026-10-27

## Context

The accepted P1 CI E1 (sub-fc06b3ec2b554566) proves exact required-gate membership and content-hash integrity before execution.

Later adversarial work found progressively stronger runtime races: post-preflight local source mutation/startup-path execution; unchecked/sourceless bytecode; symlink/reparse replacement; direct source-read plus pseudo-filename exec; and child Python interpreters that re-read mutated source.

R32 (sub-1d0e40a9a0cb4586, NONPASS/EVIDENCE_ONLY) closes several current-process source-read routes but still demonstrates two child-interpreter bypasses. The historical four-gate workload itself legitimately uses child Python for crash/restart semantics.

## Decision

Do not keep expanding P1 CI into an operating-system/process sandbox.

P1 CI claims only: exact required gate membership is frozen; frozen files are content-hash checked before launch; deterministic gate results are bound to that frozen contract.

It does not claim resistance to an adversary that retains project-directory write authority during gate execution and races arbitrary Python/native/shell child processes. Later runtime-race evidence is retained as P2 hardening debt.

## Why

Closing the stronger threat model correctly would require process-wide/child-process execution provenance or OS-level isolation. Repeated Python monkeypatching of import/open/runpy/subprocess APIs is neither a complete security boundary nor a good use of XiaoYu-specific research effort, and violates the Build-vs-Reuse rule against growing a general software-supply-chain/sandbox platform.

If hostile-local-writer execution integrity becomes a product/release requirement, use an external isolated build/sandbox mechanism or a standard content-addressed execution environment rather than continuing bespoke monkeypatches.

## Consequences

- ci_integrity returns to ready_e1 for its accepted tested scope.
- R15/R28/R32 findings remain valid evidence and are explicitly outside that scope.
- E2 claims must not describe the CI harness as tamper-proof during execution.
- Any future reopening needs a concrete threat-model change and a standard isolation mechanism candidate.
