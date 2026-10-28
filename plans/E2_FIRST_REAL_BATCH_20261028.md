# E2 第一批真实 Paid Pilot 数据 — 2026-10-28

状态：**FIRST_REAL_BATCH_COMPLETE / NONPROMOTIONAL**

本记录只汇总 E2 pilot 第一批两笔真实 DeepSeek benchmark-phase paid call。它不构成 E2 科学验收，也不触碰 confirmatory。

## 执行前门

- P1 / P2 已完成既有 closeout。
- E2 scientific protocol 保持 FROZEN_BEFORE_EXECUTION。
- LongMemEval-S pilot split 保持冻结。
- LongMemEval context 由冻结的 `governance/e2_longmemeval_context.py` 自动重建：
  - SQLite FTS5 relevance
  - history mode
  - user -> user_history
  - assistant -> conversation_history
  - top_k = 7
  - rarest-term max_posting = 128
  - gold / answer fields不进入 paid payload
- HaluMem extraction HOLD：有限 slot P1 extractor 与 open-domain HaluMem 语义不匹配。
- HaluMem QA HOLD：依赖有效的 open-domain HaluMem ingest/update pipeline。
- 全量治理回归：170 / 170 PASS。
- 首笔调用前 benchmark paid calls = 0，benchmark tokens = 0。
- 两笔均在北京 off-peak 执行。

## 第一批真实调用

### lme-a-000

Question:
`What degree did I graduate with?`

公开 benchmark gold:
`Business Administration`

DeepSeek 返回:
- status: resolved
- answer: `Business Administration`
- evidence: `lme:0:51:answer_280352e9:4`
- evidence authority: `user_history`

校验:
- answer exact: PASS
- evidence id in frozen context: PASS
- source authority: PASS

Provider:
- call_id: `api-d8cab3eb6022455d8bb1675392ca1797`
- prompt_tokens: 924
- completion_tokens: 44
- total: 968
- cache_hit_tokens: 0
- cache_miss_tokens: 924

### lme-a-001

Question:
`How long is my daily commute to work?`

公开 benchmark gold:
`45 minutes each way`

DeepSeek 返回:
- status: resolved
- answer: `45 minutes each way`
- evidence: `lme:1:7:answer_40a90d51:8`
- evidence authority: `user_history`

这个 case 的 frozen context 同时含有 assistant-origin 的错误复述 `an hour each way`，但其 authority 为 `conversation_history`。模型没有被该 assistant echo 带偏，而是选择了用户原始证据。

校验:
- answer exact: PASS
- evidence id in frozen context: PASS
- source authority: PASS
- assistant-origin authority laundering: 未观察到

Provider:
- call_id: `api-e595ec8f23db4a51826f90a51ab5bf7f`
- prompt_tokens: 1307
- completion_tokens: 47
- total: 1354
- cache_hit_tokens: 0
- cache_miss_tokens: 1307

## 第一批聚合

- paid calls: **2**
- COMMITTED: **2 / 2**
- answer exact: **2 / 2**
- evidence valid: **2 / 2**
- evidence authority = user_history: **2 / 2**
- structural/provider failures: **0**
- UNKNOWN / RESERVED: **0**
- prompt tokens: **2231**
- completion tokens: **91**
- total raw tokens: **2322**
- E2 pilot hard cap used: **2322 / 1,000,000 = 0.2322%**
- E2 pilot remaining: **997,678**
- cache hit tokens: **0**
- cache miss tokens: **2231**
- observed whole-prompt cache hit rate: **0%**
- measured off-peak cost: **¥0.002595**

## 最重要的第一批发现

1. **当前 LongMemEval source-aware P1 路径是真正可运行的。**
   两个真实公开 benchmark case 都完成了 retrieval -> formal authority context -> DeepSeek answer -> durable receipt。

2. **初始 authority 行为正确。**
   第二个 case 是一个有价值的反例：assistant 错误复述没有覆盖用户原始事实。

3. **缓存目标当前没有得到支持。**
   两笔请求的 invariant prefix SHA 完全相同，但 provider telemetry 均报告 0 cache-hit token。第一批的 whole-prompt hit rate = 0%，因此此前 >=95% stable-prefix cache 目标目前不能宣称达成。
   这可能来自 provider cache 的最小前缀长度/粒度或当前 prefix 太短；需要后续专门验证，不能用扩大 batch 来掩盖。

4. **HaluMem 不应现在付费执行。**
   当前 finite-slot extractor 与 open-domain HaluMem 不匹配，已在 runner 和 provider 两层 HOLD。没有为获取“看起来像真实数据”的结果而运行科学语义错误的 pipeline。

## 当前结论

第一批真实 E2 pilot 数据已经到达，且 LongMemEval 两个 warm-up case 均正确、receipt 完整、authority/evidence 校验通过。

但这是 nonpromotional pilot 的 **n=2 工程样本**，不支持 E2 科学结论。当前最明确的新问题是 cache reuse 仍为 0%，下一阶段应先诊断缓存前缀可缓存性，再扩大 LongMemEval pilot，而不是立即跑 HaluMem 或 confirmatory。


## Post-batch cache policy update

The initial >=95% stable-prefix cache objective is no longer used as a LongMemEval runtime gate. Root-cause analysis showed the independent-case prompt geometry is structurally low-cache-reuse under the observed DeepSeek V4.1 128-token block/SWA behavior.

Current runtime efficiency reporting therefore uses miss tokens/case, total tokens/case and CNY/case as primary metrics. The scientific protocol, pilot prompt and first-batch results are unchanged.
