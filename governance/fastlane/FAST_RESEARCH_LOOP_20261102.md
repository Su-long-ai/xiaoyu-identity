# XiaoYu Fast Research Loop — 2026-11-02

状态：ACTIVE

目标：最快找到真实能力提升，不让治理、审计、文档先于实验。

## 热路径

Research Agent 的默认循环现在是：

component idea
→ 当前 PUBLIC_DEV_PRIMARY（dev240，provider=none）
→ 没优势直接丢弃/继续下一版
→ 有真实本地优势只生成 **Local Candidate**，不是当前 E0
→ 同一个冻结 component SHA 跑 research-visible External Dev：RHELM 全量 + ConvoMem deterministic sample
→ 两个 External Dev gate 都通过才由 `qualify_e0.py` mint **E0-v4 / E0_EXTERNAL_DEV_QUALIFIED**
→ Candidate Freeze
→ LongMemEval frozen external test
→ Independent Audit
→ REALTALK final holdout

TimlMemBench / PersonaMem-v2 是 research-visible specialist dev，可用于诊断与研究，但不是当前 E0-v4 的两个必需 gate。

## 正式本地 Gate

当前 primary dev 是 `research_components/retrieval/local_dev_v3_240.json`：240 题、共享长历史库、context cap=20；其 SHA 与角色由 `governance/fastlane/LOCAL_DEV_FIXTURES.json` 冻结。`local_e2e_cases_v2_120.json` 已降为 `FROZEN_REGRESSION_ONLY`，可做回归但**不能**产生新的 promotion-eligible E0；`local_e2e_cases_smoke18.json` 仍只用于极快 smoke。

当前 fast-lane baseline 的唯一权威记录是 `governance/fastlane/BASELINE.json`；`LOCAL_GATE_BASELINE.json` 只是对应当前 primary dev 的可读指标快照。`run_local_e2e.py` 每次都动态读取 `BASELINE.json`，Research Agent 必须挑战当前 baseline，而不是旧 ProductMemoryBridge / g002。local runner 现在强制 `provider=none`，本地 E0 先证明 retrieval/evidence 增益，不用模型回答器反复烧调用。

独立轻审还必须使用 auditor-only `governance/fastlane/audit_holdout/local_ood_v1_120.json` 做 OOD 泛化门；Research Agent 不得把该 holdout 当开发集读取/调参。

## 研究阶段不再要求

以下动作不再发生在每个微型候选上：

- 不为每个参数/小改动新建 backlog task
- 不为每个失败候选 submit
- 不要求 Lead 逐次批准
- 不要求 Auditor 审失败候选
- 不为纯本地 synthetic/public E2E 建新的治理层
- 不做额外 benchmark 扩题
- 不为已经复用的基础设施重复写 Build-vs-Reuse 文档

三条 FASTRET umbrella lease 内允许连续迭代很多组件。positive local E2E 只形成 Local Candidate；当前 E0 必须再通过 RHELM + ConvoMem External Dev。

## 组件契约

统一入口：

research_components/retrieval/

Research Agent 通常只需要：

1. 复制 candidate_template.py 到自己的 ACTIVE workspace。
2. 修改 prepare()/rank()。
3. 运行：
   py research_components/retrieval/run_local_e2e.py --component <candidate.py> --provider none --promote-e0 --agent-id <agent_id>

共享 runner 强制：

- 输入只能是 ProductMemoryBridge 已 authority/lifecycle 过滤的 active documents
- 输出只能引用输入中的 stable document ID
- context cap 固定 20
- write-side 不可改
- answerer 固定
- 本地 E2E baseline 和 candidate 同题、同 answerer、同 context budget

失败候选只留 workspace 日志即可，不进入正式治理队列。

## Local Candidate 与 E0-v4 条件

Local Candidate 的最低条件：

- 使用当前 `PUBLIC_DEV_PRIMARY`（dev240），不是 legacy120/smoke
- candidate 至少一个核心 retrieval/evidence 指标严格优于当前 baseline
- full-evidence 等核心指标不能回退
- context cap 固定 20
- 无 authority 越界
- component source SHA 被记录

Local Candidate 只表达公开开发集上的离线优势。

当前 E0 使用 schema `xiaoyu-fast-retrieval-e0-v4`，只能由 `governance/evaluation/external_suite/qualify_e0.py` 生成。必须满足：

- 同一个 frozen component SHA；
- 同一个 baseline_id；
- RHELM 完整 External Dev run：provider=none、context cap=20、至少一个核心 evidence metric 严格正增益，且三个核心 metric 均不回退；
- ConvoMem deterministic-sample External Dev run满足同样 gate；
- component bytes 在 qualification 时没有漂移。

E0-v4 仍不是产品 promotion；它只授权进入 Candidate Freeze / frozen external test 流程。

## 审计与历史 Local-OOD

`LIGHT_AUDIT_PAUSE.json` 当前仍控制旧 fast-lane light audit。历史 schema-v2/v3 E0、Local-OOD/light-audit 与 External100/200 结果都可以保留为历史 evidence，但**不再拥有当前 E0-v4 promotion authority**。

当前 E0-v4 不是由 `audit_e0.py` 生成。Research/Mainline 也不得读取 auditor-only Local-OOD。对当前 external-dev-qualified E0，下一正式门是 Candidate Freeze，随后才能访问 LongMemEval frozen test；之后独立 Auditor 再做候选/测试结论审计。

Auditor 对 material P0/P1、current-root closure 和 frozen candidate 仍保持独立；P2/P3 不应制造无限往返。

## External Dev → Frozen Test

当前必需 External Dev：

1. RHELM 全量 1305；
2. ConvoMem deterministic sample。

二者均 research-visible、允许研究迭代、默认 provider=none，但不属于 unseen promotion evidence。只有同一 frozen component SHA 同时通过两者，才可 mint E0-v4。

E0-v4 之后：
- Candidate Freeze；
- LongMemEval frozen external test（Research/Mainline 在 freeze 前不可见）；
- Independent Audit；
- REALTALK final holdout（最终 release intent 才可访问）。

旧 External100/External200/LoCoMo200 属于历史回归证据，不得替代当前 External Dev / frozen-test / final-holdout 路径。



## Local saturation stop-rule（2026-11-02 17:41）

当一个 lane 在 current PUBLIC_DEV_PRIMARY 上达到 100% correct + 100% full-evidence，且 legacy regression 也保持 100%，该 lane 视为 **LOCAL_SATURATED**：停止继续为同一公开开发集制造 vN+1 微调版本。下一步必须转到 research-visible external development distribution（默认 RHELM primary；随后按适配性看 ConvoMem / TimlMemBench / PersonaMem-v2），仍优先 provider-free retrieval/evidence scoring。

当前触发者：C-v21 `rare_bridge_locality_v21`，dev240=240/240、full-evidence=225/225；legacy120=120/120、full-evidence=110/110。该结果只证明 local saturation，不允许自动 baseline upgrade、light-audit PASS 或 promotion。尤其 v21 仍含开发集形状相关的 typed/path lexical heuristics；必须看真实 external-dev transfer。

## 当前 DEV-only 组合线索（2026-11-02 17:29）

Lead 在**已公开的 dev240** 上做了一次只读/零 provider 的组合可行性验证：固定使用 exact C-v16（多跳强）与 exact D-v17（跨语言强），仅按 query 是否包含 CJK 字符进行组件路由；完整实际 runner 得到 228/240=95.0%，full-evidence 213/225=94.67%。记录位于 `governance/lead_workspaces/fastret_cd_script_router_20261102_1729`，wrapper SHA256=`9d777350714713c23f41faefa65df752b9070e74c67ac29280d62d0809b54dea`。

这条规则是在观察 dev240 family gap 后提出，**因此只能作为 DEV_EXPOSED_COMPOSITION_FEASIBILITY，不是 Local Candidate/E0、不是 OOD/generalization，也不能跳过 RHELM + ConvoMem External Dev**。Research Agent 可把它当“互补机制存在”的线索，优先寻找更通用、可解释且不依赖开发集家族形状的统一 selector/composition；不得为验证此线索读取 auditor-only OOD。

## Baseline 升级

当前 baseline 记录在：

`governance/fastlane/BASELINE.json`

Local Dev 100% 或历史 external200 高分都**不能**自动升级 baseline。当前 baseline 升级至少要求：

- 同一 frozen component 已通过 RHELM + ConvoMem External Dev 并形成 E0-v4；
- Candidate Freeze 完成；
- frozen external test 与独立审计没有 material regression；
- 无 authority/safety/context-budget 退化。

最终 baseline 变更仍由现有 fastlane baseline upgrade 记录负责，不能靠手改 `BASELINE.json` 跳过 gate。

## Mainline

Mainline Agent 不被 retrieval fast lane 占用。

Mainline 继续研究/整合其它真实产品瓶颈；已观察 material P0/P1 仍可抢占。
纯 promotion-evidence hygiene、文档整理、治理扩展默认不占 mainline，除非它确实阻塞产品。

## V21 Auditor generalization falsifier（2026-11-02 18:10）

Independent portfolio Auditor confirmed that `rare_bridge_locality_v21` is genuinely 240/240 on exposed Dev240, but its generic path-length/generalization interpretation is **falsified** by a prospectively frozen synthetic minimal contrast: when true 3-hop questions use an answer type that drives v21 to its 2-hop lexical branch, candidate full evidence is 1/6, identical to baseline 1/6. This is not the paused official OOD and does not authorize External Dev qualification, Candidate Freeze, or frozen-test access.

Therefore C-v21 is retained only as public-dev evidence. **Stop Dev240 v22/v23 lexical/path-shape tuning.** The existing C lease may close its bounded work; any successor must transfer to research-visible external dev (RHELM first) or use a materially different, query-structural mechanism that does not infer path depth from exposed answer-type words. Hidden auditor holdout remains unreadable to Research/Mainline.
