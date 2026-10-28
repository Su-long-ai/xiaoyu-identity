# XiaoYu E1 Integration Triage — 2026-10-27

## Scope

This note distinguishes "accepted scientific E1 evidence" from "ready to merge
into the product". No production identity data is modified.

## 1. model.deepseek.zh_event_parser — CANDIDATE INTEGRATION

Evidence:
- frozen prospective Chinese set: 160/160 exact state, 0 unsupported confident
  claims vs frozen rules V2 120/160 and char speech-act 94/160;
- prospective open-vocabulary set: 96/96, grounded 88/88, 0 false claims;
- independent long-context stress: 36/36 through 96 messages;
- independent dense same-slot interference: state 32/32, 0 false claims.

Important counterexample:
- same-slot late-correction provenance: 3/4 cases returned the immediately
  preceding assistant guess as evidence even though the selected final state was
  correct and the assistant guess did not support it.

Decision:
- integrate only as a candidate semantic-event projector behind an interface;
- do NOT let model answer correctness implicitly authorize source_event;
- every non-null evidence pointer must be checked against source role, quoted
  value / semantic support, temporal validity and event existence before commit;
- unsupported/mismatched evidence => quarantine/abstain, never silently attach;
- retain deterministic raw event log as the source of truth;
- continue external benchmarks before declaring it the permanent architecture.

Cost evidence:
- engineer E1 campaign: 101,011 measured tokens / 78 calls;
- non-thinking DeepSeek Flash, temperature 0, top_p 1.

## 2. retrieval.longtail.1000cap — DIRECTION ACCEPTED, INTEGRATION DEFERRED

Confirmed V2 defect:
- recall truncates candidate pool to newest 1000 active memories before ranking;
- at 1001 records, oldest memory becomes structurally unreachable;
- independent tests reproduced this deterministically.

Prototype benefit:
- frozen lexical inverted-index prototype recovered 120/120 vs V2 80/120 on
  900/1100/1600-memory transfer;
- independent reproduction matched;
- high-fanout 3000-posting query stayed near V2 latency and faster than full scan.

Blocking engineering gaps before adoption:
1. post-build additions: stale index 0/100 until rebuild;
2. archived rows are not served but stale posting tokens remain;
3. prototype excludes assistant-sourced and default add_memory records that V2
   currently can retrieve;
4. no persistent/incremental crash-consistent index;
5. no semantic Chinese paraphrase guarantee.

Decision:
- do not merge this in-memory prototype;
- use the accepted E1 as proof that the newest-1000 design must be replaced;
- compare SQLite FTS5 / persistent incremental inverted index / hybrid recent+
  global retrieval under the same LongMemEval and Chinese OOD harness;
- source eligibility must be explicit and must include whichever assistant-source
  memories survive the external-framework comparison.

## 3. Architectural consequence

The emerging architecture should remain layered:

raw immutable-ish event/provenance log
    -> validated semantic event projection
    -> typed current/historical state
    -> persistent global retrieval/index
    -> evidence-aware context packing
    -> answer model

External frameworks (Mem0, Hindsight, later Graphiti/Cognee/EverOS) are used to
falsify whether each custom layer is actually needed. A custom XiaoYu component
stays only when matched experiments show a reproducible advantage or a required
identity/privacy property unavailable in the external alternative.
