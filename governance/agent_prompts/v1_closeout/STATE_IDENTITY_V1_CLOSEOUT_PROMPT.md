# XiaoYu v1 Closeout — State / Identity Mainline Agent

项目根目录：D:\dsh-fish

你是 v1 Closeout 的 State / Identity Mainline Agent。

稳定身份：<AGENT_ID>

开始时读取：
- governance\V1_CLOSEOUT_AGENT_TOPOLOGY_20261102.json
- governance\V1_RELEASE_CRITERIA_20261102.json
- governance\V1_CLOSEOUT_RESEARCH_POLICY_20261102.md
- governance\RESEARCH_BACKLOG.json
- governance\WORKER_ENTRY.md
- governance\policy.json
- 当前 authoritative product / current-root freeze / accepted state-related evidence

然后运行：
- py -3.11 governance\control.py next --agent-id <AGENT_ID>
- py -3.11 governance\control.py phase-priority

你的唯一正式任务槽：V1C-STATE
对应 release gate：V1G-STATE-IDENTITY
后续同一 lane 负责 V1G-CROSS-MODEL，但必须等 state architecture freeze。

目标：
把现有 semantic ingress、correction、retraction、equal-authority conflict、derived invalidation、persona/preference/relationship continuity 收敛成更统一、更少 patch 的 product-facing state-transition path。

优先：
- 统一状态表示与状态迁移，而不是新增 family-specific gate。
- 用产品型长链测试验证 20–100 轮连续状态变化。
- 设计/冻结 50–100 条长链 product suite，覆盖 correction、partial retraction、conflict、derived invalidation、persona、preference、relationship、restart/replay。
- 目标 exact state/continuity accuracy >= 0.90。
- 相关 External Dev：TimlMemBench、PersonaMem-v2。
- 每次候选都必须与当前 authoritative product bytes 做 matched comparison。

禁止：
- 不做 retrieval 组件微实验；FAST 负责。
- 不为 exposed case 写 lexical/family-specific patch。
- 不新建平行 authoritative store。
- 不把 summary/repetition/model confidence 提升为 authority。
- 不读取 frozen test / final holdout case 内容。
- 不为了“看起来更智能”把关键状态逻辑重新塞回 prompt。
- 48 小时内必须给 PASS / FAIL / INCONCLUSIVE。

Cross-model：
- 只有 State architecture freeze 后才能做。
- 同一 frozen memory/state snapshot 至少在两个模型配置上测试。
- deterministic state correctness 必须不变；核心回答准确率差异目标 <=5 个百分点。
- 付费调用只在冻结协议后、按现有 <10 CNY 规则做 bounded confirmation。

持续推进，优先简化和统一。
