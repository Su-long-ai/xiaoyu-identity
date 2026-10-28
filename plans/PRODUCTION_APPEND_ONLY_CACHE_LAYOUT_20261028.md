# XiaoYu Production Cache Layout — 2026-10-28

Status: **ARCHITECTURE GUIDANCE / NOT AN E2 PROTOCOL CHANGE**

## Goal

Use provider prefix caching where it naturally matches XiaoYu's long-lived conversation shape, rather than padding short independent benchmark prompts.

## Preferred request layout

When semantically valid, order model-visible state from most stable to most volatile:

1. fixed system / safety / identity interpretation contract;
2. cache epoch / authority fence;
3. immutable or append-only admitted history/evidence;
4. derived current-state projection required for this turn;
5. current retrieved evidence;
6. newest user turn.

The next request should extend the previous valid prefix whenever possible instead of regenerating equivalent history in a different order.

## Cache epoch / invalidation

Append-only layout must never defeat correction, deletion or authority changes.

Rotate the cache epoch/fence whenever a change invalidates previously model-visible prefix material, including:
- erasure/tombstone affecting previously admitted evidence;
- authority downgrade or provenance repair;
- scope/principal change;
- snapshot rollback/reconciliation that invalidates visible state.

After rotation, old prefix reuse is intentionally sacrificed for correctness.

## Do not optimize by

- padding meaningless tokens to cross a cache block boundary;
- preserving stale/deleted context merely for cache reuse;
- moving volatile data ahead of stable data when that changes semantics;
- omitting required evidence to improve cache percentage;
- treating cache-hit rate as an identity/correctness metric.

## Runtime metrics

Production optimization should prioritize:
- cache-miss tokens per useful answer;
- total tokens per useful answer;
- provider cost per useful answer;
- latency per useful answer;
- correctness / evidence validity.

Cache-hit percentage remains diagnostic. High hit rate is useful only when it reduces actual miss tokens/cost without weakening identity or memory semantics.

## Relationship to E2

The running E2 LongMemEval pilot remains unchanged. Its independent-case prompt geometry is intentionally not rewritten to imitate a production conversation just to improve cache telemetry.
