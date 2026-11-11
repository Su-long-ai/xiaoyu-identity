# XiaoYu Product Capability Evaluation Matrix v1

Status: FROZEN_UNEXECUTED — 题已组织，本轮没有运行产品、模型或评分器。

## 三层评测定位

- Local120：retrieval fast-lane 开发门，快速筛选检索候选。
- Product180：完整产品能力覆盖，验证长期状态更新、纠正、撤回、冲突、authority、identity/persona、澄清/拒答等。
- External：Stage-1 LoCoMo100 快速外部泛化门；Stage-2 原冻结 LoCoMo200 全量确认。

## Product180 能力家族

| family | 题数 | 目的 |
|---|---:|---|
| single_hop_fact | 10 | 直接事实召回 |
| multi_hop_2 | 10 | 两跳关系组合 |
| multi_hop_3 | 10 | 三跳关系组合 |
| temporal_current_state | 10 | 多次更新后的当前状态 |
| temporal_order_duration | 10 | 时间顺序、时间点与持续时长 |
| correction | 10 | 显式更正覆盖旧值但保留来源 |
| retraction | 10 | 撤回/失效后不得继续当当前事实 |
| conflict_uncertainty | 10 | 同权威冲突时保留不确定性 |
| partial_update_clear | 10 | 字段省略、局部更新与显式清空 |
| collection_count_quantifier | 10 | 集合增删、计数、量词与开放世界 |
| derived_state_invalidation | 10 | 派生状态随底层事实修正/撤回而失效 |
| authority_provenance | 10 | 用户事实、助手推测、第三方来源的权威区分 |
| identity_alias_same_name | 10 | 别名、同名实体与身份绑定 |
| persona_relationship_continuity | 10 | 长期 persona/关系状态及变化 |
| ambiguity_clarification | 10 | 指代不清时请求澄清 |
| no_answer_abstain | 10 | 没有证据时拒绝编造 |
| adversarial_distractor | 10 | 高相似错误日期/人物/属性干扰 |
| multi_intent_composition | 10 | 单次问题组合多个独立答案 |

语言分布：中文 90、英文 54、中英混合 36。每个能力家族固定 5/3/2。

## External 两级门

- Stage-1：100 题，固定比例 30 Multi-hop / 30 Temporal / 10 Open-domain / 30 Single-hop。
- Stage-2：200 题，继续使用原 governance/locomo_blind_200_input_v2.json，不重抽、不改题。
- Stage-1 是 Stage-2 的严格子集；Stage-1 选择只依据类别与固定哈希，不使用 gold answer、evidence 或任何模型成绩。
- 当前只冻结题和层级，不执行测试。
