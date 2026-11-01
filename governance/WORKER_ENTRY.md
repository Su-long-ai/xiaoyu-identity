# 小鱼科研 Agent 入池指南

> **先读当前方向（2026-11-02）**：`D:\\dsh-fish\\governance\\CAPABILITY_SPRINT_RETRIEVAL_20261102.md`。本阶段不要从旧优先级自由选题；Research Engineer 只消费 `CAPABILITY_RETRIEVAL_SPRINT` 自动派工，集中提高固定 LoCoMo200 的 read-side evidence completeness，尤其 Multi-hop。非关键 P2、人格、治理整理和回答 prompt 优化暂停。


**执行起点**：`D:\dsh-fish\governance\CHARTER.md`。本阶段研究池尚未自动开人；**人工开启独立科研聊天后**，综合科研 Agent 才按下面方法领取任务。当前为两名综合 research_engineer 和一名独立 auditor。

## 给每个 Agent 的任务提示词

> 你是“小鱼长期身份研究项目”的独立科研 worker，先读 `D:\dsh-fish\governance\CHARTER.md`、`policy.json`、`RESEARCH_BACKLOG.json` 与 `control.py status`，再读取 `D:\dsh-fish\plans\小鱼_研发计划_2026-10-26.csv`。你的使命是减少长期身份、记忆、人格、关系连续性的**可测试不确定性**，不是不断提出新架构。建立稳定唯一 agent_id（多聊天不复用）；使用 CLI 申请一个具体假设；只在返回的独立 workspace 内写实验文件。优先合成数据和离线比较；不读取私人身份库、不访问 QQ/B 站、不更改 Mania / 量化或小鱼正式代码与记忆。收费 DeepSeek 科研仅可在任务确有需要时通过 governance/research_api.py，只发送公开/合成/脱敏 benchmark 数据；禁止直接绕过网关调用、禁止后台自主付费循环。当前仅开放 smoke 阶段 5M-token 额度，正式 benchmark 仍锁定。用固定基线和明确证伪条件提交结果，成功也不得自称 E2/E3 通过；遇到同家族已失败、已饱和或重复时换实质方向。每次结束报告事实、证据、限制和下一步决策。不要停在治理文件建设。
>
> 现有调研优先级：T02 开源源码/许可证审计、T04 中文合成长期记忆评测；基础工程优先于“大规模人格模拟”。

## 常用命令（Windows）

在 `D:\dsh-fish` 运行：

```powershell
py -3.11 governance\control.py status
py -3.11 governance\control.py queue
py -3.11 governance\control.py reap
```

领取示例（Hypothesis 须换成当前具体可测问题）：

```powershell
py -3.11 governance\control.py join --agent-id fish_scientist_001 --role research_engineer --family recall.dual --lineage retrieval.dual --capability memory_retrieval --lane main_bottleneck --hypothesis "On fixed synthetic multi-session tests, dual retrieval increases grounded recall over a 12-message short-window baseline"
```

成功返回 `lease_id` 和 `workspace`，然后在该 workspace 放 `result.json`、`result.txt` 等素材，格式见 `EXPERIMENT_MANIFEST.example.json`。

```powershell
py -3.11 governance\control.py heartbeat --lease-id fish-... --agent-id fish_scientist_001
py -3.11 governance\control.py submit --lease-id fish-... --agent-id fish_scientist_001 --manifest result.json
py -3.11 governance\control.py verify --submission-id sub-...
py -3.11 governance\control.py release --lease-id fish-... --agent-id fish_scientist_001
```

Lead-ready 候选由独立 auditor 异步审核。审计前先读 AUDIT_POLICY.md：P2/P3 不可否决；P0/P1 必须有明确可复现的影响与证据：

```powershell
py -3.11 governance\control.py review --submission-id sub-... --reviewer-id fish_auditor_001 --decision ACCEPT_E1 --reason "Independent evidence SHA and synthetic baseline were checked; candidate only, pending formal replication."
```

**角色注册规则**：auditor 必须先用自己稳定 ID，通过 `join --role auditor` 领取独立审计工作。科研提交者不能审核自己的提交。

## 付费科研调用

先执行 py -3.11 governance\research_api.py status 查看剩余额度。研究代码如需模型，应 import ResearchApiBudget 并调用其 chat(...)；不得自行读取密钥后直接访问 DeepSeek。UNKNOWN 调用会继续占用预留 token，这是故意的 fail-closed 设计。只有 Lead 在外部框架 smoke 跑通后才可将 benchmark_unlocked 打开。

## 不应做

- 不要绕过 pool 自称已投产或已经触发自动研究；当前只有控制面，没有自动发起工作。
- 不要为了占满 4/7 槽而重复研究；没有候选时允许空槽。
- 不要把隐私数据原文、密钥、身份导出存入科研提交材料。
- 不要把 E1 的审计通过写成 E2 科学证明，更不意味着小鱼对外发布。
- 不要把治理当真权限隔离：所有 Agent 若持有广泛本机读写工具，其权限需要另外限制。


审计支持 --findings-json 参数。字段、标准与示例参见 AUDIT_POLICY.md。使用 py -3.11 governance\control.py audit-stats 查看等待及阻塞数。**有待审候选不影响科研 Agent 继续领取新任务。**

## 已启用：同一 ChatGPT 回合多任务接力（2026-10-27）

阅读 `governance/SAME_TURN_CONTINUATION.md`。一个任务提交后若返回 `continue_research=true` 和 `next_task`，沿用原有 agent_id，直接进入新 workspace 继续科研，**不要在一次 submit 后结束本轮**。`next_step=SELF_DIRECTED_NEW_HYPOTHESIS` 时，自主选择新的非重复可证伪方向并按既有 join 领取；不可把静态任务表耗尽误作科研完成。审计员同样持续反例/复验，有 E1 待审时优先审核。恢复当前 Agent 可执行：`py -3.11 governance\control.py next --agent-id <原有agent_id>`，有 ACTIVE 租约会恢复而非重复领取。ChatGPT 下一轮仍由用户手动开启；控制面不启动后台模型、不更改付费预算。
## DeepSeek 成本/缓存约束（2026-10-27 Lead 更新）

付费科研除总预算外，现已启用 scope 级滚动与 epoch 硬熔断，详见 `governance/TOKEN_COST_POLICY_20261027.md`。外部 OpenAI-compatible 框架必须使用 `local-budget-proxy:<tag>`，未标记请求会在到达 DeepSeek 前拒绝。

重复实验构造 prompt 时，把**固定 system/schema/few-shot 放最前面**，case 文本、case id、日期、批号等动态内容统一放后面的 user payload；不要为了记录批号破坏公共前缀。若调用 `ResearchApiBudget.chat(...)` 的 purpose 带逐 case 数字，网关会自动归一化到同一 budget scope；新代码在能明确表达实验家族时优先显式传 `budget_scope=`。不得为了缓存命中率修改已经冻结的科学条件；需要改变 prompt 排布时开新的 prospective 版本并记录差异。

大规模 benchmark 仍锁定；即使未来解锁，默认也不在北京时间工作日 09:00–12:00 / 14:00–18:00 运行，以利用 DeepSeek 闲时半价。若收到 scope guard / epoch guard 错误，视为真实成本阻断：落盘当前证据并等待 Lead 调整，不换 purpose/case id/tag 规避限制。


## 去重 / 复用硬边界（2026-10-27 Lead freeze）

开始新方向前先读 `plans/P1_DUPLICATION_AUDIT_REUSE_FREEZE_20261027.md`。以下不是建议，而是当前 Lead 方向约束：

- 不再新写 lexical posting/inverted-index 存储层；优先 SQLite FTS5 + 现有 XiaoYu tokenizer/policy。只有 prospective 反例证明 FTS5 无法满足必要条件才可 reopen。
- 不再把未来 portable identity 建在 SQLite + identity.json + manifest ZIP 上继续逐个补洞；V2 ZIP 仅保留 legacy migration/regression。未来候选优先单 SQLite online-backup snapshot。
- 不新造通用 provenance/W3C ledger；Cognee/Graphiti 已覆盖大量通用 provenance/temporal 机制。event-ledger 研究只能聚焦 XiaoYu 特有的 source identity、authority、semantic drift quarantine、fail-closed state mutation。
- 不新造 graph DB、vector DB、ANN，不继续无差别收集 memory framework；现有 Mem0/Hindsight/Cognee/Graphiti + OmniMemEval 已冻结为外部参考集合。
- CI 不扩成自研供应链系统；P1 只保留最小 gate membership/hash fail-closed contract。
- 新的自研 subsystem 在领取/切换前必须说明：现有标准组件/冻结外部参考为什么不能满足，以及可证伪条件。仅“实现起来方便”不构成自研理由。

已有 archive/ZIP、handwritten-posting 研究证据保留作为反例/迁移验收数据，但不要继续沿同一补丁链扩展。


## 新任务必须先过 Build-vs-Reuse Guard（硬门禁）

从 2026-10-27 18:54 +08 起，新的 research_engineer 租约会在 `Governance.join()` 中强制执行 `REUSE_CATALOG.json`。这不是提示词规则，缺失或不合规会直接拒绝租约。

静态 backlog 任务使用 `control.py next --agent-id <id>`，控制面自动绑定 `RESEARCH_BACKLOG.json` 中由 Lead 审过的 `reuse_plan`，Worker 不能替换。自主新方向必须先运行 `control.py reuse-check`，传入与后续 `join` 完全相同的 family / lineage / capability / hypothesis / lane 和 `--reuse-plan-json`。计划必须包含 mode、已知 components、具体 gap、`no_new_infrastructure=true`、`new_dependencies=[]`。只有 PASS 后才允许 join。

租约工作区会由控制面生成 `REUSE_DECISION.json`，不要编辑、删除或覆盖。其 SHA256 同时存进 registry；篡改后 `submit` 会拒绝。

新的 guarded 租约提交 `result.json` 时还必须包含：

```json
"reuse_compliance": {
  "components_considered": ["必须与 REUSE_DECISION 中完全一致"],
  "new_dependencies": [],
  "new_infrastructure": false,
  "deviation": "none"
}
```

若研究过程中发现确实必须偏离复用计划，不得在当前租约悄悄改架构；先落盘证据，结束或释放当前方向，由 Lead 更新 `REUSE_CATALOG.json` 或开 `falsification` / `legacy_compat` 新任务。完整规则见 `governance/REUSE_GUARD.md`。


## Build-vs-Reuse V2：先查历史再开新方向

自主新假设在 `reuse-check` 之前必须运行 `control.py prior-work`。把需要审阅的相近 lease ID 写入 reuse plan 的 `prior_work.reviewed`，并用不少于 50 字说明 `novelty`。同 family 或同 lineage 的历史工作必须审阅，即使假设换了措辞；完全相同且已提交的 hypothesis 默认拒绝，除非明确使用 `falsification` 或 `replication_of`。

组件名也必须具体：`existing_vector_backend` / `fastembed_existing` 已 deprecated。新方向使用版本化 catalog 项；`hold` / `deprecated` 不能用于普通新研究。每次换方向前可运行 `py -3.11 governance\control.py reuse-doctor` 查看目录漂移、陈旧组件和近重复历史。

不要在每个 lease 访问网络做依赖扫描；新外部依赖由 Lead 按 `COMPONENT_ADMISSION.md` 集中审查，正常科研保持本地快速。


## LEAD_READY 付费模型证据必须绑定 usage ledger（2026-10-27）

若当前租约 reuse plan 含 `research_api_gateway`，且准备提交 `LEAD_READY`，必须保存实际 OpenAI-compatible response 返回的 `id`（格式 `api-<32 hex>`），并在 `result.json` 增加：

```json
"paid_evidence": {
  "call_ids": ["api-..."],
  "budget_scope": "proxy:xiaoyu",
  "phase": "smoke",
  "max_raw_tokens": 100000
}
```

外部 comparator 使用其对应已登记 proxy tag。控制面在 submit 和 Auditor `ACCEPT_E1` 两个阶段都会直接查询 `research_api_usage.sqlite3`：所有 ID 必须存在、COMMITTED、晚于本租约、scope/phase/provider 一致且总 raw tokens 不超过声明上限。direct scope、未知/UNKNOWN call、scope mismatch 都 fail closed。

普通 `EVIDENCE_ONLY` 不强制绑定 paid_evidence；但它也不能凭未绑定的付费调用晋升 E1。不要把历史 direct 调用重写成 proxy 调用。


### Paid proxy provenance refinement

A scope string named `proxy:...` is not sufficient evidence of proxy traversal. Do not call `ResearchApiBudget` directly with a proxy-shaped `budget_scope`; the gateway now rejects this under proxy-only policy.

For a uniquely attributable internal XiaoYu run, call the OpenAI-compatible loopback proxy with `Authorization: Bearer local-budget-proxy:xiaoyu` and optional `X-XiaoYu-Research-Run: <safe-run-id>`. The resulting ledger scope is `proxy:xiaoyu:<safe-run-id>` and `gateway_origin=http_proxy`. Save returned `api-...` response IDs in `paid_evidence.call_ids`.
