## POST_EXTERNAL_E0_OVERRIDE_20261102

This section supersedes every older Local->E0->light-audit/LoCoMo promotion flow below.

Canonical retrieval research/promotion flow:
Local regression -> Local Candidate -> RHELM + ConvoMem External Dev -> E0 -> Candidate Freeze -> LongMemEval frozen test -> Independent Audit -> REALTALK final holdout -> product RC.

Rules:
- Local Dev v3 advantage may create a Local Candidate only.
- E0 is external-development-qualified evidence, not a local signal.
- E0 requires the exact same component SHA and baseline to pass full provider-free RHELM 1305 and deterministic ConvoMem 4089 gates defined in governance/evaluation/external_suite/EXTERNAL_DEV_E0_GATE_V1.json.
- Historical E0 v3, Local-OOD120 and FASTRET light-audit records remain historical; they cannot authorize current promotion.
- LoCoMo is historical regression only.
- DeepSeek is not required for Local Candidate or E0 minting; end-to-end model confirmation is a later layer.

## EXTERNAL_REAL_DISTRIBUTION_OVERRIDE_20261102

This section supersedes the older Local120 -> LoCoMo fast-path text below.

Canonical benchmark routing is defined by:
- governance/evaluation/external_suite/EXTERNAL_BENCHMARK_MATRIX_V1.json
- governance/evaluation/external_suite/EXTERNAL_BENCHMARK_POLICY_V1.md

Active research path:
Local v2/v3 regression -> RHELM primary external Dev -> ConvoMem deterministic scale Dev -> TimlMemBench / PersonaMem-v2 specialist Dev as relevant.

Promotion path:
candidate/protocol freeze -> LongMemEval frozen external test -> independent audit -> REALTALK final holdout for release-level confirmation.

Rules:
- Local synthetic data is regression/unit evidence, not primary external capability evidence.
- RHELM/ConvoMem/TimlMemBench/PersonaMem-v2 are intentionally consumable development data; research may inspect their gold/failures and tune against them, but their scores are not unseen-generalization claims.
- LongMemEval is research-invisible frozen test; no case-specific tuning after exposure.
- REALTALK is research-invisible final holdout and is not a routine benchmark.
- LoCoMo is historical regression only because this project has already consumed it repeatedly.
- Presence on local disk does not grant access; benchmark_access.py and the matrix research_visible flag are authoritative.
- Retrieval/evidence/state evaluation is provider-free by default. Paid answerer/judge is later confirmation only.

## Public Dev v3 ? 2026-11-02

- Default local retrieval DEV is research_components/retrieval/local_dev_v3_240.json.
- It contains 240 cases across 10 families: single-hop semantic, varied 2-hop, varied 3-hop, current temporal state, temporal order, alias/identity, entity collision, semantic paraphrase, Chinese/mixed-language, and abstention.
- It intentionally mixes single-token and two-token entities and multiple relation surface forms.
- Local v2_120 is frozen regression-only and remains available for backward compatibility; its score is not promotion/generalization evidence.
- Dev v3 is public to researchers, so it is still not a hidden benchmark. Generalization still requires the auditor-only Local-OOD120 gate.

# XiaoYu Evaluation Policy v1

Status: FROZEN_UNEXECUTED
Date: 2026-11-02

本文件是当前评测题层的 canonical 索引。此次变更只组织、冻结题库与层级；没有运行产品、模型、Judge，也没有产生新的 benchmark 成绩。

## Local provider policy — 2026-11-02

Owner decision: all local/synthetic evaluation suites are provider-free.

- Local120 MUST run with provider=none only.
- Product180 MUST run provider-free as well.
- Local E0 qualification is based on frozen offline retrieval/evidence metrics, not a model answerer.
- Light audit reproduces the same offline retrieval/evidence advantage with provider=none.
- DeepSeek/model calls are permitted only after a candidate reaches the external benchmark stages (External100, then External200).
- Existing historical local runs that used DeepSeek remain historical evidence only; pending candidates must be requalified under the new offline-only local policy before any new external promotion path.

## Local OOD generalization gate ? 2026-11-02

- Local120 is a development/regression set. A high Local120 score is not external-generalization evidence.
- Positive E0 must still reproduce on Local120, then pass the independent auditor-only governance/fastlane/audit_holdout/local_ood_v1_120.json gate.
- OOD fixture SHA256: 27b9752076574a51a22668a6bb160498a28021b7b80a813b5984943b9c266028.
- Frozen OOD margin: candidate must beat the current baseline by at least 3/120 offline cases with nonnegative full-evidence delta.
- Research/Mainline agents must not inspect or tune against governance/fastlane/audit_holdout/; only Independent Auditor/Lead may use it for gating.
- OOD uses no model provider and contains no external benchmark content.

External100 causal-comparison rule:
- if candidate retrieval is the same ordered source-ID list as the sealed baseline for a question, reuse the sealed baseline answer and its judgement;
- call the candidate answerer/judge only on questions whose retrieval actually changed;
- future Stage1 uses V2 frozen rule requiring at least +1/100 answer accuracy, nonnegative full-evidence delta, at least one changed retrieval row, and zero material authority regressions.

Current fast path:
Dev Local120 -> E0 -> dev reproduction -> Local-OOD120 -> External100 -> External200 -> promotion

## 1. Local retrieval gate

- 题库：research_components/retrieval/local_e2e_cases_v2_120.json
- 120 题，共享长历史，context cap=20。
- 作用：retrieval fast-lane 快速开发筛选。
- 旧 18 题只作 smoke，不作为正式能力门。

## 2. Product capability suite

- 题库：governance/evaluation/PRODUCT_CAPABILITY_SUITE_V1_180.json
- 180 题，18 个能力家族，每类 10 题。
- 语言：中文 90、英文 54、中英混合 36。
- 作用：完整产品能力验证，不只测 retrieval。
- 当前状态：FROZEN_UNEXECUTED。

能力范围包括：
single-hop、2-hop、3-hop、当前状态、时间顺序/持续时长、correction、retraction、conflict/uncertainty、partial update/CLEAR、collection/count/quantifier、derived-state invalidation、authority/provenance、identity/alias/same-name、persona/relationship continuity、ambiguity clarification、no-answer abstain、adversarial distractor、multi-intent composition。

## 3. External two-stage evaluation

Canonical manifest:
governance/evaluation/EXTERNAL_EVAL_TIERS_V1.json

Stage-1:
- governance/evaluation/locomo_stage1_100_input_v1.json
- 100 题。
- 30 Multi-hop / 30 Temporal / 10 Open-domain / 30 Single-hop。
- 是 Stage-2 200 的严格固定子集。
- 各 conversation 尽量保持原 200 的约一半。
- 选题只使用类别与固定哈希，不使用 answer、evidence 或任何模型成绩。
- 只作低成本外部筛选，不允许 baseline promotion。

Stage-2:
- governance/locomo_blind_200_input_v2.json
- 原冻结 200 题保持不变。
- 60 Multi-hop / 60 Temporal / 20 Open-domain / 60 Single-hop。
- 只有 Stage-2 可以用于正式 external breakthrough / baseline promotion。

固定顺序：
Local120 -> positive E0 -> light audit -> External Stage-1 100 -> External Stage-2 200 -> promotion decision

Stage-1 的具体通过阈值必须在第一次实际运行之前另行冻结，不能看到结果后再定；本次没有设定或运行阈值。

## 4. Data-boundary rule

Product180 是内部 synthetic product-capability suite，不允许把其成绩声称为外部泛化证据。
External100/200 不允许 Research Agent 根据 blind ID、gold、evidence、既有 outcome 或 failure diagnostics 调组件。
Stage-1 结果出来后禁止重抽 100 题。
Stage-2 原 200 题禁止改题或替换 membership。
