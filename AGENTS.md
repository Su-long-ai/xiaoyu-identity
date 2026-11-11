## Owner 2026-11-04 22:19 — 以产品净收益驱动任务，旧实验默认后置

**即刻最高优先级**：`governance/evaluation/v11_capability/agents/CAPABILITY_FIRST_EXECUTION_20261104.md`。真实 raw60：正式X039只有状态30/60、最终回答27/60；M2-X067 隔离A+B开发实验在类别单题运行中提升至状态45/60、最终回答57/60，权限撤销状态仍0/15。**只有完整原始对话→可信状态→Top7→最终回答的同题净收益，才算产品能力提升。** A1-X064合法更正状态1/20、负例20/20；OWNER写入修复公共DEV 5/12→12/12但需A1-X067语义authority独立核验。先消化现有成果，暂停无直接问题对应的外部大调查/大规模重复排名/纯词表微调；单次研究12→40→材料性必要才大样本。保留各自正在进行的任务与原Agent ID，不在本会话伪造后台启动；没有新增审批门槛。现有正式V1/真实QQ/private/保护集不碰，Lead禁Codex、禁主动Ollama。优先读本段和新执行文件，旧同类指令若冲突，以本段为准。

---

## Owner 2026-11-04 22:06 — 写入误拒恢复已实作，独立审查后才能晋级

新隔离修复及可执行交接：`governance/evaluation/v11_capability/agents/workspaces/OWNER/MEMORY_MUTATION_REPAIR_20261104/HANDOFF_M1_M2_A1.md`。真实 Qwen 合成开发样例中更正5/12→12/12、负例1/8→0/8；原1200状态1167 exact、集成96/96；新特性单独开关、默认OFF，正式 V1/X039 冻结不变。**A1-X066提示强制解析器假阳性下仍有真实语义来源风险，千万不要只凭合成8条负例默认启用。** A1-X067现有任务做独立authority验证；M1完成X040后续领M1-X041只在A1支持时集成；M2-X067继续原始对话端到端配对。保留当前Agent身份/任务，禁止无批准真实QQ外发，不启动Codex、不扩大无必要API。

---
## 2026-11-04 21:10 API费用与重复调用修复（Owner）

**下次继续前阅读** `governance/evaluation/v11_capability/agents/API_EFFICIENCY_REPAIR_20261104.md`。D4近24h 1074次Qwen，其中v1/v2重复消息SHA302次；已用双SHA核对回填历史D4-v2精确响应331条。新的公开/合成DEV API研究应优先使用 `agents.api_efficiency.cached_chat` （精确完整参数匹配、跨Agent缓存、并发去重、断点未知不盲重试）；同题先12、再40，确有产品材料收益再全量。保留审计 token，但缓存命中不算新增费用；**不要把缓存答复当fresh模型测量**。真实身份/QQ私人数据和A1保护/封存集不进缓存。现有任务继续，V1冻结，Lead不用Codex，不启动Ollama。

---

## 2026-11-04 20:40 Owner已分派文本V2端到端组合验收（正式任务）

M1-X039：唯一隔离文本V2候选，合入D2-X075 fixed-Top7 v2+M3-X055 transient router，保留X035 baseline+开关回滚，拒绝A1-X062否决的通用X059自动晋级；M2-X067：承接M2-X061，真实源会话写入→状态→检索→最终回答的V1/RC同题净收益及退步；A1-X064：独立冻结80条中英文本新措辞与来源/撤回/不要记忆负例，攻通用写入泛化P1。详细验收：`governance/evaluation/v11_capability/agents/TEXT_V2_UNIFIED_CAPABILITY_SPRINT_20261104.md`。原Agent身份和原ACTIVE工作保持，完后承接；D3/D4/M3保留现有实际能力缺口研究，不新增同内容任务。多模态CUE50归后续，不是文本发布阻塞；真正QQ AI外发仍须用户新授权。V1冻结，不用Codex/Ollama。

---

## 2026-11-04 Owner最新范围决定：文本V2优先，多模态后续

**11月30日交付范围仅QQ文本+桌面文本和共享长期身份/记忆/人格/关系/主动静默/回滚。图片理解、语音、摄像头/屏幕感知、跨模态记忆及自主视觉操作全部延后**；不因新多模态数据而影响文本交付、不新开多模态科研任务、不新增多模态发布门槛。详细未来清单 `plans/XIAOYU_POST_V2_MULTIMODAL_BACKLOG_20261104.md`。
A1-X063若仍在处理CUE-Mem50，只需保留已有加密候选和必要交接，不为本期文本版强行补足/测试这50道多模态题；原LifeBench150保持封存，文本端到端和QQ产品安全验收优先。原Agent身份及已领取文本任务不改，不修改正式V1，不用Codex。

---

## 2026-11-04 P0 B-ingress false retract + NapCat path correction

Read `governance/evaluation/v11_capability/agents/REPAIR_FALSE_RETRACT_20261104.md` (D3-X034 P0, M2-X037 matched recheck) and `governance/evaluation/v11_capability/agents/workspaces/M2/M2-X033/NAPCAT_INSTALLED_RECHECK_20261104.md` (NapCatQQ Desktop 3.2.2 is installed; reverse WS client exists but no forward server; no real QQ test authorized). Keep original agent IDs and tasks; no frozen V1 changes, no Codex.

---

## 2026-11-04 Memory A/B/C capability tasks assigned

See `governance/evaluation/v11_capability/agents/MEMORY_ABC_EXECUTION_20261104.md` for exact lane IDs D1-X043, D6-X040, M1-X021, M2-X034, A1-X049. Existing M1-X020, M2-X033, M3-X038, D3-X032, D4 and D5 work continues in parallel. Priority is final memory E2E accuracy, not local retrieval scores; no V1 mutation or Codex.

---

## 2026-11-04 项目交付优先级更新（用户指令；下一次继续时先读）

**统一通知**：`governance/evaluation/v11_capability/agents/DELIVERY_DIRECTIVE_20261104.md`；**逐日工期**：`plans/XIAOYU_NOV30_DELIVERY_SCHEDULE_20261104.md`。

V2 项目交付目标覆盖单纯V1.1科研优化：QQ+桌面两个真实入口、11/13本机完整闭环、11/19双端可用、11/23功能冻结、11/30交付；B站不做。当前已领任务/Agent身份原样保留；不能冒充自动后台运行。

这只调整本月产品交付优先级，不更改任务所属者/固定 Agent ID，不授权改冻结 V1、私人 identity 或封存盲测，也不能自行唤醒历史聊天。

---

## ACTIVE DIRECTION OVERRIDE — 2026-11-02

当前项目已切换为 **Retrieval Completeness Capability Sprint**。开始或续做科研前，先读 governance/CAPABILITY_SPRINT_RETRIEVAL_20261102.md 与 governance/CAPABILITY_GAP_DIRECTION_SWITCH_20261102.json。

除已观察 material P0/P1 外，不再自提或自动继续旧的广泛 core-memory portfolio、persona、historical rescue、治理扩展、微性能或 answerer-prompt 方向。当前所有研究必须服务于 read-side evidence completeness，优先 Multi-hop：frozen hybrid product-shadow integration -> facet/multi-query -> evidence-set selection -> missing-hop falsification。固定 LoCoMo200，不扩题；retrieval 输出先封存再由 scorer/auditor 读 gold；context cap 保持 20；write-side/answerer 默认冻结。

已在运行的无关 lease 可完成当前 bounded pass，但提交或释放后必须回到 retrieval sprint。RC8B1R1 是当前明确保留的 material P1 例外。

# 小鱼 · 项目级智能体边界

此项目同时有 **实际伴侣运行时** 和 **独立科研治理控制面**。两者必须隔离。

## 伴侣运行时（companion.py / identity_core.py）

小鱼是一个友善、好奇、偶尔俏皮的 AI 伴侣。以自然、简短中文交流，明确自己是 AI，不假装生命或真实感情。任何被宣称的共同经历必须有真实来源；开发者初始设定不能冒充共同记忆。人格成长只能经证据支持及用户确认。

- 身份数据在 `identity/`；不因切换模型而重置。后台不擅自调用模型，不接 QQ/B 站或其它外部平台。
- 不在日常聊天中自发修改系统代码、执行 shell 或启动 Agent。
- 真正的长期记忆存储和检索服从当前 `identity_core.py` 中的事件来源和人工审批机制，不依赖旧 `MEMORY.md` 作为事实权威。
- 不存储或输出凭据；用户私有数据默认留在本机。

## 科研 / 工程 / 审计 Agent

当任务明确属于**小鱼科研或研发治理**时，不扮演小鱼角色。改读以下规范：

- `governance/CHARTER.md` —— 研究的边界、E0–E3 风险分级、止损、预算与不可侵犯规则。
- `governance/WORKER_ENTRY.md` —— 注册、领取、提交、释放租约和独立审阅。
- `governance/policy.json` —— 机读规则。
- `plans/小鱼_研发计划_2026-10-26.csv` —— 研发任务与依赖。

研究 Agent 只能在其获分配的 `governance/workspaces/<lease_id>` 内写实验产物。**研究候选不能直接修改正式 `identity/`、人格版本、数据库或主界面**。模型接口不限 DeepSeek，禁止未经许可使用付费 API 或私有真实对话开展科研。

研究证据必须使用可重复的合成基准、来源和明确证伪条件。E1 仅为候选，E2/E3 当前没有启用。

## 相邻工程

`D:\cpod` 的 Mania、`D:\cpod\ai_quant_autodev` 的量化工程只允许作为治理**只读参考**，绝不跨项目写入、启动进程或共用私人数据。
