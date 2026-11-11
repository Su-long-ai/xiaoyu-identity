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

## 2026-10-29 产品化切换

R47–R52 已完成独立 E1 收口，R52 最终提交 `sub-0cc4e587fc8a46d4` 已 `ACCEPT_E1`。项目不再继续扩同类 Rxx 研究链，当前主线改为：

1. 收完既有 E2 confirmatory：Recovery V2 HaluMem prediction → prediction seal → qwen3.8-flash 12/12 calibration → HaluMem gold scoring → 独立结果审查；LongMemEval 原 holdout 保持 INVALIDATED/禁用；
2. 将 accepted memory/state 能力接入真实 `companion.py`；
3. 优先做中文、更正/撤回、跨模型身份连续性的产品纵切；
4. 新科研仅由真实产品失败或 confirmatory blocker 触发。

已新增薄产品桥 `product_memory_bridge.py`：accepted R52/R47/R49 负责可信存储/当前状态，SQLite FTS5 负责派生 posting/candidate retrieval，中文 bigram 仅作为查询 token 适配；真实私有对话不经过研究 API，R52 synthetic projector 不进入产品语义抽取。schema V3 用单调 `change_seq` 防止同时间戳更正/撤回 ghost；bridge 故障时长期记忆显式 fail-closed，不回退 legacy recall。当前产品回归 **38/38 PASS**；canonical source provenance、recent-dialog stale-state、physical-delete tombstone failure 的 final-send fail-closed 均已进入产品字节。最新 physical-delete P1 已 Lead 复验 16/16，但仍等待登记独立 Auditor exact-byte recheck，不能由 Lead 自行标记 CLOSED。5000-memory memory-core smoke 继续作为性能参考。详见 `plans/PRODUCT_MEMORY_BRIDGE_CLOSEOUT_20261029.md`。


## 2026-10-29 跨模型真实行为 shadow

产品 adapter 已新增一等 Qwen provider（qwen3.8-flash / DASHSCOPE_API_KEY / thinking off）。合成同身份上下文分别实调 DeepSeek Flash 与 Qwen3.8-Flash，各 3 次，六次对更正、撤回、偏好与身份名的结构化结果完全一致。当前产品离线回归 38/38 PASS；这只是产品 shadow，不是 E2/E3 声明。


## 2026-10-29 E2 Recovery V2

首次正式 HaluMem confirmatory 在 68 COMMITTED + 1 durable UNKNOWN 后暴露 checkpoint/state 原子性缺口；LongMemEval 则因 pre-seal 全量 JSON 反序列化触发 gold-boundary 污染。项目没有重试 UNKNOWN、删除 receipt 或静默换 holdout，而是新建 Recovery V2 generation。

Recovery V2 exact package 已由独立 Auditor 审计并获得单独 final freeze：既有 68 COMMITTED 只允许按原 request/response hash 精确复用，原 UNKNOWN 只能作为 `TRANSPORT_ABSTAIN_NO_RETRY` 且不产生 semantic state；新调用 pre-dispatch 固化 request intent，session 恢复只认 progress-bound immutable SQLite checkpoint。HaluMem 当前按该 generation 执行 prediction；LongMemEval 原 holdout保持禁用。HaluMem prediction 全部 seal 后，才允许 fresh qwen3.8-flash 12/12 calibration，再进入 gold scoring。


## 2026-10-30 budget override

The project now operates under a hard **RMB 100 total-project API ceiling with staged authorization**. Formal HaluMem confirmatory is checkpoint-paused; no full-run restart is authorized. Stage A is still the exact-current BUDGET50_HALUMEM_DEV_GATE_V1 pilot (legacy name, 647 semantic turns + 51 frozen QA on non-confirmatory data), whose original peak-cost design cap remains 2.5 CNY. Product final-send P1 is independently closed on the current bound bytes; only the non-exposed physical-delete cold-start/legacy path remains P2 advisory.


## 2026-10-30 prospective generalization gate

Repeated Stage-A tuning has exposed the targeted 10-case sets and the original HaluMem 51-QA set. Effective immediately, those sets are **debug/regression only** and may not support a generalization or promotion claim.

A new one-shot **LoCoMo blind-200** gate is frozen from a previously unused benchmark: 180 primary memory QA (60 multi-hop + 60 temporal + 60 single-hop, balanced as 18 primary questions per each of 10 conversations) plus 20 open-domain diagnostic QA. Membership is selected deterministically from sample_id + QA index + category without using question/answer/evidence content. Model-visible input contains conversation + selected question only; answer/evidence, event summaries, observations and session summaries are stripped. Gold is represented pre-seal only by hashes.

Both an exact baseline and the post-dev candidate must produce and seal all 200 predictions before any gold decode is authorized. The selected 200 become permanently exposed after scoring and can only be used for postmortem/regression; unselected LoCoMo QA remain reserve. Passing blind-200 still requires independent audit and a separate budget review before formal HaluMem confirmatory; it never auto-authorizes formal execution.

Authoritative files: `governance/EVAL_GENERALIZATION_POLICY_20261030.json`, `governance/LOCOMO_BLIND_200_PROTOCOL_V1.json`, `governance/LOCOMO_BLIND_200_GOVERNANCE_BINDING_V1.json`.


## 2026-10-30 LoCoMo blind V2 correction

The initial LoCoMo blind-200 V1 prefreeze was independently reviewed as **NEEDS_WORK before any blind prediction**. V1 executed zero predictions and decoded zero gold; its 200 selected questions are excluded from the replacement generation and cannot support a claim.

The authoritative prospective gate is now **LoCoMo blind-200 V2**. V2 uses a fresh seed and has zero overlap with V1. Selection runs only on `governance/locomo_blind_source_v2_gold_stripped.json`; primary membership is 60 multi-hop + 60 temporal + 60 single-hop, with every conversation contributing at least four questions per primary category, plus 20 open-domain diagnostics. Model-visible input omits category labels as well as answer/evidence/summaries/observations. No per-case gold hash oracle is retained.

The upstream raw `locomo10.json` has been deleted from the local workspace for the prediction phase. Gold can only be re-downloaded at the fixed dataset SHA after exact baseline and candidate predictions both seal all 200 unique frozen blind IDs and the V2 gold gate authorizes one-shot scoring.

Authoritative files: `governance/LOCOMO_BLIND_200_PROTOCOL_V2.json`, `governance/LOCOMO_BLIND_200_GOVERNANCE_BINDING_V2.json`, `governance/LOCOMO_BLIND_200_PREFLIGHT_V2.json`, `governance/locomo_blind_200_gold_gate_v2.py`, and `governance/EVAL_GENERALIZATION_POLICY_20261030.json`.
