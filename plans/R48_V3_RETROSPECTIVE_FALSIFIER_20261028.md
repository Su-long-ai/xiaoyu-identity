# R48 v3 retrospective falsifier — 2026-10-28

Status: **LEAD E0 / RETROSPECTIVE EXPOSED-PILOT FALSIFIER**

Candidate under test:
- r48_fts5_candidate_v3.py
- SHA256: 0a596f3480a0109e2de778d9ec77945e22cf2773b869066af90516222a06289f

No provider calls were made. No confirmatory cases were read.

## 46-case retrospective result

Against the already-exposed 46 LongMemEval pilot cases:

- baseline any-answer-session coverage: 32 / 46
- v3 any-answer-session coverage: 40 / 46
- baseline full-answer-session coverage: 24 / 46
- v3 full-answer-session coverage: 33 / 46
- full gains: 10
- full losses: 1
- authority violations: 0
- context budget violations: 0

Among the 14 baseline retrieval misses:
- v3 recovers any answer session in 9 / 14
- v3 recovers the full answer-session set in 7 / 14

Among the 12 previously normalized-exact pilot cases:
- baseline full coverage: 11 / 12
- v3 full coverage: 10 / 12
- regression: lme-a-001

## lme-a-001 regression

Question:
How long is my daily commute to work?

Gold answer session:
answer_40a90d51

v3 query tokens:
long / daily / commute / work

v3 selected three unrelated sessions whose best coherent records each cover three common query terms. The true commute answer session is omitted entirely.

Observed failure mechanism:
the v3 session score rewards raw distinct/coherent query-term count. Generic terms such as long, daily and work can jointly dominate a semantically decisive but less frequent term such as commute.

This is a common-term coherence-dominance failure, not an authority failure.

## Required remediation gate

R48 must preserve lme-a-001 answer-session coverage without:
- using answer_session_ids, gold, question-type labels or evaluator coordinates as retrieval input;
- weakening the top-7 record budget;
- regressing the frozen 120-case/OOD, 60-case neighbor, common-flood or authority tests;
- introducing a new retrieval backend.

A valid repair may use deterministic term discriminativeness/DF weighting or an equivalent bounded SQLite-FTS5-native rule, but must remain source/authority preserving and deterministic.

This retrospective result is a development falsifier only. It does not create a new LongMemEval outcome claim.
