# R49 destructive confirmation composition spec — 2026-10-29

Status: **COMPOSE EXISTING COMPONENTS / DO NOT REBUILD ACTION INFRASTRUCTURE**

R49 的 destructive safety 已有三块可复用证据：

1. `memory.action.confirmation_binding`：目标/身份/分支/payload/TOCTOU 绑定；
2. `memory.action.crash_consistency`：mutation + action status + audit + replay state 单事务 exactly-once；
3. 独立 R49 confirmation-boundary audit：80/80 未确认不改状态，32/32 正例确认/重放，stale 8/8、cross-identity 8/8 fail-closed。

因此下一版产品候选应**组合**这些边界，而不是实现另一套 pending-action/confirmation ledger。

关键 pending action 必须绑定：
- identity；
- source/provenance fingerprint；
- exact target component + semantic fingerprints；
- expected authoritative generation；
- relation；
- exact proposed mutation payload/evidence；
- expiry；
- replay/consumption state。

确认应用必须在一个原子事务内完成：重新验证全部绑定 → R47 mutation → action 状态 → immutable audit → replay consumption → commit。

明确禁止：
- bare numeric memory_id/proposal_id 作为 approval capability；
- 未确认 destructive proposal 直接改 authoritative state；
- stale/cross-branch/cross-target/payload-substituted confirmation；
- 为 R49 再造一套重复 action infrastructure。

未解决事项仍单列：生产 key management、确认 UI/UX、用户误确认、multi-host/distributed transaction、physical deletion。这些不应被 E0 reference 偷换成“已产品化”。

机器可读规格：
`governance/lead_workspaces/r49_semantic_adjudicator_20261029/R49_CONFIRMATION_COMPOSITION_SPEC.json`
