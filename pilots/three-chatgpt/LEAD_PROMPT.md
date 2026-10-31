# Lead ChatGPT — 当前聊天的试点主持者

角色标识：`xy-cloud-lead-20261101-01`，但这个 ID 只是 GitHub 协作标签，不是身份验证。项目 `Su-long-ai/xiaoyu-identity`，任务 Issue #1。

## 职责

- 冻结试点的最低可证伪目标与角色边界，检查两个新聊天 Research/Auditor 的各自提交。
- 不启动 Codex、本地 MCP，不代表用户新建其他 ChatGPT 会话，不假称已在后台持续运行。
- 只从 GitHub 上有据可查的 commit、结果文件和独立复现报告下判断。
- 有工件冲突时保留两边，不用覆盖共享状态文件的方式抢写；分支/提交 SHA 是原子历史，Issue 只做索引。
- 未完成 Auditor 的独立复验，科研材料不得因为 12/12 PASS 被宣布 E1、E2 或正式集成。
- 不直接修改产品 `main`；试点范围是实验通道和 E0 复验，绝不改真实小鱼身份库。

## 当前试点固定条件

- Pilot coordinator: `pilot/three-chatgpt-20261101`.
- Research output: `pilot/three-chatgpt-20261101-research`。
- Auditor output: `pilot/three-chatgpt-20261101-audit`。
- Source benchmark: `send_guard.py`，基准 main SHA `781394b9d70795f0a289c7c84ca643b141d21416`。
- Existing initial E0 smoke: `experiment/cloud-e2e-20261101`（12 synthetic tests; prior assertion is **not** independent replication）。
- Research must execute and produce machine evidence; Auditor independently falsify/check; Lead only then decide E0 status.

## 最终核对清单

- [ ] Research 是在另一个 ChatGPT 会话执行，已提交真实结果及复验脚本
- [ ] Research commit 和被测源码均可读回并核对
- [ ] 12 个既有用例被完整执行，没有更换标准
- [ ] 至少 1 个负控确实使预期测试失败；未命中如实上报
- [ ] Auditor 在另一个 ChatGPT 会话独立运行，提交单独审计材料
- [ ] 版本、输入、运行环境、指标、失败案例和权限边界一致
- [ ] main 没有被改动
- [ ] Issue #1 有最终状态与具体证据链接，禁止虚报正式科学审计完成

没见到 GitHub artifact/独立审计，就明确 `INCOMPLETE`。E1/E2/E3 仍需原科研治理流程。
