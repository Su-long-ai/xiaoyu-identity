# E2 LongMemEval cache 0% root-cause investigation — 2026-10-28

Status: ROOT_CAUSE_HIGH_CONFIDENCE / NO_PROTOCOL_MUTATION

## Symptom

The first three real LongMemEval E2 pilot calls all used the exact same frozen invariant-prefix SHA256:

`11237ee01ec6a750ef3f8965a849e29a5cbf06897b699cc4724b7a7f75725c7c`

Provider telemetry:

- lme-a-000: prompt 924, cache hit 0, miss 924
- lme-a-001: prompt 1307, cache hit 0, miss 1307
- lme-a-002: prompt 762, cache hit 0, miss 762

This is not a proxy telemetry bug: prompt_tokens = hit + miss for all calls and the durable ledger records the same values.

## Provider/account cache is healthy

Since 2026-10-17, the same local paid ledger contains 2708 DeepSeek Flash committed calls with cache telemetry:

- hit calls: 1526
- total hit tokens: 1,039,483
- total miss tokens: 1,726,490

Recent same-model XiaoYu calls show repeated 128-token cache hits. Therefore the account, DeepSeek Flash model, local gateway, and usage parsing all demonstrably support cache hits.

## Same R18 prompt historically also had zero hits

The exact E2 context-answer system prompt has SHA256:

`5ff0d7c79ff15180e9963d3c102d948d21d8d71116c382804aabf74f1b7ea59f`

Historical accepted R18 paid behavior testing used this exact system prompt for 16 calls and observed:

- cache hit tokens: 0
- cache miss tokens: 43,579

Therefore the E2 runner/proxy rewrite did not introduce the cache-zero behavior. It is associated with this prompt geometry.

## Official V4 tokenizer measurements

Using DeepSeek's current official `deepseek_v4_tokenizer.zip`:

Current E2:
- system chars: 352
- system + user marker: 143 tokens
- true LCP across lme-a-000/001/002: **158 tokens**
- full local-tokenizer counts: 900 / 1283 / 738
- provider prompt counts: 924 / 1307 / 762
- provider-local delta: constant +24 tokens on all three requests

The constant +24 proves there is no case-dependent token-count drift in the hidden/provider template large enough to explain the cache miss.

Historical R27 cache-positive comparison:
- baseline system + user marker: 214 tokens
- optimized system + user marker: 290 tokens
- optimized warmup -> first measured LCP: **294 tokens**
- observed first measured cache hit: **128 tokens**

## V4.1 cache architecture explanation

DeepSeek V4.1 uses 128-token KV-cache blocks and a 128-token sliding-window (SWA) replay mechanism.

DeepSeek/DeepInfer documentation states:
- block-cache hit lengths are aligned to 128-token blocks;
- under V4.1 SWA bounded replay, if the terminal SWA cache required for a hit is absent, the hit backs off by one 128-token block;
- maximum reusable hit length is constrained by the 128-token SWA window plus extra speculative-backtracking positions.

This predicts the observed results exactly:

Current E2:
- LCP = 158
- floor(158 / 128) = 1 block
- one-block SWA backoff => 0 reusable blocks
- predicted hit = **0**
- observed hit = **0**

Historical cache-positive optimized path:
- LCP = 294
- floor(294 / 128) = 2 blocks
- one-block SWA backoff => 1 reusable block
- predicted hit = **128**
- observed hit = **128**

This is the strongest current root-cause explanation and matches both negative and positive controls.

## Why the old 95% cache target is wrong for LongMemEval

LongMemEval cases are intentionally independent. The only shared material is the short evaluation contract; each case has different retrieved context and question.

Even if the current 158-token prefix could be perfectly cached, the first three prompt lengths are 924 / 1307 / 762 tokens. The theoretical whole-prompt hit fraction would only be around 10–20%, not 95%.

Under the observed V4.1 128-block/SWA behavior, a short 158-token prefix produces 0 billed cache-hit tokens.

A 95% whole-prompt cache-hit target is therefore structurally incompatible with independent LongMemEval cases. It only makes sense for workloads with large repeated/append-only contexts, such as long-lived agent conversations.

## What not to do

Do not pad the system prompt with meaningless tokens merely to cross 256 tokens. Adding ~128 stable tokens to obtain ~128 hit tokens largely cancels the saved miss tokens and can slightly increase total cost.

Do not mutate the already-running E2 pilot prompt to chase cache metrics.

Do not treat 0% cache as a correctness failure; answer/evidence correctness is separate.

## Recommended optimization

For the current E2 pilot:
- keep the frozen prompt unchanged;
- report LongMemEval cache as structurally ineligible/low-value for this short independent-prefix geometry;
- optimize against actual cache-miss tokens and total cost, not a 95% hit-rate target.

For the future confirmatory protocol:
- consider batching multiple independent LongMemEval cases per provider call to amortize the fixed system prompt;
- freeze batch size and failure/recovery semantics before execution;
- do not alter current pilot retrospectively.

For production XiaoYu:
- use append-only/monotonic conversation layouts where request N+1 fully contains request N as a prefix whenever semantically valid;
- place genuinely stable identity/instruction/context material before turn-specific content;
- measure cache miss tokens per useful answer rather than a global percentage.

## Confidence

High.

Evidence combines:
1. current real E2 telemetry,
2. historical same-account/same-model cache-positive controls,
3. historical exact-R18-prompt cache-negative controls,
4. official DeepSeek V4 tokenizer measurements,
5. DeepSeek V4.1 128-token/SWA cache architecture documentation,
6. exact numerical prediction of 0 vs 128 cache-hit outcomes.


## Applied post-launch amendment

Implemented after root-cause confirmation without mutating the pre-first-paid-call freeze:

- runtime policy: `governance/E2_RUNTIME_EFFICIENCY_POLICY.json`
- runtime report: `governance/e2_runtime_efficiency.py`
- LongMemEval legacy 95% cache target: `NOT_APPLICABLE_AS_RUNTIME_GATE`
- primary efficiency metrics: cache-miss tokens/case, total tokens/case, completion tokens/case, CNY/case
- whole-prompt cache-hit rate retained as observational telemetry only
- current pilot prompt mutation/padding for cache: forbidden
- current pilot batching: forbidden
- confirmatory batching design: `plans/E2_CONFIRMATORY_BATCHING_DESIGN_20261028.md`
- production append-only/cache-epoch guidance: `plans/PRODUCTION_APPEND_ONLY_CACHE_LAYOUT_20261028.md`

The original pre-call token-efficiency contract and execution freeze record are intentionally unchanged for auditability.
