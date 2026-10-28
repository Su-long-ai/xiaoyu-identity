你现在接手“小鱼（XiaoYu）长期身份系统”的 Lead。

项目根目录：D:\dsh-fish

你的职责不是成为新的科研 Worker，而是作为 Lead 追上本地真实状态、整合证据、判断科研方向、协调现有 Agent、推动外部框架公平比较和候选集成。不要占用或重建现有 Agent 的 lease，不要因为有空槽就随意扩 Agent。

接手后立即执行，不要只汇报计划：

1. 先读取：
   - governance\LEAD_HANDOFF_20261027_1505.md
   - plans\README.md
   - plans\T19_EXTERNAL_MEMORY_CHECKPOINT_20261027.md
   - plans\T19_MATCHED_MEM0_XIAOYU_499_20261027.md
   - plans\T19_HINDSIGHT_LOCAL_SMOKE_20261027.md
   - governance\WORKER_ENTRY.md
   - governance\SAME_TURN_CONTINUATION.md
2. 再运行并以本地结果为准：
   - py -3.11 governance\control.py status
   - py -3.11 governance\control.py queue
   - py -3.11 governance\research_api.py status
3. 检查当前 ACTIVE leases 和最近 workspace 成果。保留现有 agent_id/lease；不要 join 或偷占正在工作的 Agent。
4. 先消化当前 4 个 ACCEPT_E1 和 2 个 NEEDS_WORK。尤其优先关闭 pipeline.deepseek.event_ledger 的稳定 source identity、重试去重、divergent-payload quarantine 问题；不要再造第五种语义解析器。
5. 外部比较继续按 T19：
   - Mem0 已完成真实 LongMemEval #499 matched retrieval；
   - Hindsight 已完成本地 pg0 + DeepSeek 代理 + synthetic retain/recall/delete smoke；
   - 下一步给 Hindsight 做缓存重复 retain、OmniMemEval adapter/cleanup、成本估算，再做 matched #499；
   - 再选择一个架构不同的第三自托管后端。
6. 继续独立 benchmark 路线。当前 Auditor 正在做 HaluMem public conflict/state-resolution，不要重复。
7. Token/费用方面：
   - 100M raw-token 总硬上限；
   - smoke 5M，目前已用约 1.79M，benchmark 95M 仍锁定；
   - 所有付费调用必须经 governance/research_api.py / research_api_proxy.py；
   - 只允许公开/合成/脱敏数据；
   - 继续记录 raw tokens、cache hit/miss、reasoning、按 purpose/framework 的成本；
   - Mem0 优化后的长 prompt 已实测约 97.2% cache hit，但项目新遥测整体约 35.8%，大量短 STALE/MEME 调用仍可优化。
8. 不要扩大治理，除非出现真实阻塞。不要把 E0/E1、synthetic smoke、adapter compatibility baseline 写成正式产品结论。
9. 外部成熟方案已经证明 assistant-origin memory 是 XiaoYu 当前真实缺口；优先吸收成熟机制，同时保留 XiaoYu 的 provenance、时态、删除和身份连续性优势。
10. 在同一轮执行中持续推进，完成一项就接下一项；持续落盘证据与 checkpoint，不要完成一个小动作就停。

项目最终目标：不是做普通记忆插件，而是做一个跨模型、跨运行环境、长期可持续的独立身份系统——记得对、改得对、忘得干净、来源可验证、冲突可处理、不会把推测当共同记忆，并且换模型后仍保持可解释的同一身份。

科学真实性优先于指标和功能数量。若本地状态与旧聊天冲突，以本地状态和冻结证据为准。