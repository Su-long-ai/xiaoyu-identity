# 小鱼科研控制面

- `CHARTER.md`：权责、分级、硬约束与反过度治理。
- `WORKER_ENTRY.md`：科研 Agent 入池、连续执行、付费调用和 Build-vs-Reuse V2。
- `policy.json`：机读政策；E2/E3 仍未开放。
- `RESEARCH_BACKLOG.json`：Lead-vetted 候选以及每项 machine-readable reuse plan。
- `REUSE_CATALOG.json`：版本化组件目录，含 lifecycle / owner / source / version / license / health / review date。
- `REUSE_GUARD.md`：领取前、历史工作检查、提交时二次校验和部署缝隙处理。
- `COMPONENT_ADMISSION.md`：新增外部组件从 reference/trial 到 adopt 的集中准入规则。
- `decisions/ADR-*.md`：架构选择、备选方案、后果与何时重新评估。
- `control.py`：SQLite 控制面；租约、止损、prior-work、reuse doctor、E0/E1 提交与独立审阅。
- `registry.sqlite3`：科研池状态，与正式身份数据库分离。

## 常用命令

```powershell
cd D:\dsh-fish
py -3.11 governance\control.py status
py -3.11 governance\control.py queue
py -3.11 governance\control.py reuse-audit
py -3.11 governance\control.py reuse-doctor
py -3.11 governance\control.py next --agent-id <stable-agent-id>
py -3.11 -m unittest discover -s governance -p "test_*.py" -v
```

自主新方向先查历史：

```powershell
py -3.11 governance\control.py prior-work --family <family> --lineage <lineage> --capability <capability> --hypothesis "<hypothesis>"
```

然后把需要审阅的 lease 写进 reuse plan 的 `prior_work.reviewed`，说明 `novelty`，再执行 `reuse-check` / `join`。同 family 或同 lineage 的旧研究必须显式审阅；完全相同且已提交的 hypothesis 默认拒绝，除非明确为 falsification / replication。

## Build-vs-Reuse V2

新的 research_engineer 租约 fail-closed：组件必须来自当前目录；`hold` / `deprecated` 不能用于普通新研究；不允许模糊的 `existing_vector_backend` / `fastembed_existing` 作为新任务依据，必须点名具体版本组件；新 dependency/framework 先经 Lead 集中准入，正常 lease 不访问网络做依赖扫描。

领取时的 `REUSE_DECISION.json` 与 registry SHA256 绑定；guarded submission 的 `reuse_compliance` 必须与领取决定一致。catalog/policy 变化不改写历史实验，`reuse-doctor` 只提示 revision drift；新 lease 按当前目录重新评估。

完整规则见 `REUSE_GUARD.md`、`COMPONENT_ADMISSION.md` 和 `decisions/`。

## Benchmark 与删除语义

未来 matched retrieval 研究必须先冻结 RAW / SOURCE / CANONICAL_CURRENT / TASK_DEFINED scoring target，并尽量保存完整 ranked outputs 以便离线重评分，见 `plans/P1_BENCHMARK_SCORING_POLICY_20261027.md`。

删除/备份区分逻辑 erasure、beyond-use、restore replay prevention 与物理安全擦除。旧快照恢复成 active state 前必须先应用更新的 erasure/invalidation lineage，否则 fail closed，见 `plans/P1_ERASURE_BACKUP_SEMANTICS_20261027.md`。

## 付费科研

DeepSeek 统一经过 `research_api.py` / loopback proxy。Build-vs-Reuse / prior-work / doctor 都是本地 stdlib + SQLite 操作，不新增模型调用。大 benchmark 仍锁定。
