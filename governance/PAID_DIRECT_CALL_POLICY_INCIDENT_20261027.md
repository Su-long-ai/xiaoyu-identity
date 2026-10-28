# Paid Direct-Call Policy Incident — 2026-10-27

## Finding

`runtime_guard.require_proxy_tag=true` 自 2026-10-27 16:00 左右生效，但当时的 `research_api.py` 只在 proxy 入口校验 tag，direct `ResearchApiBudget` 调用仍能绕过该声明。

机器账本：`governance/PAID_DIRECT_CALL_POLICY_INCIDENT_20261027.json`。

影响窗口：

- post-policy direct calls: **600**
- distinct direct scopes: **35**
- committed raw tokens: **922,643**
- prompt / completion: **775,245 / 147,398**
- measured cache hit / miss: **21,888 / 753,357**
- first observed: **2026-10-27 16:09:00 +08**
- last observed: **2026-10-27 21:48:55 +08**

这是“机读政策与 gateway 实现不一致”的治理/来源问题，不等价于模型输出本身错误。

## Current P1 impact

- R16：`direct:r16_structured_event_candidate`，本身已经因 88/96 raw protocol NONPASS，现由 R27 替代。
- R18：`direct:r18_context_behavior` 共 16 calls；结果保留为不可直接晋升的 observational evidence，R29 负责 `proxy:xiaoyu` 合规重放 + fresh supplemental holdout。
- 当前 **10 个 ACCEPT_E1 不需要回撤**：
  - API/model-dependent accepted claims 均在 proxy-only policy epoch 前完成；
  - policy epoch 后接受的 CI、source-aware retrieval、single-SQLite snapshot、conflict resolution、R17 trusted authority 都是本地确定性/离线证据。

因此不做“因为 gateway bug 把所有历史 E1 清零”这种过度治理。

## Central fix

现在 `research_api.py` 在 reserve 之前中央检查：

1. runtime guard enabled；
2. 当前时间 >= effective epoch；
3. `require_proxy_tag=true`；
4. scope 不是 `proxy:...`；

满足以上条件时立即抛出 `ResearchBudgetError`，不建立 reservation、不接触 provider。

内部 XiaoYu 模型实验使用独立登记 tag：

`local-budget-proxy:xiaoyu`

它不会冒充 `mem0oss / hindsight / graphiti / cognee` comparator scope。

现场负例已验证：direct reserve → expected fail，usage DB row delta = **0**。

## Evidence policy

这 600 条历史调用保持原始 `direct:...` 标签，不删除、不重写成 proxy，也不通过数据库迁移“洗白”。

后续任何需要付费模型证据的 P1 E1 候选，都必须能把 provider usage 追溯到当时允许的 proxy scope；否则即使语义指标漂亮，也不能以该调用作为正式 E1 promotion evidence。


## Follow-up: proxy-shaped scope spoofing

R27 exposed that a direct `ResearchApiBudget` caller could previously pass `budget_scope="proxy:xiaoyu:..."`, creating a proxy-shaped accounting row without traversing the HTTP proxy. Historical R27 rows therefore remain E0/non-promotable even though their scope string begins with `proxy:`.

Fixed by recording `gateway_origin`, requiring an internal proxy-handler capability before a proxy scope may be reserved, and requiring `gateway_origin=http_proxy` for LEAD_READY paid evidence. Historical rows are not backfilled. See `plans/P1_PAID_PROXY_ORIGIN_PROVENANCE_FIX_20261027.md`.
