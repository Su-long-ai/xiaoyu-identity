## Fast-Lane E0 轻审计例外（2026-11-02）

`governance/fastlane/e0_candidates/` 下的 retrieval E0 不走完整 promotion audit。审计只需独立复现同一 local E2E 优势，核对 component SHA、matched baseline/answerer、context cap=20，以及无 external200 gold/case-ID 特判。通过即允许 external200。除 material P0/P1 外，P2/P3、治理/包装/文档问题不得阻断此轻审计。

# 审计实质性与反过度治理规范 · V2（2026-10-26）

> 原则：**只阻塞足以改变科学结论或安全边界的实际问题；科研继续，审计异步。**
> 本文件适用于小鱼 E1 候选。E2 正式科学和 E3 产品门当前没有启用；本规范不能绕过其未来的独立严格验收。

## 判断矩阵

| 等级 | 适用 | 阻塞效果 |
| --- | --- | --- |
| P0 | 已观察到的隐私泄漏、记忆污染导致越权、严重身份事实伪造等 | 只能拒绝/要求修复 **此 E1 候选**；发现真实全局事故应另行报告 owner |
| P1 | 已观察到的错误指标、数据泄漏、无法复现、影响研究结论的实质性回归 | 只能拒绝/要求修复 **此 E1 候选** |
| P2 | 可补充的边界测试、局限说明、非关键问题 | **非阻塞**，候选可被 ACCEPT_E1 |
| P3 | 排版、代码风格、命名及其他无实质影响的意见 | **非阻塞**，候选可被 ACCEPT_E1 |

`ACCEPT_E1` 是**候选材料审核通过**，并不代表正式 E2 的科学结论，更不表示已经采纳为小鱼产品。

## P0/P1 证据负担

所有阻塞性审计发现必须具备：
- `observed: true`（明确声称已观察，而不是纯猜测）；
- `issue`（具体缺陷）、`impact`（改变了哪个真实能力指标、隐私或安全结果）；
- `reproduction`（精确复现步骤）；
- `evidence`（指出候选工件、数据或日志里的具体证据）；
- `fix`（最小修复建议）。

必须在一个审阅周期尽量一次性提交主要问题；每份审计最多 8 项，不得因排版风格开启另一轮实质阻塞。**机器只校验字段与流程，不能证明审计描述本身属实；最终仍需独立核对证据。**

如果 P0/P1 证据不足，先记录为 P2 风险或要求另立实验验证，不能绕过该规则拒绝已有候选；如果发现真实安全事故，立即由 owner 走独立应急流程，而不是把整个科研队列暂停当作万能响应。

## 合法决策

- 有且仅有 P2/P3（或无问题）→ `ACCEPT_E1`；所有建议随审阅记录保留；
- 至少一项证据完整、可复现、已观察的 P0/P1 → `REJECT` 或 `NEEDS_WORK`，只影响被审核的候选；
- P2/P3 拒绝、没有具体材料的 P0/P1 拒绝、同一候选二次反复审阅都被控制程序拒绝；
- 有未经审计的候选不影响科研 Agent 自动继续研究（真正 Agent 调度尚未开发）；独立科研租约与审阅队列没有全局等待条件。

## 审计 JSON 范例

附加到 `governance/control.py review ... --findings-json` 参数的内容是 JSON 数组：

```json
[
  {
    "severity": "P1",
    "observed": true,
    "issue": "固定测试的 holdout 样本进入检索索引",
    "impact": "污染准确率评估，不能支持报告的检索增益",
    "reproduction": "使用固定种子重建索引并查验 holdout ID 在索引中的出现",
    "evidence": "候选工作区 index_ids.txt 中存在 holdout ID 样本",
    "fix": "重新仅从训练集构建索引并重复评估"
  },
  {
    "severity": "P3",
    "issue": "结果文档里存在不统一的变量命名",
    "impact": "不影响模型成绩和数据可复验，只增加阅读成本",
    "fix": "在后续整理时统一术语"
  }
]
```

如果只是 P3，审计不能因为这条而 `REJECT`；如果有 P1，不能强行 `ACCEPT_E1`。

## 命令和监控

```powershell
cd D:\dsh-fish
py -3.11 governance\control.py status
py -3.11 governance\control.py audit-stats
py -3.11 governance\control.py queue
py -3.11 -m unittest discover -s governance -p "test_*.py" -v
```

监控指标：已审核数、通过/退回数量、严重问题数量、非阻塞建议数量、平均候选等待时间和最旧待审时间。**这些只说明流程吞吐；目前未建立误拦截申诉/推翻统计，所以不能宣称已测得误拦截率。**

## 程序限制与后续改进

- 操作 Agent ID 不是真实密码学身份验证；JSON 中的“已观察”也只是人工声明，语义真假仍需检查。
- 治理 CLI 不会自动启动 Agent、限制其他进程的支付 API，也不会停止现有操作系统进程。
- 真正的身份数据库、完整删记忆能力及 E2/E3 发布需要不同层级的产品安全审计。
- 如果审计积压，将优先改变候选选择和审核优先级，不通过放松高风险安全门解决。

**下个主要开发任务不是继续强化审批，而是跑合成中文记忆基线与开源代码对照。**

## 科学结论与 Promotion 证据有效性分离（2026-10-31 强制）

从本规则生效起，必须把两个问题分开回答：

1. 科学结果是什么：假设在实际观测中是 POSITIVE / NEGATIVE / INCONCLUSIVE / NOT_TESTED。
2. 这批证据能否用于 promotion：证据是 VALID / INVALID_ADMINISTRATIVE / INCOMPLETE / NOT_APPLICABLE。

硬规则：
- token 上限、预算上限、budget scope、调用 provenance、预注册行政字段等违规，默认只使 promotion evidence 无效，不得单独把科研方向判成 NONPASS。
- NONPASS 必须存在已经观察到、可复现、直接命中预先 falsifier 的科学失败；不能把超过调用上限当作科学失败。
- LEAD_READY 必须同时满足：科学结果 POSITIVE、promotion evidence VALID、没有已观察科学 falsifier。
- 科学结果正面但 promotion evidence 因行政原因无效：保留为 EVIDENCE_ONLY / supporting evidence，并在价值足够时按正确 scope/cap 重新复验。
- 实际测得的资源成本可以作为工程结论的一部分，但只有在成本或效率本来就是预先冻结的评价指标时才能用于淘汰工程方案；单纯撞到行政 cap 不等于方案科学上无效。
- 后续更干净的科学实验可以覆盖早先结果；必须明确写清后来因科学证据淘汰，不能倒写成早先因流程违规淘汰。

R37 是历史校正样例：其 32/32 x2 是正面的实验观察，但当次 promotion 证据因 scope 与 25k raw-token cap 违规而无效；该违规本身不否定 whole-message semantic extraction。其更强的 lossless event-sequence 主张后来由合规 R40 的 29/32 x2 重复遗漏所科学证伪。

## Safety Boundary Stratification（2026-11-01）

权威记录：governance\SAFETY_BOUNDARY_STRATIFICATION_20261101.json。

审计安全问题时必须区分“上游预测错”和“权威边界真的被突破”。语义归属、关系分类、候选生成等 L0 非权威组件允许存在可测的非零预测误差；只要 deterministic L1 gate 将其拦截、降级为澄清/不写入，且没有形成 L2 durable authoritative mutation/exposure，就不能仅凭该 L0 错误给集成候选记 P0/P1 产品安全 blocker。

这不改变科学 falsifier：如果某个组件的预注册指标要求更高，它仍可科学 NEGATIVE。区别在于，组件 exact hypothesis 失败不自动推出整个组合架构或产品候选不安全。

P0/P1 安全 finding 应明确给出 boundary_crossing：错误如何从 L0 穿过 principal / ambiguity / target / generation / lifecycle / mutation authorization，最终形成 material authoritative effect。无法证明 crossing、且 final state fail-closed 时，默认按组件质量问题或 P2 风险处理。

真正的 L1/L2 未授权写入、错误 durable target mutation、错误 authoritative exposure 仍保持零容忍。

## Multidimensional Gate Stratification（2026-11-01 强制）

读取 governance\GOVERNANCE_OVERSTRICT_REPAIR_20261101.json。

从本规则生效后的新 lease 开始，LEAD_READY / NONPASS manifest 必须包含 gate_stratification，至少分别记录：
- primary_blocker_class
- implementation_outcome
- safety_outcome
- release_outcome
- administrative_outcome
- environment_outcome

不得再把不同维度压成一个 NEGATIVE：
- 科学能力被证伪：SCIENTIFIC，scientific_outcome=NEGATIVE。
- 能力有效但实现 bug / composition 失败：IMPLEMENTATION_CORRECTNESS；科学结论可以保持 POSITIVE/INCONCLUSIVE/NOT_TESTED。
- 能力有效但性能不达产品门：IMPLEMENTATION_PERFORMANCE；科学结论可以保持 POSITIVE，scientific_falsifier_observed=false。
- L1/L2 权威边界真实穿透：SAFETY_BOUNDARY。
- 只在 release/composition 失败：RELEASE_INTEGRATION。
- scope/authorization/registration 或依赖/权重/环境缺失：不得仅因此提交 NONPASS；使用 EVIDENCE_ONLY / NOT_TESTED 并记录 administrative/environment blocker。

性能门默认是 implementation/promotion gate，不是 scientific gate。只有在执行前明确冻结 SCIENTIFIC_COST_HYPOTHESIS 时，性能本身才可证伪科学假设。禁止 rerun-until-pass；优先使用 order-balanced repeated timing 与 robust aggregate，而不是单个噪声 block 外推整个 capability。

已知依赖、模型权重、环境变量或命令在正式 execution freeze 前使用 governance\runtime_preflight.py 做本地预检；缺失依赖 = NOT_TESTED，不是科学失败。


对新结果的 material finding 也应指出影响所在维度。P0/P1 仍要求真实 observed material impact；单纯 admin/env 未执行不是候选的科学 P1，性能未达实现门也不自动否定 underlying capability。

