# 小鱼 · 独立可迁移的私人 AI 伴侣原型


> **Research direction — 2026-11-02:** Retrieval-completeness capability sprint is active locally. LoCoMo200 found 35% complete-evidence context recall and 10% Multi-hop; the frozen zero-call BGE+BM25+RRF exposed-dev candidate reaches 59.3% all-recall and 26.7% Multi-hop. Current P0 is product-shaped read-side integration and further Multi-hop completeness. See governance/CAPABILITY_SPRINT_RETRIEVAL_20261102.md.

> **Current status · 2026-10-31:** the product runtime now uses the independently accepted minimal composition: an exact accepted R47 confirmed-memory core plus a four-field SQLite FTS5 derived retrieval index. Product/identity regression is 38/38 PASS. Truthful R47 runtime telemetry is integrated as a routine product remediation and its E1 review is still pending; this is not an E2/E3 promotion. Formal HaluMem/LongMemEval boundaries remain governed separately, and E2/E3 claims are still forbidden.

这是一个**本地持久身份实验原型**，不是 DeepSeek/DSH 插件。身份、记忆、成长与模型服务商解耦；除用户主动聊天/成长反思外不会自动调用模型。

## 打开

双击 `启动小鱼.cmd`，或运行：

`py -3.11 companion.py`

需要 Python 3.11（含 Tkinter），产品核心无需第三方 Python 包。

## 当前产品架构

产品运行时现在只从 product_components/memory_engine_v1/ 加载已经晋级且 SHA 固定的记忆组件；governance/ 不再是产品运行时依赖。旧 fish.py 已改为兼容启动器，默认转到 companion.py；原始旧实现仅保存在 legacy/ 供显式恢复使用。


- **独立身份**：`identity/identity.sqlite3` 是身份与原始事件的权威数据源，identity ID 不随模型变化。
- **事件与来源**：消息、互动、记忆审批、更正、撤回和成长记录都有本地事件来源；bootstrap 设定不会冒充共同经历。
- **长期记忆产品桥**：`product_memory_bridge.py` 的已确认产品记忆路径在运行时只依赖 exact accepted R47；R49/R52 仍保留为冻结科研/历史工件，但不是当前产品运行时依赖。
- **检索**：派生加速层使用 **SQLite FTS5**，元数据只保留 `memory_id / priority / status / source_event`；中文 bigram 只是 query token 适配。FTS5 只负责候选检索，R47 的 current/conflict/lifecycle 语义决定哪些记忆仍可作为当前模型可见状态。
- **更正与撤回**：用户可在「长期记忆」里更正、撤回、归档；旧状态保留为历史证据，但退出当前召回。
- **来源非放大**：写入和 bridge 两个边界都校验 canonical `source_event`；assistant/system/unknown 来源不能升级为 `user_state`，恢复的异常旧行会被 quarantine。
- **单调变更版本**：schema V3 使用 `change_seq` 跟踪记忆 mutation，避免同一时间戳下撤回/更正留下 ghost memory。
- **Fail-closed 降级**：如果 exact memory bridge 缺失、漂移或运行异常，聊天仍可使用，但长期记忆注入显式变为空；不会静默回退到较弱的 legacy recall。
- **人格连续性**：成长反思必须由用户批准并绑定真实互动证据，写入版本化人格历史。
- **模型解耦**：可切换 DeepSeek、Qwen、OpenAI-compatible、Ollama 或自定义兼容服务；模型配置不会改身份数据库。Qwen 已是一等 provider，默认 `qwen3.8-flash` + `DASHSCOPE_API_KEY`，thinking 关闭。
- **完整迁移**：导出包含 `identity.sqlite3`、`identity.json` 与校验清单，不包含 API Key；导入只允许新目录。当前恢复逻辑兼容 V1/V2/V3 身份包。

## 模型切换

在 UI 点击「切换模型」。默认配置是 DeepSeek；密钥只从对应环境变量读取。切换 provider 不改变 identity ID 或本地记忆状态。

当前已有离线回归验证：同一身份/记忆快照在 provider 配置切换前后，注入给模型的身份上下文字节保持一致。**这证明基础设施连续性，不等于不同模型的行为必然完全相同。**

## 记忆边界

只有用户确认过的记忆进入 current user state。待确认候选、bootstrap、assistant 历史、被撤回/归档/替代的旧状态不会被当作当前用户事实。

如果 memory bridge 不可用，UI 会显示警告；此时不会用 legacy recall 补记忆，避免组件故障反而扩大错误记忆暴露。

## 安全与隐私

- 导出文件包含私人聊天和关系历史，应私密保存；当前导出不加密。
- 归档/撤回会停止当前召回，但历史证据仍可保留；“物理删除所有历史备份”是更强的独立隐私目标。
- 产品 memory bridge 全部在本地运行，不把私人身份数据发送到研究 API。
- 科研/benchmark 默认只用公开、合成或明确脱敏数据；真实 `identity/` 不进入科研评测。
- 小鱼仍是 AI 软件原型，不声称有意识或真实生物感受。

## 当前验证

完整产品回归：

`py -3.11 -m unittest -v test_identity test_identity_v2 test_product_memory_bridge`

当前结果：**38/38 PASS**。

Longitudinal smoke v2（含 canonical-source provenance 隔离）：

`py -3.11 tools\xiaoyu_longitudinal_product_smoke.py --count 5000 --repeat 10 --max-median-recall-ms 120`

5000-memory 性能参考（2026-10-29，来自当前 memory-core 之前的精确修订；后续 final-send/proposal hardening 未改变该参考的用途，但本段不声称是最新 root-byte 重跑）：
- 5000 条记忆首次派生索引构建：约 **32.23 s**；
- recall median：**48.96 ms**；
- recall p95：**49.25 ms**；
- restart bridge：**49.93 ms**；
- correction / retraction / restart continuity：全部通过；
- restart 不触发 full reconcile。

首次 5000-memory 冷构建仍是明确性能债，但不会在每轮聊天重复支付。

## 跨模型行为 shadow

使用一次性合成身份做真实 API shadow：同一份当前身份上下文分别交给 DeepSeek Flash 与 Qwen3.8-Flash，各重复 3 次。检查助手身份名、更正后的当前城市、鞋偏好、已撤回事实不被猜回。当前结果：DeepSeek **3/3 PASS**、Qwen **3/3 PASS**，六次语义结果一致；不读取真实私人 identity，不属于 E2 正式结论。

## 科研与正式结论边界

R52 的 E1 接受说明其测试范围内的 open-domain composition 通过了独立复核；它**不是** E2/E3 产品完成声明。

当前 HaluMem confirmatory judge 已在 final freeze 前重新绑定为 Alibaba Model Studio `qwen3.8-flash`（thinking disabled）。需要 `DASHSCOPE_API_KEY`，且必须先做全新的 12/12 Flash calibration；GPT-4o/旧 Max judge 结果不复用。

正式 E2 当前边界：
1. 原 final-v2 独立 re-audit 与 final execution freeze 已完成；
2. 首次 HaluMem prediction 的 68 COMMITTED + 1 durable UNKNOWN 已被 Recovery V2 以“COMMITTED 精确复用 + UNKNOWN=TRANSPORT_ABSTAIN_NO_RETRY”方式合法接管；
3. Recovery V2 已独立审计并单独 final-freeze，当前仅 HaluMem 获准继续 prediction；
4. prediction seal 完成后才允许执行全新的 qwen3.8-flash **12/12 calibration**；只有 calibration 通过后才允许 HaluMem gold scoring；
5. LongMemEval 原 holdout 因 pre-seal gold-boundary materialization 已失去 untouched 资格，当前保持禁用，不允许静默替换或继续出分；
6. 最终结果仍需独立正式审查后才能考虑 E2 promotion。

The physical-delete/tombstone final-send prior P1 is independently closed on the current bound bytes: 16/16 fault cases, 16/16 retry-closure cases and the full 38/38 product regression pass. The non-exposed physical-delete cold-start/legacy-migration path remains P2 advisory. e2_claim_allowed=false.


## 2026-10-30 current override

- Product final-send fail-closed remediation is now **independently rechecked and closed on the bound bytes** (fish-eba8bfe5b6864d51); the remaining physical-delete cold-start/legacy-migration issue is P2 advisory.
- The Owner increased the hard total-project API ceiling to **RMB 100**, but spending remains staged rather than blanket-authorized. Formal HaluMem Recovery V2 confirmatory is **checkpoint-paused**, not invalidated or restarted; Stage A is restricted to the existing bounded dev gate.
- Current paid priority is a bounded non-confirmatory budget-worthiness gate on the already-exposed 647-turn / 51-QA HaluMem pilot. Formal confirmatory and LongMemEval remain disabled while that gate is evaluated.
