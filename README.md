# Persistent AI Identity & Long-Term Memory System

**Private research system for stateful AI agents:** model-independent identity, event-sourced long-term memory, human-confirmed persona evolution, portability across providers, and external memory evaluation.

**Portfolio signal:** persistent memory · stateful agents · provenance · provider abstraction · evaluation.

> **Research direction — 2026-11-02:** Retrieval-completeness capability sprint is ACTIVE. The frozen LoCoMo200 run scored 44.50% overall; complete evidence reached context on 35% of items, and answer accuracy was 88.57% when evidence was complete. Current P0 work is read-side retrieval completeness, especially Multi-hop (10% complete-evidence recall). See [governance/CAPABILITY_SPRINT_RETRIEVAL_20261102.md](governance/CAPABILITY_SPRINT_RETRIEVAL_20261102.md).

> **Research status — 2026-10-28:** P1 text-identity integration is frozen **integration-ready** (12/12 required stages ready; 122/122 governance regression at freeze). E2 prospective validation and product readiness are **not** unlocked. See [P1_FREEZE.md](P1_FREEZE.md) and [plans/P1_INTEGRATION_READY_CHECKPOINT_20261028.md](plans/P1_INTEGRATION_READY_CHECKPOINT_20261028.md).

这是一个**本地持久身份实验原型**，不是 DeepSeek/DSH 的插件。
对话需要 API（可更换服务商）；喂食、休息、玩耍、保存记忆、身份导出等不花 Token。

## 打开

双击 `启动小鱼.cmd`，或在目录运行 `py -3.11 companion.py`。需要 Python 3.11（含 Tkinter），无需第三方 Python 包。不会自启和自动调用模型。

## 核心设计

- **独立身份**：`identity/identity.sqlite3` 是主数据，身份 ID 与模型无关。
- **事件账本**：每条消息、互动、记忆存档和成长笔记均留有时间和可追溯记录。
- **长期记忆**：`长期记忆`里添加、检索和归档；只有明确说“记住：...”或你手动确认的内容会进入长期记忆。
- **人格连续性**：`成长反思`能根据真实经历提出候选，**必须经过你确认**才写入带版本的人格档案；不允许模型悄悄重写身份。
- **模型解耦**：`切换模型`支持 DeepSeek、OpenAI、Ollama、本地或其他兼容 Chat Completions 的服务。修改 `provider.json` 绝不改变身份数据库。
- **完整迁移**：点击 `导出身份`得到 `.zip`；其中有通用 `identity.json`、`identity.sqlite3` 和校验信息，无 API Key。提供 `IdentityStore.import_to_new_home`，只允许导入新目录，避免覆盖。
- **原始经历**：保留对话和活动事件以追溯、检查、修订；避免把模型生成的猜测当作事实。
- **本地控制**：除你主动请求的模型调用外无网络请求。不开网页，不装插件、不连 QQ/B 站。

## 模型切换

在 UI 点击 `切换模型`。默认 `deepseek` / `deepseek-flash`，密钥由环境变量 `DEEPSEEK_API_KEY` 提供；选择 OpenAI 时使用 `OPENAI_API_KEY`。
Ollama 连接回环地址端口 11434，模型名称需要按你的本机安装情况调整。
自定义兼容 API 可填写 HTTPS 接口或本地 HTTP，密钥变量名填环境变量**名称**，不要把密钥写到配置文件。
迁移以后，不同模型的行为仍有差别，**不可能保证表现完全相同**。

## 安全和边界

- 导出文件包含**私人聊天和关系历史**，应私密保管。当前导出未加密，不要公开发布。
- `归档记忆`表示不再检索，**不会抹掉原始历史和旧备份**；彻底遗忘需要另行设计隐私删除工具。
- 当前检索是无需联网的中文词语匹配与重要性打分，不是全量语义理解或长期自主记忆更新。
- 成长反思只在用户主动点击时调用模型；如果 API 返回 HTTP 402，仍可离线互动和管理档案。
- 首次升级会尝试从旧 `fish_data.json` 和 `MEMORY.md` 导入内容，保留原数据和备份。
- 现在仍是**早期可用原型**，并非完善的生命模拟，也不能证明 AI 有意识。

## 测试

`py -3.11 test_identity.py` — 离线测试迁移、去重、记忆检索、人格版本、模型切换、打包恢复和密钥不泄漏。

## V2 · 记忆来源、审核与成长证据

- 初始设定与真实记忆严格隔离。旧版 4 条初始化文本保留为 `bootstrap`，**不参与长期记忆检索**。
- 本机身份与真实互动计数分别统计，不将系统迁移、预设或技术事件算作共同经历。
- 在聊天中说“记住：...”或自然表达明确偏好时，会生成**待确认候选**；只有在「长期记忆 → 待确认」选择“确认候选”，才成为长期记忆。
- 长期记忆可追溯到完整原话对应的事件编号；拒绝的候选不会被当成回忆。
- 人格成长必须经过你的批准，并关联至少 2 条真实的对话或养成互动事件。
- 历史中的未使用初始设定仍随导出备份保存，但永远不冒充共同记忆。
- V2 导出格式可用 `py -3.11 restore_identity.py "导出的身份.zip" "全新的空路径"` 恢复；也能恢复旧 V1 身份备份并迁移来源分类。
- 旧版数据与程序已独立放在 `backups\pre-provenance-v2-*`，升级脚本保存在 `maintenance\`，未删除原资料。

验证：`py -3.11 -m unittest -v test_identity test_identity_v2`，全部离线运行，不调用 API。
