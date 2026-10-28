# T19 DeepSeek Token / Cost Optimization Checkpoint — 2026-10-27

## Outcome

Lead completed a cost-control pass focused on **actual DeepSeek spend**, not merely raw-token reduction. The 95M benchmark phase remains locked.

## Incident that exposed the gap

A previously blocked full Hindsight LongMemEval-S #499 streaming client was still waiting for the local Hindsight service. When port 18888 was restarted for a small Lead probe, that old client resumed automatically and continued ingesting sessions.

Observed burst, approximately 15:33–15:41 +08:
- raw tokens: 672,550
- prompt tokens: 608,789
- completion tokens: 63,761
- cache hit: 504,448
- cache miss: 104,341
- measured input cache hit rate: 82.86%

This proved that good cache hit alone does not prevent a stale benchmark process from producing unnecessary cost.

The stale Hindsight service/client path was stopped. Large external runs must now also survive provider-side scope guards; service availability alone is not permission to continue unlimited paid work.

## DeepSeek dashboard reconciliation

The user dashboard screenshot around 15:39 +08 showed:
- total: 1,905,143
- input cache hit: 622,843
- input cache miss: 1,061,016
- output: 221,284

Local ledger crossed ~1.905M at about 15:32:59 +08, indicating the dashboard was roughly six minutes behind during the high-throughput burst. The apparent local-vs-dashboard gap was therefore not evidence of duplicate accounting.

## Controls implemented

### Research gateway

`governance/research_api.py` now provides:

- durable `budget_scope` and request-size fields in the SQLite ledger;
- normalized scopes so numbered cases do not evade a family budget;
- 15-minute per-scope circuit breaker:
  - 300k raw tokens
  - 100k cache-miss tokens
  - 75k output tokens
  - 150 calls
- policy-epoch per-scope ceiling:
  - 600k raw tokens
  - 200k cache-miss tokens
  - 150k output tokens
  - 300 calls
- maximum single conservative reservation: 75k tokens;
- existing UNKNOWN fail-closed reservation semantics preserved;
- benchmark weekday Beijing peak-hour block;
- cache telemetry coverage and CNY cost-range reporting;
- `report --hours ... --limit ...` grouped cost diagnostics.

The policy epoch ensures historical calls remain visible in reporting without immediately consuming newly introduced scope ceilings.

### OpenAI-compatible proxy

`governance/research_api_proxy.py` now:

- requires `Authorization: Bearer local-budget-proxy:<tag>` for external paid clients;
- rejects untagged external requests locally before provider access;
- maps the tag directly to a durable `proxy:<tag>` budget scope;
- caps smoke-phase proxy completion requests at 8192 tokens;
- continues to reject streaming and tool/function calls.

A live untagged request returned HTTP 429 locally as expected.

### Prompt/cache contract

`WORKER_ENTRY.md` and `SAME_TURN_CONTINUATION.md` now require future repeated experiments to:

- keep frozen system/schema/few-shot material at the start;
- place case IDs, timestamps, batch numbers and variable benchmark payload later;
- preserve exact stable prefixes where scientific semantics allow;
- avoid changing frozen protocols merely to improve cache statistics;
- treat cost-guard rejection as a real stop condition rather than changing purpose/tag to evade it.

## Regression

Governance regression after the controls:

- 55 tests
- 55 PASS
- 0 FAIL

New tests cover normalized family scopes, rolling cache-miss/call limits, epoch limits, single-request reservation limits, benchmark peak blocking, cost reporting, and proxy tag enforcement.

## Historical usage report

After metadata-only scope backfill of 1,614 historical rows:

- historical token counts were not changed;
- remaining rows without budget scope: 0.

24h report at the checkpoint:
- raw: 2,916,075
- prompt: 2,588,816
- completion: 327,259
- measured cache hit: 815,355
- measured cache miss: 582,458
- hit rate on measured prompt tokens: 58.33%
- cache telemetry coverage: 53.99% of prompt tokens

Largest scopes:
- `proxy:hindsight`: 921,698 raw, 82.27% measured cache hit
- `proxy:legacy-untagged`: 620,827 raw, historical telemetry unavailable
- next-largest direct research families are each roughly 25k–50k raw

The legacy untagged proxy bucket can no longer grow under the new proxy policy.

## Hindsight cache/cost findings

### Stable repeated synthetic retain

`T19_HINDSIGHT_CACHE_PROBE_20261027.json`:
- 3,153 prompt tokens
- 2,944 cache-hit
- 209 cache-miss
- 93.37% cache hit
- both user- and assistant-origin facts recalled
- deletion verified empty

### Public LongMemEval-S #499 gold session

Default Hindsight settings:
- raw: 7,947
- prompt: 7,419
- completion: 528
- hit: 6,144
- miss: 1,275
- hit rate: 82.81%
- assistant-origin gold retrieved
- final cleanup empty

### Causal-link extraction disabled A/B

Isolated port 18889, same public session:
- raw: 6,887
- prompt: 6,437
- completion: 450
- hit: 4,096
- miss: 2,341
- hit rate: 63.63%
- assistant-origin gold still retrieved
- final cleanup empty

Although disabling causal links reduced raw tokens by ~13.3% and completion by ~14.8%, it increased cache-miss tokens by 1,066. Under the current pricing structure this single matched probe is **more expensive**, not cheaper. Therefore the optimization is rejected; Hindsight's default causal-link setting remains unchanged pending stronger evidence.

## Decisions

1. Do not optimize for raw tokens in isolation.
2. Do not adopt `retain_extract_causal_links=false` from this A/B.
3. Do not enlarge Hindsight chunk size merely to reduce repeated cache-hit prefix tokens; cache-hit input is already cheap and the scientific comparison could change.
4. Do not rewrite completed/frozen experiment prompts solely for cache.
5. Optimize future prospective runs through stable prefixes, bounded output, batching where scientifically equivalent, tagged scopes, and off-peak execution.
6. Keep smoke at 5M and benchmark at 95M locked.
7. External service startup must not be allowed to revive unbounded stale benchmark work; gateway scope/epoch ceilings are the final circuit breaker.

## Operational commands

```powershell
py -3.11 governance\research_api.py status
py -3.11 governance\research_api.py report --hours 24 --limit 30
py -3.11 -m unittest discover -s governance -p "test_*.py" -q
```

See also: `governance/TOKEN_COST_POLICY_20261027.md`.


## Final proxy anti-tag-rotation validation

Registered external proxy tags are now explicitly limited to:
- `hindsight`
- `mem0oss`
- `graphiti`

A live loopback negative test using `rotated-tag` returned HTTP 429. SQLite `calls` row count was 1669 before and 1669 after (delta 0), proving rejection occurred before any governed provider reservation/call.

Final governance regression after this addition: 57/57 PASS.

## Hindsight causal-link A/B actual-cost interpretation

Using the frozen peak price snapshot:

- default causal=true session47 probe: approximately CNY 0.007020
- causal=false session47 probe: approximately CNY 0.008446

The causal=false variant was about 20.3% more expensive on this matched probe despite using fewer raw/output tokens. It is therefore rejected as a cost optimization.
