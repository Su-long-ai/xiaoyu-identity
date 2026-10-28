# XiaoYu E2 Pilot Research Reopen Checkpoint — 2026-10-28

Status: **LME PILOT COMPLETE / HALUMEM HELD / TWO BOUNDED RESEARCH GAPS OPEN**

## Paid execution state

LongMemEval frozen nonpromotional pilot:
- manifest cases: 46
- durable ledger cases: 46
- exact membership: PASS
- COMMITTED: 46 / 46
- RESERVED / UNKNOWN: 0
- outside-manifest calls: 0
- confirmatory calls: 0
- prompt tokens: 62,065
- completion tokens: 1,849
- raw tokens: 63,914
- cache hit tokens: 0
- cache miss tokens: 62,065
- E2 pilot hard cap remaining: 936,086

No HaluMem paid call has executed.

## LongMemEval postrun diagnostic

Canonical artifact:
`governance/E2_LME_PILOT_POSTRUN_AUDIT.json`

Descriptive only:
- normalized exact: 12 / 46 = 26.09%
- normalized substring: 16 / 46 = 34.78%
- mean token F1: 0.3498
- answer-session hit@7: 32 / 46 = 69.57%
- exact given answer-session hit: 12 / 32 = 37.5%
- exact given retrieval miss: 0 / 14
- temporal: answer-session hit 5 / 5, exact 0 / 5

Conclusion:
retrieval coverage is a material bottleneck, but not the only bottleneck. Context-to-answer / temporal / update reasoning remains independently weak.

The original 46 receipts are immutable. There is no unexecuted LongMemEval pilot holdout left. The 454 confirmatory cases remain untouched.

## Efficiency interpretation

The pre-execution token contract is preserved as historical evidence.

Post-first-real-batch addendum:
`governance/E2_PILOT_EFFICIENCY_METRIC_ADDENDUM.json`

Effective LongMemEval efficiency metrics:
- cache-miss tokens / committed case
- raw tokens / committed case
- completion tokens / committed case
- off-peak CNY / committed case

The old 95% stable-prefix target is observational-only for this workload. The current frozen pilot prompt is not padded or mutated to chase cache hits.

## HaluMem blocker

Required HaluMem tracks remain:
- extract: `HOLD_OPEN_DOMAIN_SCHEMA_MISMATCH`
- QA: `HOLD_DEPENDS_ON_VALID_HALUMEM_MEMORY_PIPELINE`

Current proposal-only artifacts:
- `governance/E2_HALUMEM_OPEN_DOMAIN_TRANSITION_CANDIDATE.json`
- `governance/E2_HALUMEM_PAIR_SOURCE_CANDIDATE.json`
- `governance/E2_HALUMEM_PILOT_SHAPE_AUDIT.json`

The source-pair candidate contains 647 deterministic user+assistant pairs from the already frozen two pilot users. Forbidden fields (memory_points, questions, answer, evidence, original_memories) are absent from runtime pair payloads. Confirmatory user records selected/analyzed by the pair builder: 0.

The shape audit is diagnostic only. It shows assistant-origin support is material and therefore a user-only extractor is not faithful to HaluMem full-dialogue ingestion. Benchmark annotations used for the shape audit must never become runtime model input.

## Research tasks reopened

Only two bounded E2 research tasks are allowed. Self-directed exploration remains closed.

### R47 — HaluMem open-domain ingest/update
Agent ID: `fish_re_b_20261026_identity`
Lease: `fish-1aeee6aa1bb649bf`
Workspace: `governance/workspaces/fish-1aeee6aa1bb649bf`

Goal:
replace the scientifically invalid finite-slot extraction bridge with the minimum source-grounded open-domain representation/update contract while reusing existing source identity, authority, provenance, SQLite/FTS5 and strict validation.

Lead E0 support:
- generated semantic-key-as-identity fails under paraphrased update/retraction;
- immutable source-span claim IDs + explicit supersedes/retracts/derived_from relations pass synthetic update, retraction, derived-taint, assistant separation, unresolved conflict and restart/replay checks;
- typed RETRACTION is control provenance, not model-visible user fact;
- validator probe passes all current caller-ownership / grounding / ambiguity checks.

No HaluMem paid execution is authorized by this E0 evidence.

### R48 — LongMemEval retrieval repair
Agent ID: `fish_re_a_20261026_t04_9b72`
Lease: `fish-5720c28835f24163`
Workspace: `governance/workspaces/fish-5720c28835f24163`

Goal:
repair the brittle rarest-term / per-message recall policy without replacing the accepted SQLite FTS5/source-authority infrastructure.

Lead E0 support:
- pure session-level replacement improves some misses but regresses an already-correct case => reject;
- frozen baseline retrieval + bounded session-aware user-history supplement reaches gold-literal-in-context 8/8 on the first eight already-exposed cases, versus 6/8 baseline;
- this is retrospective E0 only and does not solve the independent answer/reasoning bottleneck.

All 46 pilot cases are already exposed, so R48 has no prospective pilot holdout. It may use those cases only retrospectively plus synthetic/pre-frozen nonconfirmatory probes. Any new LongMemEval outcome claim must wait for a separately frozen confirmatory protocol.

## Auditor status

No Auditor is started yet.

Correct trigger:
start one independent Auditor only after R47 or R48 produces a concrete candidate submission. Do not occupy the audit slot before there is a candidate to falsify.

## Claim ceiling

- P1 frozen integration-ready: unchanged
- P2 closed: unchanged
- E2 nonpromotional pilot: incomplete because HaluMem required track is held
- confirmatory thresholds/protocol: not frozen
- E2 scientific acceptance: false
- E3/product readiness: false
