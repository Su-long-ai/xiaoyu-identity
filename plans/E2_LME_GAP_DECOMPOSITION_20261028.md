# E2 LongMemEval Gap Decomposition — 2026-10-28

Status: **LEAD E0 / POST-RUN ENGINEERING DIAGNOSTIC / NONPROMOTIONAL**

This note decomposes the already-exposed 46-case LongMemEval pilot after all paid pilot calls were committed. It does not authorize new paid calls, does not read confirmatory cases, and is not an E2 scientific claim.

## Observed pilot baseline

- cases: 46
- normalized exact: 12 / 46
- answer-session hit@7: 32 / 46
- retrieval misses: 14
- retrieval-hit but non-exact: 20

## Failure decomposition

Retrieval miss:
- 14 cases
- directly in R48 scope.

Hard non-retrieval falsifiers with answer-session evidence already present:
- temporal reasoning: 5 / 5 answer-session hit, 0 / 5 normalized exact, all five returned unknown;
- knowledge update: 3 cases with answer-session hit were returned as conflict even though the benchmark expects the temporally newer state.

Other hit-but-nonexact categories:
- multi-session synthesis: 3
- preference abstraction: 1
- other hit+unknown: 1
- resolved surface-form mismatch: 4
- resolved substantive mismatch: 3

Surface-form mismatches are not promoted as capability failures because deterministic normalized-exact is stricter than the official LongMemEval judging protocol. Examples include abbreviated or paraphrased answers where the core fact may still be acceptable.

## Lead conclusion

R48 is necessary but not sufficient.

R48 must remain a bounded retrieval/admissibility repair and must not absorb temporal/current-state reasoning merely to improve retrospective pilot scores.

A separate downstream task, R50, is therefore held behind R48. It is justified only by real pilot cases where answer-session evidence was already present but the current context-consumption/state policy still failed.

R50 remains HOLD until R48 reaches ACCEPT_E1 or is explicitly replaced. This preserves the auditor slot and prevents retrieval defects from being masked by downstream reasoning logic.

## Nonclaims

- no official LongMemEval LLM-judge accuracy claim;
- no new LongMemEval paid pilot calls;
- no confirmatory cases touched;
- no E2 acceptance;
- no claim that all 20 retrieval-hit/nonexact cases are true capability failures.
