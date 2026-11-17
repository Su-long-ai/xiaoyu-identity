# XiaoYu 1.0 · 2026-11-18 临时决策包

> 私有仓库临时存档。  
> 目的：把 2026-11-18 已确认的 XiaoYu 产品状态、1.0 范围、外部项目调研和收口决策固化下来，避免继续扩 scope 时丢失主线。
>
> 本包整理时，本地 Operator 已断开，因此“当前状态”使用断开前刚刚完成的实测/回归与研究 authority；外部部分来自公开仓库、论文和项目文档的当日调查。

## 一句话目标

**XiaoYu 是一个长期连续存在的 AI 伴侣：拥有稳定身份、可信长期记忆、跨入口连续性、环境感知、有限主动性和可验证的能力提升。**

核心不是“再造一个聊天机器人框架”，而是保证：

1. 今天、明天、换模型、换入口以后仍然是同一个“小鱼”；
2. 共同经历可追溯，不把模型猜测或开发者设定冒充真实记忆；
3. 长期记忆能写、能取、能冲突处理、能降权、能跨年维护；
4. Desktop / QQ / 后续 Vision、Voice、B站等都只是 surface/capability，共享一个 Core；
5. 能力提升必须通过 frozen / prospective / outcome-first 评测证明，而不是看 retrieval 指标或开发集感觉；
6. 主动性必须有节奏、安静时段、打扰价值和显式边界，不能变成刷屏机器人。

## 文档

- [MASTER_PLAN.md](MASTER_PLAN.md)  
  XiaoYu 1.0 的目标、当前状态、缺口、优先级、架构与 DONE 标准。

- [EXTERNAL_SURVEY.md](EXTERNAL_SURVEY.md)  
  外部调查：SurfCore、dsh-see-now、Open-LLM-VTuber、Letta、LoCoMo、MemoryAgentBench、OSWorld，以及它们对 XiaoYu 的直接启示。

- [VALIDATION_AND_ACCEPTANCE_PLAN.md](VALIDATION_AND_ACCEPTANCE_PLAN.md)  
  验收计划：为 Identity、Memory、Proactivity、Vision、Voice、权限、Skill、恢复和资源定义可量化 pass/fail gate。

- [LONG_TERM_HARDENING_AND_OPERATIONS.md](LONG_TERM_HARDENING_AND_OPERATIONS.md)  
  长期工程化：密钥、加密、备份、迁移、更新验签、供应链、故障恢复、资源预算和隐私运维。

- [IMPLEMENTATION_SELECTION_MATRIX.md](IMPLEMENTATION_SELECTION_MATRIX.md)  
  实现选型矩阵：逐模块决定现在采用什么、1.x 候选、为什么不采用其它重型方案。

- [MULTIDIMENSIONAL_SATURATION_SURVEY.md](MULTIDIMENSIONAL_SATURATION_SURVEY.md)  
  多维度饱和调查：身份、记忆、偏好、主动性、视觉、权限、技能、跨端、隐私、安全、关系、运维、成本与最终产品分期。

- [FINAL_PRODUCT_CAPABILITIES_RESEARCH.md](FINAL_PRODUCT_CAPABILITIES_RESEARCH.md)  
  饱和外部调查：长期身份、双时间记忆、偏好/主动性、视觉/Computer Use、程序性技能、授权、安全与最终产品能力地图。

- [DECISIONS.md](DECISIONS.md)  
  设计裁决：哪些直接吸收、哪些只参考、哪些明确不做；同时给出 11 月底收口规则。

## 当前最重要的四件事

1. **DECADE100 收口**：all100 semantic substrate 已 100/100 PASS，继续 runtime payload + aggregate cost preflight，然后完成正式验证并裁决。
2. **Core V1 freeze**：Identity / Memory / Turn / Tool / Freshness / Provider 的接口冻结，不再反复重构。
3. **多入口产品闭环**：Desktop + QQ 真正共享同一身份、最近状态、未完成 purpose；完成实机 E2E、崩溃恢复、一键启动和备份。
4. **补“活着”的能力**：Vision → 有限主动性 → 基础流式语音；B站、复杂自治、手机/Quest 以后再做。

## Scope 原则

### XiaoYu Core 负责

- identity
- persona
- memory authority / provenance
- long-term memory lifecycle
- canonical turn
- recent state
- tool runtime
- freshness / persistence
- provider routing
- evidence / answer contract
- purpose state

### Surface / Capability 负责

- Desktop / Live2D
- QQ / OneBot
- Vision capture
- TTS / ASR
- Bilibili
- Mobile / Quest

**任何 surface 都不允许自己再维护第二套人格、第二套记忆、第二套 provider truth。**

## 1.0 完结定义

1.0 不是“把所有想法都做完”，而是：

- 一个稳定 Core；
- API-only provider；
- 可信长期身份与记忆；
- 跨重启、跨模型连续；
- Desktop + QQ 同一身份；
- 基础 Vision；
- 基础流式 Voice；
- 有限 proactive / purpose；
- DECADE100 完成；
- 完整 E2E / recovery / backup；
- 之后新增能力不得成为 1.0 release blocker。

完成这些后必须明确标记：

**XIAOYU_1_0_DONE**

后续 SurfCore 社会化能力、B站、复杂陪看、手机、Quest、多角色等属于 1.x / 2.0。
