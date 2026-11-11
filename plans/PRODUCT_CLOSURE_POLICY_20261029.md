# XiaoYu 产品闭环与停止条件（2026-10-29）

状态：ACTIVE PRODUCT PRIORITY ADDENDUM
适用范围：D:\dsh-fish
目标：约束研究范围本身，而不是再增加一层研究治理。

## 1. 产品成功定义优先于研究资产数量

小鱼 V1 的产品目标只有四类：
1. **记得对**：重要用户事实/经历在需要时能被检索并正确使用，来源与当前性可解释。
2. **改得对**：更正、撤回、冲突、删除能改变后续回答，不让旧状态幽灵化回流。
3. **连续**：跨模型/运行时迁移后，身份与重要长期状态保持；初始化设定、用户事实、模型推断不混淆。
4. **用得起**：长期运行的延迟、上下文长度、token/缓存成本可接受，不因记忆增长线性恶化到不可用。

benchmark、audit、manifest、provenance 只服务于上述四类目标，不单独计作产品进度。

## 2. 当前产品主线

当前阶段固定为：
**既有 E2 confirmatory 收口 -> 最小纵向产品集成 -> 长期 shadow longitudinal 验证 -> V1 冻结。**

在这条链完成前：
- 不新增通用 memory framework；
- 不新增与当前产品失败无直接关系的研究大类；
- 外部调研默认视为已饱和，只有出现具体产品失败且现有方案解释不了时才重新打开；
- ACCEPT_E1 必须进入产品、明确延期理由或退役，禁止只累计候选数量。

## 3. 探索层与承诺层

探索/工程 shadow 路径默认轻量：
实验 -> 本地回归 -> shadow 集成 -> 观察真实失败模式。

只有以下动作进入重治理：
- 形成 E2/E3 正式科学声明；
- 修改正式长期身份/记忆状态；
- 删除/覆盖真实用户状态；
- 使用真实私有数据或对外行动；
- 发布不可逆迁移。

因此，研究失败、代理指标下降或非关键不确定性不应自动阻塞普通 shadow 工程。

## 4. Longitudinal 是最终主评测

合成集和公开 benchmark 保留，但 V1 必须增加长期 shadow 评测，至少覆盖：
- 多会话后事实召回；
- 用户更正后旧值不回流；
- 撤回/删除后的衍生状态闭包；
- 长时间间隔后的时间语义；
- 模型/运行时切换后的身份连续；
- 记忆增长后的检索延迟、上下文长度、token 成本。

longitudinal 结果只用脱敏/合成或 Owner 明确授权的数据。没有授权时不得用真实私人聊天补齐指标。

## 5. 停止条件

满足以下条件时，默认停止新增架构研究并冻结 XiaoYu V1：
- 当前正式 confirmatory 链完成，且没有 authority/admissibility 类 P0/P1；
- 最小产品纵向链实际跑通：ingest/update -> storage -> retrieval -> answer consumption；
- 关键更正/撤回/删除/冲突路径有回归覆盖；
- 至少一次跨模型或跨运行时迁移验证通过；
- longitudinal shadow 没有发现会让用户状态被错误长期保存/恢复的高严重度失败；
- 性能/成本未出现随记忆规模不可接受的退化；
- 当前已知产品级 P0/P1 归零。

达成后，新研究必须由新的真实产品失败重新开启；“还能继续优化”不是 reopen 理由。

## 6. 治理收缩规则

- 新 guard/doctor/manifest 必须替代或扩展现有机制；不得仅因为“更稳妥”新增平行层。
- 每个新增治理机制必须写清：触发条件、产品级失败、退出/删除条件。
- 连续一段产品周期未拦截任何真实 P0/P1、却造成正常路径阻塞的规则进入降级/删除候选。
- Lead 不得成为正常产品请求的同步依赖；Lead/独立审计只处理正式声明、不可逆动作和异常升级。
- 治理维护预算继续服从 CHARTER 的 10% 上限。

## 7. 决策优先级

产品故障 > longitudinal 失败 > 正式科学缺口 > 性能成本 > 新研究兴趣。

当没有产品失败、没有纵向失败、没有正式声明需求时，正确动作是停止研究、冻结版本，而不是制造新 backlog。


## 8. Longitudinal product gate now has an executable smoke

Use:

`py -3.11 tools\\xiaoyu_longitudinal_product_smoke.py --count 5000 --repeat 10 --max-median-recall-ms 120`

The product bridge now uses persistent incremental indexing instead of scanning all current memories on every recall. The index is acceleration only; frozen R52 state remains authority. In-place mutation of an existing memory ID is quarantined rather than silently replacing immutable-source state. Normal user correction still uses `correct_memory`, which retires the old row and creates a fresh sourced row.

Memory-core 5,000-row reference on 2026-10-29: recall median 48.96 ms, p95 49.25 ms; restart bridge 49.93 ms with zero full reconcile; correction, retraction and restart continuity all pass. First 5,000-memory build is 32.23 s and remains a cold-start performance debt, but it is not paid on each conversation. Later final-send/proposal hardening has advanced the current root regression to **38/38 PASS**; this paragraph keeps the prior exact-revision 5,000-row run as a performance reference rather than pretending it was rerun on every subsequent root byte.


## 9. Second-pass product hardening (2026-10-29)

Source provenance is now enforced at both write and bridge boundaries. Explicit `source_event` passed to `IdentityStore.add_memory` must resolve to canonical user evidence (`conversation.user`, `memory.saved`, or `memory.corrected`, actor=user). The ProductMemoryBridge independently revalidates canonical provenance so restored or legacy/direct-DB rows cannot launder assistant/system content into `user_state`; invalid rows are quarantined rather than model-visible. A temporary export/import reproduction verifies valid user memories stay visible and assistant/system-origin rows remain hidden with quarantine preserved before and after round-trip.

The FTS5 acceleration DB now commits derived index mutations once per sync rather than once per memory. Current 1,000-memory longitudinal reference after this change: cold build ~4.65s, median recall ~3.09ms, p95 ~3.23ms, restart ~9.11ms; correction/retraction/restart continuity PASS. Current core identity/product-memory suite: **38/38 PASS**. Canonical-source provenance is already covered; the newest physical-delete/tombstone-write final-send P1 remediation is Lead-verified (16/16 fault recheck) and still requires the registered independent exact-byte recheck before formal closure.

## 10. Cross-model behavioral shadow（2026-10-29）

产品层新增合成、可重复的跨模型行为连续性 smoke：同一份经过 correction/retraction 后的 IdentityStore + ProductMemoryBridge 当前上下文分别提交给 DeepSeek Flash 与 qwen3.8-flash。每个 provider 重复 3 次；六次均保持助手身份名、当前城市、低重心/安静鞋偏好，并对已撤回的薄荷茶返回 unknown。DeepSeek 3/3 PASS，Qwen 3/3 PASS，跨模型语义一致。该结果只证明当前合成纵切，不替代 20–50 turn longitudinal 或正式 E2。


## 10. Product mainline + continuous research (2026-10-29)

XiaoYu now runs a dual-track productization model. Product/mainline is the dominant track (~75% soft target); continuous research is retained at ~25% as a soft target, with roughly 75% of research expected to be product/falsifier driven and up to 25% free exploration. Closeout no longer means research is permanently disabled: when there is no explicit closeout blocker, at most one reuse-guarded self-directed research engineer may run. Any explicit product/confirmatory blocker suppresses that exception. Research percentage is never a blocking KPI, and existing audit/promotion gates remain unchanged.


## 11. Confirmatory recovery is now an execution phase（2026-10-29）

E2 is no longer PREFREEZE. The original final-v2 package passed independent re-audit and received a final execution freeze. The first HaluMem run exposed a transport UNKNOWN plus checkpoint/state atomicity gap; LongMemEval separately lost untouched-holdout status through pre-seal gold-boundary materialization. The project therefore froze a new Recovery V2 generation rather than hot-patching the old run.

Recovery V2 has an independent exact-byte audit and separate final freeze. Only HaluMem is authorized: old COMMITTED calls are exact-hash reused, the old UNKNOWN is transport-abstain/no-retry, new requests are intent-bound before dispatch, and resume uses only immutable progress-bound checkpoints. LongMemEval remains disabled. Fresh qwen3.8-flash 12/12 calibration remains post-prediction-seal and pre-gold-scoring. None of these execution steps by themselves authorize E2/E3 promotion.


## 12. 2026-10-30 budget-constrained execution override

Owner budget is now capped at **RMB 100 for the entire project API spend**, but the larger ceiling is explicitly staged and is not a target to spend. Formal HaluMem Recovery V2 remains scientifically intact but checkpoint-paused. Stage A may only finish the fixed, already-exposed 647-turn / 51-QA HaluMem pilot budget-worthiness gate; formal confirmatory may be re-enabled only after the dev prediction is sealed, fresh qwen3.8-flash calibration passes 12/12, the predeclared QA/safety thresholds pass, and a new cost projection fits the remaining budget. A poor pilot result routes back to dev/pilot remediation; it does not authorize repeated tuning on the formal holdout.

The registered independent product recheck fish-eba8bfe5b6864d51 closed the prior final-send P1 on the exact bound product bytes. The remaining physical-delete cold-start/legacy migration behavior is P2 advisory while that destructive surface is not exposed.
