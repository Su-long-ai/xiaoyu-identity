> SUPERSEDED BY FAST_RESEARCH_LOOP (2026-11-02). Execution now follows governance/fastlane/FAST_RESEARCH_LOOP_20261102.md. Research agents iterate reusable retrieval components inside umbrella leases; only positive local E2E becomes E0, then light audit, fixed external200, and baseline promotion. Mainline continues other product/capability work. Current baseline is governance/fastlane/BASELINE.json (generation 2, multifacet_bge_rrf_v1, 109/200 = 54.5%).

# XiaoYu Capability Sprint — Retrieval Completeness（2026-11-02）

状态：**ACTIVE / LOCAL CONTROL-PLANE ENFORCED**

当前最大产品能力瓶颈已经由固定 LoCoMo200 外部评测定位为 **read-side retrieval completeness**，尤其 Multi-hop 找全必要证据。

基线：总体 QA 44.50%；完整 evidence 进入上下文 35%；完整 evidence 条件下 QA 88.57%；Multi-hop 完整 evidence recall 10%；Single-hop 完整 evidence 条件下 QA 97.06%。

本地已有冻结的零 provider-call 候选 `HYBRID_BGE_RRF_RETRIEVAL_CANDIDATE_FREEZE_V1.json`：在 199 道可评分 exposed-dev 问题上，all-recall 从 38.19% 提到 59.30%，Multi-hop all-recall 从 6.67% 提到 26.67%，top-k=20。它仍是 exposed-dev E0，未授权直接修改 live product。

因此当前顺序固定为：

1. **RETR01**：把冻结 BGE+BM25+RRF candidate 接入真实 ProductMemoryBridge/read-side shadow；保持 authority/admissibility/lifecycle、stable ID 和 context cap=20 不变，先过 deterministic/product regression。
2. **RETR02/RETR03**：集中提高 Multi-hop candidate completeness，研究 entity/relation/temporal/event facet union 与 bounded multi-query/query decomposition。
3. **RETR04**：在 candidate pool 已含完整证据时，降低 selector/context packing 丢证据，固定 top-20。
4. **RETR05**：对 residual missing-hop 做结构化 falsification，区分 query-generation、pool crowding、cross-session linkage、selector loss；禁止逐题补丁。

默认冻结：B1/B3 deterministic memory core、write-side correction/retraction/authority 主逻辑、answerer prompt、judge 配置、固定 LoCoMo200 item set、context cap=20。禁止扩题；raw full LoCoMo gold 保持删除；retrieval 输出必须先封存，再由 scorer/auditor 使用 gold。

除已观察 material P0/P1 外，旧 CORE_MEMORY_PORTFOLIO_RESEARCH、historical rescue、persona、非关键治理/微性能、answerer prompt 方向全部暂停。当前明确保留的 material P1 例外只有 **RC8B1R1**。

已经在运行的无关 self-directed lease 不强杀，允许完成当前 bounded pass；提交或释放后，下一任务必须回到 retrieval sprint。

只有当 retrieval completeness 明显提高后 QA 不再随之提高、两条 materially different retrieval 路线都失败、独立审计推翻诊断，或 Owner 明确改目标，才退出本 sprint。
