# XiaoYu E2 Token / Cost Optimization Closeout — 2026-10-28

Status: **IMPLEMENTED / RE-FROZEN BEFORE FIRST E2 PAID CALL**

## Outcome

Token/cost optimization is now an execution-layer contract rather than advisory documentation.

The frozen scientific E2 protocol and pilot/confirmatory user split were not changed.

At closeout:
- benchmark paid calls: **0**
- benchmark used/reserved tokens: **0**
- E2 pilot execution hard cap: **1,000,000 raw tokens**
- full benchmark allocation remains a ceiling, not an execution target: **95,000,000**
- E2 claim eligibility: **false**
- confirmatory calls: **forbidden**

## Historical diagnosis

Lifetime smoke-era measured cache telemetry:
- prompt tokens: 3,953,983
- completion tokens: 547,321
- measured cache-hit tokens: 1,039,483
- measured cache-miss tokens: 1,723,497
- measured hit rate: **37.6218%**

This is not an E2 quality gate because it mixes heterogeneous smoke/framework traffic.

Examples supporting the optimization direction:
- Hindsight historical scope: ~82.1% cache hit.
- XiaoYu generic proxy historical scope: ~61.0%.
- several legacy direct HaluMem scopes: 0% measured cache hit.

E2 therefore starts from separate phase-local telemetry at zero.

## Implemented cost controls

### Stable-prefix execution

Every frozen E2 track has:
- byte-stable invariant prefix;
- frozen prefix SHA256;
- case-specific payload last;
- accepted P1 dynamic payload encoding;
- exact response_format;
- per-track completion ceiling.

Stable-prefix target is >=95%, but whole-prompt hit rate is observational because case-specific benchmark content is necessarily novel.

No synthetic paid cache-warmup calls are allowed. The first two real frozen cases in each scope execute serially; bounded parallelism begins only afterward.

### Per-track completion caps

- LongMemEval answer: **512**
- HaluMem extraction: **512**
- HaluMem QA: **768**

The extraction cap was tightened from 1536 after checking accepted R35 paid evidence:
- historical completion maximum: 83 tokens;
- p95: 81;
- mean: 49.7.

A 512-token cap retains >6x the historical maximum without paying for a needlessly large reservation envelope.

## HaluMem extraction granularity correction

A pre-execution audit found the first execution manifest had one extraction paid case per selected HaluMem session.

That was invalid against the accepted P1 extractor contract, which processes exactly one target user message.

The 32 selected sessions contain:
- **647 user turns**
- mean **20.22** user turns/session
- min 8 / max 38 user turns/session
- user-message length mean 128 chars
- p95 242 chars
- p99 377 chars
- max 513 chars

The manifest was corrected before any E2 paid call:
- old extraction cases: 32 session-level
- new extraction cases: **647 message-level**
- LongMemEval answer: 46
- HaluMem QA: 51
- total frozen paid operations: **744**

Accepted R35 historical cost was 15,003 raw tokens / 40 calls = ~375.1 tokens/call, implying a rough 647-call extraction projection of ~243k raw tokens. The 1M pilot hard cap remains intact.

The extraction scope call counter was raised from 50 to 700 only to avoid false count-based blocking; raw/cache-miss/output caps, pilot hard cap, peak-hour block and global concurrency=2 remain active.

## Accepted dynamic payload reuse

No new prompt semantics were invented.

Context-answer tracks reuse accepted R18/R29 encoding:
- fixed R18 system prompt;
- final user payload = `逐项回答以下独立案例：\n` + compact single-case JSON array;
- required fields: id/context/question.

Extraction reuses accepted R35 encoding:
- fixed accepted event-extraction system prompt;
- one compact JSON object;
- current_state/context_messages/target_message/slots;
- target_message must be role=user.

Gold/answer-only fields are rejected by the runner before provider access.

## Duplicate and crash-loss prevention

Provider-side ledger now records for E2 cases:
- case_id;
- invariant prefix SHA;
- response text;
- response SHA256;
- usage/call ID/status.

For E2, COMMITTED is written atomically with a durable response receipt.

Resume behavior:
- COMMITTED: recover response from paid ledger, **no second paid call**;
- RESERVED/UNKNOWN: fail closed until explicit reconciliation;
- duplicate RESERVED/COMMITTED/UNKNOWN case IDs: blocked under SQLite BEGIN IMMEDIATE.

This closes the previous crash window where a provider-successful call could be paid/committed but its caller process could die before saving the response locally.

## Unified runner

Added:
`governance/e2_pilot_runner.py`

It supports:
- preflight (zero provider calls);
- offline plan validation;
- committed-case recovery;
- explicit single-case execution only.

The runner validates exact frozen track/case membership, accepted payload shape, gold exclusion, prefix hash, response cap and durable ledger receipt.

Runtime receipts are regenerable and excluded from Git.


## LongMemEval input freeze and source-identity repair

The token-safe gateway is not sufficient if the local retrieval/context payload can drift between runs.

A frozen offline LongMemEval adapter is now included at governance/e2_longmemeval_context.py.

It:
- verifies the public LongMemEval-S dataset SHA256 before building input;
- uses the P1-frozen SQLite FTS5 / source-aware authority policy;
- maps raw user source to user_history and assistant source to conversation_history;
- exposes at most seven whole source records;
- never reads answer/gold fields into the paid payload;
- makes zero provider calls.

All **46/46** frozen LongMemEval pilot payloads were materialized in an isolated Lead workspace and checked against the manifest:
- rows: 46;
- unique case IDs: 46;
- frozen cases: 46;
- missing: 0;
- extra: 0;
- payload-SHA mismatches: 0;
- gold-field leakage: 0;
- provider calls: 0.

The manifest stores a SHA256 for every individual LongMemEval payload. The runner recomputes it before provider access, so a later retrieval-code change cannot silently change E2 model-visible context.

Full 46-case construction exposed a real source-identity bug that the first two warm-up cases did not cover: LongMemEval can repeat haystack_session_ids within one record. A source key based only on case/session-id/message-index could therefore collide.

The source key now also binds the stable session ordinal:

case + session_ordinal + original_session_id + message_ordinal

A dedicated regression test covers repeated session IDs. This changes identity disambiguation only; it does not alter source text, gold data or scoring.

Generated governance/e2_pilot_inputs/ files are deliberately ignored and are not the source of truth because concurrent preparation may regenerate them. The frozen per-case payload hashes in E2_PILOT_EXECUTION_MANIFEST.json are authoritative.

This LongMemEval builder is an **E2 evaluation adapter** implementing the P1-frozen retrieval policy. Its success must not be misreported as proof that every future production retrieval implementation has been end-to-end validated.

## HaluMem fail-closed hold

Pre-execution validation also found that the accepted P1 R27/R35 extractor is a finite-slot current-state extractor while HaluMem is an open-domain memory task.

Accordingly:
- longmemeval_answer: **READY**
- halumem_extract: **HOLD_OPEN_DOMAIN_SCHEMA_MISMATCH**
- halumem_qa: **HOLD_DEPENDS_ON_VALID_HALUMEM_MEMORY_PIPELINE**

The 647 message-level HaluMem extract IDs remain frozen for accounting/reproducibility, but the gateway/runner must not spend tokens on that held track.

This is intentional cost correctness: changing the slot schema or inventing an open-domain ingest path after seeing the pilot definition would alter the tested capability. Resolving it requires a separately frozen scientific transition, not a token-optimization shortcut.

## Frozen implementation

Scientific protocol SHA256 remains:
`0d5805e8a8a773544955724c4490440c237aa1fcdd8876a0d342acad6f2caf14`

Split SHA256 remains:
`07f209183bea2b1c11c18f2073173a6576df3396396c4ffc520cd18afe3cfd1f`

Prompt freeze SHA256:
`19300dd3f3cc7c52ae9a4836e637f0bc8b6f7ca20b2cce56649078d48729ddf9`

New execution manifest SHA256:
`357d5f9192c14bfec3e3e9e54861e23a0c22c84f20a3c353a6bcbe1e0d00b175`

New execution freeze record SHA256:
`2505302ab35bc82182b6c5adaa2f8a78e742b2790913db7bb234f89ca24e46e2`

The freeze record binds protocol, split, prompts, token contract, manifest builder, freeze script, paid gateway, proxy, pilot runner, token doctor, the LongMemEval input builder, and frozen P1/P2 baselines.

## Validation

- E2 Token Efficiency Doctor: **healthy=true**
- errors: **0**
- warnings: **0**
- pilot_execution_ready: **true**
- executable tracks: **LongMemEval READY; HaluMem extract/QA HOLD fail-closed**
- missing response receipts: **0**
- response receipt hash mismatches: **0**
- prefix mismatches: **0**
- duplicate paid case IDs: **0**
- peak calls: **0**
- benchmark UNKNOWN/RESERVED: **0**
- unified runner preflight: **ready=true**
- targeted runner/gateway/input tests: **47/47 PASS**
- complete governance regression: **170/170 PASS**
- P1: **12/12 READY**
- P2: **7/7 READY**
- Reuse Doctor: **healthy=true, 0 errors, 0 warnings**

## Nonclaims

No provider cache-hit >=95% result is claimed yet because E2 has made zero paid calls.

The 95% target is for the invariant prefix, while provider telemetry exposes aggregate prompt cache hit/miss. Exact prefix bytes are structurally enforced; empirical cache behavior will be observed from the real pilot.

No E2 scientific acceptance or E3/product claim is granted by these optimizations.
