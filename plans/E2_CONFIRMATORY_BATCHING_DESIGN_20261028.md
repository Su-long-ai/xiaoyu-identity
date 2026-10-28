# E2 Confirmatory Batching Design Gate — 2026-10-28

Status: **DESIGN_ONLY / HOLD_BEFORE_CONFIRMATORY**

This plan is intentionally not executable during the current E2 pilot. It exists to reduce fixed prompt overhead in a future confirmatory run without retrospectively changing the pilot protocol.

## Motivation

LongMemEval cases are independent and currently share only a short fixed evaluator prefix. The first real E2 calls showed that chasing provider KV-cache hit rate is low-value for this geometry. Batching can instead amortize the fixed system/instruction cost across several independent cases in one provider request.

## Candidate design

Evaluate fixed batch sizes **1 / 2 / 4 / 8** before confirmatory execution. No adaptive batch size based on outcomes is allowed.

Each batch must:
- contain only cases from the already-frozen confirmatory split;
- preserve each case's independent `id / context / question`;
- expose no gold/answer fields;
- require exactly one result per input case ID;
- reject duplicate, missing, unknown or extra result IDs;
- prohibit cross-case evidence IDs;
- score each case independently after transport validation.

## Failure and resume semantics

A provider response is accepted only if the entire response envelope has a bijection with the input case IDs.

If any case item is missing, duplicated, structurally invalid or contains evidence from another case:
- the batch is structurally failed;
- no partial item is promoted as confirmatory evidence;
- retry policy must be frozen before execution;
- durable ledger must prevent an already committed batch from being paid twice.

Provider/network UNKNOWN remains fail-closed and requires reconciliation before retry.

## Required pre-execution comparison

Before any confirmatory call, freeze a pilot-only or synthetic matched comparison of batch size 1 vs 2/4/8 and measure:

- per-case answer/evidence exactness;
- cross-case contamination;
- missing/duplicate/extra output rate;
- total tokens per useful case;
- cache-miss tokens per useful case;
- completion tokens per useful case;
- CNY per useful case;
- latency per useful case.

A batch size is eligible only if it is semantically non-inferior and transport-safe. Cost savings alone cannot promote a batching mode.

## Hold conditions

Current pilot batching: **FORBIDDEN**.

Confirmatory batching remains HOLD until:
1. current pilot is closed;
2. HaluMem open-domain path status is resolved independently;
3. a prospective batch contract and parser are frozen;
4. failure/retry semantics are frozen;
5. no confirmatory case has been exposed to the provider.

This document authorizes design work only, not provider execution.
