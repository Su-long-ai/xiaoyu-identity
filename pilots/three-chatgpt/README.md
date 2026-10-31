# XiaoYu: 三 ChatGPT 云端科研协作 E0 试点（2026-11-01）

**协调入口**：https://github.com/Su-long-ai/xiaoyu-identity/issues/1  
**本分支**：`pilot/three-chatgpt-20261101`（从 main `781394b9d70795f0a289c7c84ca643b141d21416` 建立）。  
**现成可复现实验候选**：`experiment/cloud-e2e-20261101` 的 `experiments/cloud_e2e_smoke.py`、`evidence/cloud_e2e/20261101/results.json`、`report.md`。其历史 12/12 只是候选证据，不自动等于新会话独立复算。

## 角色/实际会话

- Lead：当前 ChatGPT 会话。维护范围、审计边界、最终收口。提示词 `LEAD_PROMPT.md`。
- Research：由用户另开一个 ChatGPT 对话；研究独立性和专用分支。提示词 `RESEARCH_PROMPT.md`。
- Auditor：由用户再开一个 ChatGPT 对话；**不参与 Research 的候选设计或代码修改**。提示词 `AUDITOR_PROMPT.md`。

**三个聊天不能由一个聊天直接创建或保证后台存活。** GitHub 账号相同，角色 ID 是约定标识，不是强身份认证或独立授权隔离。

## 协作与状态协议

1. Issue #1 是唯一任务协调入口；**不要并发修改一份共享 JSON 状态文件**。已有状态以具体 GitHub commit/分支/审计材料为准。
2. Research 只写专有分支 `pilot/three-chatgpt-20261101-research`，提交机器生成的机读结果和可复现实验；禁止直接改 production 源文件或主分支。
3. Auditor 只写专有分支 `pilot/three-chatgpt-20261101-audit`，读取 **Research 已提交的确切 commit**，独立复算及攻击性验证，指出差异，不接受无证据的自述。
4. Lead 从 GitHub 分别读这两支的结果和源 SHA，确认链条后给出 E0 试点结论；没有独立验证就 **INCOMPLETE**。
5. 如 GitHub Issue 评论可用，可在 Issue #1 留下提交 URL、角色、状态和摘要；否则以分支上材料和回复用户的链接为准。
6. 每个提交需记录：基准 commit、文件 hash、命令、依赖/版本、测试数据来源、运行环境、成功/失败/跳过、失败反例和局限。
7. 优先 ChatGPT Python 执行；无法支持先尝试兼容依赖；再使用 GitHub Actions（必要时且限定运行时长、成本及权限）。不使用本地 MCP、Codex，不能在聊天结束后假称后台自动科研。
8. 仅合成数据。不得上传真实 `identity/`、`exports/`、聊天、密钥或私人数据；不得使用未批准的收费 API。
9. 保持 `main` 不变，不自动合并；原有 `AGENTS.md` 和 `governance/CHARTER.md` 优先，试点是 GitHub 云端工程 E0，不冒充正式科研控制面租约/E1/E2/E3 门。
10. 已知限制：本地 `D:\dsh-fish` 的较新状态不一定已同步；仅基于 GitHub 已有 commit 说话。

## 本轮冻结目标和验收标准

**研究任务 R-001**：在一个*不同 ChatGPT 会话*中，从 GitHub 取 `send_guard.py` 原源码和 E0 smoke 测试，独立在 ChatGPT 环境重新运行 12 项合成 SQLite 测试，生成机器输出的 JSON，额外运行至少 1 项明确的反例/负控（例如临时关闭 authority 检查后，相关测试应失败；此变更绝不写入产品源码）。记录反例有无真实命中。

**审查任务 A-001**：Research 成果出现后，独立验证实际文件与声明的哈希、命令、输入边界、12 项结果、负控效果；自己从源代码独立运行必要复验，报告审查所见。只给 E0 engineering verdict，不给产品升级或科学泛化结论。

**Lead 收口**：检查 Research/Auditor 来源版本、提交 SHA、负控有效性、复验记录和 scope；即使 Research 12/12 PASS，如审计未完成、不可复算或证据不全，结果标记 `INCOMPLETE`/`NEEDS_WORK`。

**阶段状态**：已创建试点入口和规则；Research / Auditor 聊天是否启动、任务是否执行以其各自提交为准，禁止预先声明成功。

## 可观测流程

`Issue #1 → Research 分支代码与结果 → Auditor 分支独立报告 → Lead 交叉核验与 E0 决策`。

所有人的首次步骤均须从 GitHub 读取本文件及各自角色提示词，而不是依赖其他聊天的总结。
