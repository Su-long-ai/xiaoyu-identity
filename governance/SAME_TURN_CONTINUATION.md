# 小鱼科研 Agent：单回合多任务接力

适用于 Research Engineer A/B 和 Independent Auditor；由用户手动启动 ChatGPT 下一轮，不支持后台自动唤醒。

## 每次用户手动开启一轮后的动作

1. 读取当前项目 `AGENTS.md`、`governance/WORKER_ENTRY.md` 和现有任务；保留原先稳定的 agent_id。
2. 若已经有 ACTIVE 租约，继续该租约；否则：
   `py -3.11 D:\dsh-fish\governance\control.py next --agent-id <当前agent_id>`
3. 在返回的 next_workspace 内做实验、写完整证据、运行基线和负例。
4. 交付时调用既有 submit：
   `py -3.11 D:\dsh-fish\governance\control.py submit --lease-id <当前lease_id> --agent-id <当前agent_id> --manifest result.json`
5. 读取结果：`continue_research=true` 且返回 `next_task` 时，**同一 ChatGPT 回合**立即在新工作区开始下一任务，不要先写结束汇报。
6. `next_step=SELF_DIRECTED_NEW_HYPOTHESIS` 时，静态任务表用完并不意味着科学路线耗尽。基于本机项目实时证据提出可证伪、非重复的新假设，用现有 `join` 命令领取新工作区，沿用同一 agent_id，继续实验。
7. `PAUSED`、`POOL_CAPACITY_FULL`、真实工具阻断时，停止对应受阻操作，不绕过安全限制；保留已完成的证据。
8. 一个问题负结果或一个 E0 提交均不是停止本轮的理由。仅在平台执行边界、真实阻断或确实没有值得研究的方向时结束回复，提供紧凑工作总结。

## 独立审计

审计员的 ACTIVE 工作区可持续建立独立合成反例、复验和测试工具。遇到 E1 待审提交时依据 AUDIT_POLICY.md 审核，随后继续其它证据核验；不得审核自己的提交。将审计工具/反例作为 E0 提交后也会自动获得下一份审计方向的租约。

## 安全及界限

- 控制面**只分配任务、记录结果**；不会启动模型、后台服务或发消息触发下一轮。
- 用户手动触发每轮 ChatGPT 执行；无需额外安装 Codex CLI/Ollama 守护进程。
- 每项工作只在分配的独立 workspace 写入。不得碰真实 identity/、其他 Agent 工作区、外部私有聊天或凭据。
- 当前预算为零，不开启后台或付费模型调用。
- 长任务结束前及时落盘断点。平台对单轮时长有上限，无法保证固定分钟数。

## 不依赖结束前保存：中断恢复协议

ChatGPT 可能直接触发单回合执行边界，不保证有收尾工具调用。

- 在实验推进过程中尽早把脚本、输入、指标、反例和日志写入**当前独立工作区**；每完成一个实际阶段就落盘，不要囤到最终回复。
- 下轮仍由用户手动触发。第一步运行 `control.py next --agent-id <原有agent_id>`；工具会**即刻扫描已落盘的文件元数据**，无需上一轮主动生成断点文件。
- 返回 `WORK_IN_ASSIGNED_WORKSPACE` 且 `resumed=true`：沿用当前 ACTIVE 租约，查看 `workspace_recovery.recent_files`，直接接续。
- 返回 `RECOVER_FROM_PREVIOUS_WORKSPACE`：之前租约已经 STALE/TTL_EXPIRED，控制面为相同假设合法领取了**新租约**；只读查看 `previous_workspace` 的部分实验成果，将继续工作和新产出写在 `next_workspace`，**绝不向旧工作区补写或篡改旧证据**。
- 返回 `RECOVERY_CLAIM_BLOCKED`：旧任务需要保留，但新租约因并发冲突、容量或止损而未获准。不能向失效租约写入，不得绕过控制面；选择其它允许的非重复研究路线。
- `workspace_recovery` 只列文件名、大小、修改时间，不读取正文或秘密；保存了什么就恢复什么。**未写入文件的思考无法重建**。
- 任务已成功 submit 的 E0/E1 保持完整可验证，避免从零重跑。不要用 `ACTIVE` 推断聊天正在后台运行。

以上机制只在**下一次用户手动触发 ChatGPT 后**执行，不在后台发起任何新模型调用。即使执行到时间截断，也不要求 Agent 最后一秒总结或写 checkpoint。

## 提交临界区的中断恢复（2026-10-27）

- `submit` 已确认提交成功后，下一任务分配即使发生异常，也仅返回 `next_step=RETRY_NEXT` 和已经保存的 `submission_id`。**绝不能将这个情况当成提交失败或重新提交原租约**。
- 新的 `receipt.json` 先写临时文件，再原子更名为正式回执；避免强制中断后出现半截 JSON。
- 若回执已经存在但 SQLite 还没有相应提交，只能在其 lease、清单哈希、证据哈希、等级等字段**完全一致**时复用；不一致则拒绝写入并要求人工核对。
- 若租约已经 STALE/TTL_EXPIRED 且留下孤立回执，新一轮 `next` 从**数据库**判断实际是否提交，读取旧文件，但新实验只在新租约工作区写入。
- 真正的断电/操作系统级文件系统损坏、尚未落盘的代码或思考仍无法保证恢复；这不是自动启动 ChatGPT 的机制。

## 付费调用连续执行补充（2026-10-27）

单回合多任务接力不等于无限付费循环。所有 DeepSeek 调用受 `TOKEN_COST_POLICY_20261027.md` 的 scope/epoch 熔断约束。Agent 在同一回合切换 case 时必须保持稳定的 prompt 前缀与 budget scope；命中成本熔断后不得通过改 purpose、case 编号或 proxy tag 继续烧额度。已完成的离线工作仍可继续，付费部分等待 Lead 明确处理。


## 同回合切换方向的复用门禁

`next` 自动领取 backlog 时会绑定 Lead-vetted reuse plan。只有 `next_step=SELF_DIRECTED_NEW_HYPOTHESIS` 才需要 Worker 自己提出 plan；此时必须先 `reuse-check` PASS，再 `join`。不能为了继续同一回合而跳过复用检查，也不能通过换 family/lineage 名字规避。

pre-guard 旧租约发生 STALE/TTL_EXPIRED 时，只允许 family + lineage + capability + hypothesis 完全相同的恢复；恢复不能携带新 subsystem。已知 duplicate-wheel 规则仍然生效。

## Portfolio research mode (2026-10-31)

Current steady-state: 3 divergent explorers + 2 applied mainline researchers + 1 independent auditor; Lead is outside worker leases and 3 user-capacity slots remain for bursts.

- Explorers: one exact hypothesis gets one bounded pass. After submission, immediately rotate to a materially different mechanism/paradigm or new cross-family question. Do not repeatedly optimize the same exposed cases. Exploratory evidence is E0 only and cannot directly become LEAD_READY.
- Mainline: work only on accepted bytes/product-facing mechanisms with matched baselines, no oracle fields, and measurable integration or simplification value.
- Auditor: audit promotion candidates/material claims and portfolio-locality/duplicate-work risk; do not gate every exploratory E0.
- If a task is falsified, saturated or scientifically blocked, that is a routing event, not a reason to keep the same hypothesis alive.
- As long as useful work exists and the execution turn remains open, submit -> next -> continue. "Running full" means continuously switching to valuable tasks, not spending time on a dead hypothesis.

## Per-chat workspace isolation (2026-10-31)

Every ChatGPT worker chat must generate one unique worker_instance_id (for example chat-7f3a91c2d4e8) and reuse it for every next, join, heartbeat, submit, and release call in that chat.

agent_id is the stable scientific role identity. worker_instance_id is the parallel chat instance identity. A post-fix ACTIVE lease is bound to exactly one worker instance. A different instance receives WORKER_INSTANCE_CONFLICT and no workspace path.

After submit, WORKSPACE_SEALED.json marks the old workspace historical/read-only. Evidence verification uses an immutable submission snapshot outside the worker workspace, so later accidental writes cannot alter the committed evidence chain.

## Background-liveness truthfulness（2026-11-01）

submit -> next -> continue 只保证当前 ChatGPT 执行回合仍然存活时继续。治理 registry、phase-priority、condition 文件本身不会在后台调用模型，也不会在审计 verdict 到来时自动唤醒一个已经结束的 ChatGPT turn。

因此：
- 没有真实 Automation task ID、常驻 worker/daemon PID 或其他已验证执行器时，禁止汇报“持续监控 / 已建立后台监控 / 会自动继续”。
- 外部 Auditor / Lead verdict 尚未出现时，应写 WAIT_EXTERNAL_AUDIT 或等价表述，并明确“下一次用户/Automation 唤醒时刷新 live registry 后继续”。
- 如果确有 Automation，只能描述其真实 cadence；ChatGPT Automations 的周期任务不是连续常驻 worker。
- 若新的 global_preempt_self_directed=true backlog 在已有 self-directed lease 期间出现，下一次 control.py next 会返回 HIGH_PRIORITY_BACKLOG_PREEMPT_REQUIRED。先 checkpoint/submit 或 release 当前 bounded work，再重新 next 领取 blocker；不得继续把低优先任务当主线。

