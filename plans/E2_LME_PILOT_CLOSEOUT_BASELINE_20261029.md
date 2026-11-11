# E2 LongMemEval Pilot Closeout Baseline — 2026-10-29

Status: **46/46 PAID PILOT COMPLETE / RETROSPECTIVE REPAIRS SEPARATELY ACCEPTED / NO E2 CLAIM**

This checkpoint freezes the distinction between:
1. what the original frozen paid LongMemEval pilot actually achieved; and
2. what later R48/R50 implementation research demonstrated retrospectively without new paid LongMemEval calls.

## Original paid pilot — immutable outcome baseline

Authoritative audit:
`governance/E2_LME_PILOT_POSTRUN_AUDIT.json`

SHA256:
`09e49e07fc8d98fdb6ec6ddc85bdc163c7de6c1e583daf9c2bcf8889d421f8a3`

All **46 / 46** frozen pilot cases were committed under the original execution policy.

Provider usage:
- prompt tokens: **62,065**
- completion tokens: **1,849**
- actual tokens: **63,914**
- cache hit: **0**
- cache miss: **62,065**

Original deterministic engineering quality:
- normalized exact: **12 / 46 = 26.09%**
- normalized substring: **16 / 46 = 34.78%**
- mean token F1: **0.3498**
- answer-session hit@7: **32 / 46 = 69.57%**
- exact given answer-session hit: **12 / 32 = 37.5%**
- exact given retrieval miss: **0 / 14**

Original response statuses:
- resolved: **21**
- unknown: **22**
- conflict: **3**

By question type:
- single-session-user: 10/20 exact, 15/20 answer-session hit
- multi-session: 0/5 exact, 3/5 answer-session hit
- single-session-assistant: 1/6 exact, 4/6 answer-session hit
- single-session-preference: 0/5 exact, 1/5 answer-session hit
- temporal-reasoning: **0/5 exact, 5/5 answer-session hit**
- knowledge-update: **1/5 exact, 4/5 answer-session hit**

The last two rows are the key decomposition: temporal/current-state failures persisted even when retrieval found the answer session, so retrieval repair alone could not close the pilot gap.

## R48 — retrieval repair evidence

Backlog status: **done / ACCEPT_E1**

Submission:
`sub-df989b99335a4512`

Independent review:
`review-9e7664649a224cce`

Accepted evidence:
- frozen holdout: 120/120
- neighbor gate: 60/60
- determinism: 900/900
- retrospective exposed-pilot full answer-session coverage: **24/46 -> 36/46**
- zero full losses
- lme-a-001 retained

Interpretation:
R48 is accepted **implementation/retrieval evidence**. It does not change the original 12/46 paid outcome and it does not create a new LongMemEval outcome claim.

## R50 — temporal/current-state consumption evidence

Backlog status: **done / ACCEPT_E1**

Submission:
`sub-833b0824063e488a`

Independent review:
`review-06f12cae5f3b4da4`

Accepted evidence:
- original temporal/current-state falsifier: 72/72
- shuffle stability: 720/720
- fresh mixed-key/malformed-evidence fuzz: 1,400/1,400
- new paid LongMemEval calls: **0**

Interpretation:
R50 is accepted **implementation-only temporal/current-state reasoning evidence**. It does not retrospectively re-score the 46 paid pilot receipts.

## Scientific boundary

The following statements are allowed:

- The original frozen LongMemEval nonpromotional pilot completed 46/46 paid cases.
- Its original deterministic engineering baseline is 12/46 normalized exact and 32/46 answer-session hit@7.
- R48 independently closes a bounded retrieval-policy implementation gap on frozen/retrospective evidence.
- R50 independently closes a bounded temporal/current-state consumption implementation gap on frozen/synthetic evidence.

The following statements are **not** allowed:

- “The LongMemEval pilot score is now 36/46.”
- “R48/R50 improved the already-run paid pilot.”
- “XiaoYu has passed LongMemEval E2.”
- Any confirmatory/generalization claim before untouched confirmatory execution under a separately frozen protocol.

## Current E2 implication

LongMemEval no longer needs more pilot calls. The implementation findings are mature enough to inform the future confirmatory candidate, while the original paid pilot remains an immutable low baseline that motivated R48/R50.

The only direct E2 pilot research closeout blocker at this checkpoint is R49 HaluMem open-domain semantic transition / destructive confirmation safety.
