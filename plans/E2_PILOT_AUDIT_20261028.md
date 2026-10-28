# XiaoYu E2 Non-Promotional Pilot Audit — 2026-10-28

Status: **LME EXECUTION COMPLETE / OVERALL PILOT INCOMPLETE — REQUIRED HALUMEM TRACK HELD**

## Claim boundary

This is a non-promotional pilot audit. It does not grant E2 scientific acceptance, does not set confirmatory thresholds, and does not authorize any confirmatory call.

Frozen scientific protocol SHA256:
`0d5805e8a8a773544955724c4490440c237aa1fcdd8876a0d342acad6f2caf14`

Frozen execution manifest SHA256:
`357d5f9192c14bfec3e3e9e54861e23a0c22c84f20a3c353a6bcbe1e0d00b175`

## Executable LongMemEval track

All 46 frozen LongMemEval pilot cases are now COMMITTED.

Execution integrity:
- expected cases: 46
- committed receipts: 46/46
- durable ledger mismatches: 0
- duplicate case IDs: 0
- outside-scope calls: 0
- wrong-case calls: 0
- invariant-prefix mismatches: 0
- completion-cap violations: 0
- missing response receipts: 0
- response receipt hash mismatches: 0
- benchmark peak-window calls: 0
- UNKNOWN/RESERVED benchmark calls: 0
- confirmatory calls: 0

Usage:
- prompt tokens: 62,065
- completion tokens: 1,849
- total raw tokens: 63,914
- pilot hard cap: 1,000,000
- remaining under pilot cap: 936,086
- cache-hit tokens: 0
- cache-miss tokens: 62,065
- observed whole-prompt cache-hit rate: 0%
- average cache miss / committed LME case: 1,349.24
- average completion / committed LME case: 40.2

The 0% cache result is observational, not a correctness gate; the existing post-launch efficiency addendum already explains why the short independent-case prefix is structurally low-value for V4.1 cache reuse.

## Post-paid descriptive LongMemEval diagnostics

Gold was opened only after all 46 paid pilot cases were committed. No LLM judge or confirmatory provider call was made.

Output status:
- resolved: 21
- unknown: 22
- conflict: 3

Deterministic engineering diagnostics:
- normalized exact: 12/46 = 26.09%
- normalized substring: 16/46 = 34.78%
- mean token F1: 0.3498
- median token F1: 0.0

Retrieval diagnostic:
- answer-session hit@7: 32/46 = 69.57%
- exact among retrieval hits: 12/32 = 37.5%
- exact among retrieval misses: 0/14 = 0%

Question-type observations:
- single-session-user: exact 10/20, answer-session hit 15/20
- single-session-assistant: exact 1/6, hit 4/6
- knowledge-update: exact 1/5, hit 4/5
- multi-session: exact 0/5, hit 3/5
- single-session-preference: exact 0/5, hit 1/5
- temporal-reasoning: exact 0/5 despite answer-session hit 5/5 and resolved 0/5

These are descriptive pilot diagnostics, not official LongMemEval LLM-judge accuracy and not E2 thresholds.

## Bottleneck interpretation

The pilot exposes at least two separable bottlenecks.

1. Retrieval coverage:
   14/46 pilot questions had no gold answer session in the frozen top-7 lexical context. None of those 14 produced an exact answer.

2. Context-to-answer / task reasoning:
   Even when an answer session was present, normalized exact was 12/32. The strongest special case is temporal reasoning: all 5 answer sessions were retrieved but all 5 outputs abstained/non-exact.

Therefore simply increasing answer-model confidence would not fix the retrieval misses, while only improving retrieval would not solve all answer failures.

## Required HaluMem track is not complete

The frozen scientific protocol lists HaluMem operation/hallucination as a **required track**, not an optional post-core track.

The frozen execution manifest currently holds:
- `halumem_extract`: `HOLD_OPEN_DOMAIN_SCHEMA_MISMATCH`
- `halumem_qa`: `HOLD_DEPENDS_ON_VALID_HALUMEM_MEMORY_PIPELINE`

Reason:
the accepted P1 R27/R35 extractor is a finite-slot current-state extractor, while HaluMem is an open-domain memory task. Paying for the frozen 647 extraction cases with that extractor would test the wrong capability. The runner correctly fails closed.

Accordingly:
- LongMemEval executable pilot subtrack: **COMPLETE**
- trust-layer reused controls: **inherited from accepted P1/P2 receipts**
- HaluMem required pilot subtrack: **NOT EXECUTED / SCIENTIFIC SCHEMA BLOCKER**
- overall E2 non-promotional pilot: **INCOMPLETE**
- separate confirmatory threshold/protocol freeze: **BLOCKED**
- untouched confirmatory cases/users: **must remain untouched**

## Pilot success-gate interpretation

For the executed LongMemEval track, the execution hard requirements are satisfied: frozen fingerprints/case IDs/payload hashes, gold exclusion, zero duplicate paid work, receipt binding, allowlisted proxy, structural execution checks and token cap.

The overall pilot success gate cannot be declared passed because a frozen required track remains unexecuted for a scientific capability mismatch. Quality metrics remain descriptive-only regardless.

## Required next transition

Do **not**:
- execute HaluMem with the finite-slot R35 extractor;
- use hand-built HaluMem QA context;
- touch confirmatory HaluMem users or LongMemEval confirmatory cases;
- set confirmatory thresholds as though the full pilot were complete.

The next legitimate transition is a separately reviewed/frozen open-domain HaluMem memory pipeline or an explicit Lead protocol amendment that changes required-track scope before execution. Reuse of already accepted components should be assessed before any new implementation.

Artifacts:
- `governance/E2_LME_PILOT_POSTRUN_AUDIT.json`
- 46 receipts under `governance/e2_pilot_runtime/`
- durable paid ledger `governance/research_api_usage.sqlite3`
- frozen protocol / split / execution manifest
