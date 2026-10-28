# T19 Graphiti LME #499 Session-47 Cost Gate — 2026-10-27

## Decision

**STOP / COST-GUARD BLOCKED. Do not run full #499 under the current smoke policy.**

The public gold-bearing LongMemEval-S #499 session 47 was started through the frozen OmniMemEval Graphiti adapter, but the governed research API correctly terminated ingestion when the normalized `proxy:graphiti` rolling cache-miss cap was reached.

This is a cost/reliability result, not a retrieval-quality result. Because ingestion did not finish, no claim is made about whether Graphiti would retrieve the #499 gold answer after a complete graph build.

## Workload

- LongMemEval-S index: 499
- gold-bearing session index: 47
- source: assistant-origin public benchmark evidence
- messages: 12
- message-content characters: 4,300
- expected gold phrase: `Grilled Snapper with Mango Salsa`
- Graphiti deployment: commit `2b5db9e139b2627c3ba18ff55f9181569b0d8224`
- local BGE embedding; paid LLM calls only through `proxy:graphiti`

## Measured partial-ingestion cost

Ledger rows after this probe's marker:
- COMMITTED: **57**
- UNKNOWN: **0**
- RESERVED after termination: **0**
- raw tokens: **112,291**
- prompt tokens: **107,726**
- completion tokens: **4,565**
- cache hit tokens: **18,688**
- cache miss tokens: **89,038**
- measured prompt-cache hit rate: **17.35%**

The immediately preceding successful Graphiti synthetic smoke used 11,136 cache-miss tokens under the same normalized scope. Therefore the scope rolling total reached:

- cache miss: **100,174**
- configured guard: **100,000**

The next provider reservation was rejected before upstream execution with:

`Scope 'proxy:graphiti' rolling cache-miss guard reached (100174 >= 100000)`

Graphiti surfaced this as an HTTP 500 from the sync ingest endpoint because its internal provider abstraction translated the proxy's 429 guard signal into Graphiti `RateLimitError`. This did **not** create an UNKNOWN outcome.

## Cleanup

The failed sync request left a partial graph, so Lead explicitly issued:

`DELETE /group/lme_exper_user_graphiti_adapter_probe_499`

Result:
- HTTP 200
- direct Neo4j post-delete node count for the group: **0**
- direct Neo4j post-delete relationship count for the group: **0**

No partial benchmark graph is retained.

## Interpretation

1. Graphiti passed the tiny synthetic functional gate, but a single 12-message / 4.3k-character real public session already consumed 57 paid LLM calls and 112k raw tokens before ingestion completed.
2. The low cache reuse means a 50-session matched #499 run would be materially more expensive than Hindsight and cannot be justified from the current 5M smoke budget/runtime policy.
3. The runtime cost guard worked as intended: it prevented the comparator from silently expanding a small smoke into a large paid run.
4. Graphiti remains a useful architectural comparator (temporal knowledge graph), but is **not comparator-stable/cost-qualified** for the next matched stage under current settings.
5. Do not unlock the 95M benchmark because of Graphiti. The benchmark phase remains locked.
6. If Graphiti is revisited later, cost reduction must be an explicit experimental variable (e.g. coarser episode granularity, reduced extraction passes, or another frozen Graphiti configuration) and must first re-pass a comparable public/synthetic gate. Do not simply raise the runtime guard to force completion.

## Related evidence

- synthetic pass: `plans/T19_GRAPHITI_SYNTHETIC_SMOKE_20261027.json`
- synthetic deployment checkpoint: `plans/T19_GRAPHITI_LOCAL_SMOKE_20261027.md`
- attempted public probe script: `external/graphiti_lme499_session47_probe_20261027.py`
- this checkpoint records the guarded termination because the probe script intentionally did not emit a success JSON after incomplete ingestion.
