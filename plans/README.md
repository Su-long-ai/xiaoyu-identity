# 小鱼独立身份研发计划

更新：2026-10-27。主计划：`小鱼_研发计划_2026-10-26.csv`。本次更新把“外部框架真实部署与同条件比较”前移，避免继续重复造轮子。

## 当前状态

- 共 30 项任务：已完成 2、进行中 8、未开始 20；不再把 DeepSeek 余额问题标成阻塞。
- 已有 2 个综合科研工程 Agent + 1 个独立审计 Agent 实际入池并产生 E0 证据；正式 E2/E3 产品发布仍未开放。
- 治理连续工作/中断恢复已落地，当前回归 36/36；除真实阻塞性缺陷外，冻结继续扩张治理功能。
- `DEEPSEEK_API_KEY` 已在运行环境中存在，`provider.json` 默认 `deepseek-flash`。Owner 已授权第一阶段总计 **100M tokens**：先开放 5M smoke，剩余 95M benchmark 在外部框架跑通后解锁；所有付费科研必须经 governance/research_api.py。
- 当前科研已覆盖：中文更正与拒答、时态投影、来源/证据类型、删除派生数据、检索预算消融。均为 E0，尚不能当产品结论。

## 计划顺序的关键调整

原计划把外部 memory 框架比较放在 T18 之后（W10–11），现在证明过晚。外部调查显示已有统一评测适配层可直接复用，因此 T19 提升为 P0，并与 T04/T05 并行启动。

新的优先链：

1. T02 外部框架/许可/复用审计；
2. T04 冻结统一评测协议，区分 Raw-native 与 Oracle/Canonical；
3. T05/T10 DeepSeek 连通性、预算硬限制、用量记录；
4. T19 复用 OmniMemEval 做真实外部后端同条件对比；
5. T06/T08/T13/T15 只针对比较中暴露的缺口继续自研；
6. T18/T20 汇总内部基线和综合质量门；
7. 只有外部方案不能满足需求且自研有可复现收益时，才继续扩大 V3 架构。

## 外部基准/框架结论

- **OmniMemEval**：当前最值得直接复用的统一 harness。统一 `add/search/delete` adapter，覆盖主流 memory 后端及 LoCoMo、LongMemEval、BEAM、PersonaMem v2、HaluMem。ANSWER/EVAL 模型通过 OpenAI-compatible BASE_URL 配置，可接 DeepSeek。
- **TimlMemBench**：中英双语，专门覆盖撤回、替代、作用域、来源、激活与克制；同时提供 canonical-pool 与 raw-native 两种评测，非常贴合小鱼当前瓶颈。
- **HaluMem**：把幻觉拆到 extraction / update / QA 三个操作阶段，适合定位小鱼错误究竟来自语义抽取、状态更新还是最终回答。
- **RHELM**：更真实的长期、异构、动态资料环境，可作为后续高阶验证，不应替代基础可复现 benchmark。
- 第一批值得实跑的自托管/开源候选：Graphiti、Hindsight、EverOS、Cognee、Mem0 OSS，以及小鱼 V2；MemOS 额外做 DSH 原生插件级比较。Letta 放在 agent-level 比较。
- 厂商自报分数与第三方统一 harness 分数可能差异显著，计划禁止直接把厂商榜单当结论。

## 公平比较原则

必须分两条赛道，禁止混表：

1. **模型受控赛道**：自托管方案尽量统一 DeepSeek ANSWER/EVAL、数据、top-k/上下文预算、温度与评分器；能统一 extraction LLM/embedding 时也统一。
2. **As-shipped 赛道**：云端/托管产品允许使用其原生专有抽取/检索，但只代表产品整体效果，不声称是算法本身优劣。

所有结果至少报告：逐题答案与证据、分项准确率、错误确定回答/拒答、上下文 token、检索延迟、总 API token/费用，以及框架版本/commit。

## 文件

- `外部长期记忆调查_2026-10-27.md`：本轮外部调查与复用决策。
- `D:\dsh-fish\governance\WORKER_ENTRY.md` / `SAME_TURN_CONTINUATION.md`：科研 Agent 连续执行协议。
- `D:\dsh-fish\governance\RESEARCH_BACKLOG.json`：科研候选池；静态池耗尽不等于科研饱和。
