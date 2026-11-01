# XiaoYu Capability Sprint — Retrieval Completeness（2026-11-02）

状态：ACTIVE / 当前项目方向覆盖令  
作用域：小鱼下一代能力原型的 read-side；在 Lead 明确解除前，优先级高于常规 P2 研究与非关键治理扩展。

## 1. 决策依据

固定 LoCoMo 200 题外部评测已经定位主要瓶颈：

- 总体：89/200 = 44.50%
- 主评测 180 题（1/2/4）：87/180 = 48.33%
- Multi-hop：24/60 = 40.00%
- Temporal：26/60 = 43.33%
- Open-domain：2/20 = 10.00%
- Single-hop：37/60 = 61.67%
- Answer provider failure：0/200
- Judge failure：0/200
- 完整 gold evidence 被召回：35%
- 完整 evidence 条件下准确率：88.57%
- evidence 不完整时准确率：20.77%
- Single-hop 完整 evidence 条件下：97.06%
- Multi-hop 完整 evidence 召回率：10%

因此当前主瓶颈被定位为：**read-side retrieval completeness，尤其是 multi-hop 的证据找全能力**。

当前不是 answerer、B1/B3 deterministic memory core 或 write-side 的主问题。Multi-hop answerer 是否仍有第二层瓶颈，必须等 retrieval completeness 显著提升后再判断。

## 2. 当前唯一 P0 能力目标

把长期历史中的必要证据尽可能完整地找进上下文，然后再让冻结 answerer 回答。

研发链路按以下顺序收敛：

1. candidate generation
2. lexical / semantic / facet retrieval
3. multi-query / query decomposition
4. evidence-set union / dedup
5. evidence-complete rerank / selection
6. 仅在上述部分显著改善后，再判断 multi-hop reasoning 是否成为新瓶颈

最终 QA accuracy 仍记录，但本 sprint 的第一主指标改为 **gold evidence completeness**。

## 3. 冻结项

本 sprint 期间默认冻结：

- B1/B3 deterministic memory core
- write-side memory update / correction / retraction 主逻辑
- answerer prompt
- answerer / judge 配置
- 固定 200 道 LoCoMo item ID 与类别比例
- 已有产品型 E2E 链路
- 非必要治理机制扩展

禁止为了分数：

- 扩大 LoCoMo 题量
- 换题或按结果挑题
- 逐题人工写 query / rule
- 在 candidate 运行前读取当前题 gold evidence
- 调整 answer prompt 来掩盖 retrieval 缺口
- 引入新的 vector DB / graph DB / ANN 基础设施，除非已有复用组件被前瞻反例证明不足

gold 只允许在候选输出封存后进入独立 scorer / auditor，用于计算 evidence completeness 和 failure taxonomy。

## 4. 冲刺指标

Baseline：

- evidence completeness：35%
- Multi-hop completeness：10%
- final QA：44.50%

阶段目标：

- Stage A：overall completeness >= 50%，Multi-hop >= 30%
- Stage B：overall completeness >= 60%，Multi-hop >= 45%
- 同时要求 frozen-answerer final QA 对 baseline 有明确正增益

这些是能力冲刺目标，不是为了达标而允许后验调参。每个候选必须报告：

- overall evidence completeness
- Multi-hop / Temporal / Single-hop completeness
- final QA
- recall@candidate pool
- selector loss：candidate pool 已包含完整 gold，但最终 context 丢失的比例
- 每题候选数 / context token 成本
- 与 baseline 的 delta

## 5. 当前研究分工

Research Engineer A 优先：
- candidate generation
- lexical + semantic + entity/facet union
- candidate recall ceiling

Research Engineer B 优先：
- multi-query / query decomposition
- evidence-set construction
- evidence-complete reranking / selection

Independent Auditor：
- 固定 200 item ID
- 检查 gold 泄漏、后验调参、题目扩容、answerer 漂移
- 独立复算 completeness 与 final QA
- 区分 candidate-generation failure 与 selector failure

Lead：
- 只消费会改变 retrieval 方向的 E0/E1 证据
- 暂停非关键旁支消费
- 不因为审计排队让 retrieval 主线停工

## 6. 自动派工覆盖

在本 sprint ACTIVE 期间：

- 自动派工只选择 plan = `CAPABILITY_RETRIEVAL_SPRINT`
- 原 P2 R24/R25/R23 保留，不删除，但不自动抢占 Research Engineer 槽位
- 只有已观察到的 P0/P1 产品安全或科学有效性事故可以临时抢占
- P2/P3 建议、治理整理、文档清理不得抢占 capability sprint

## 7. 退出条件

只有以下情况之一成立，Lead 才改变当前方向：

1. retrieval completeness 已进入明显高位，且 final QA 不再随 completeness 提升，证明 answerer / reasoning 成为新主瓶颈；
2. 两条实质不同的 retrieval 路线都不能稳定提高 completeness；
3. 独立审计证明当前诊断来自 gold 泄漏、评测实现错误或不可复现；
4. Owner 明确改变产品目标。

在退出前，默认回答“下一步做什么”的答案应是：**继续提高 read-side evidence completeness，优先 Multi-hop。**
