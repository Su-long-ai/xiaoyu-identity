# XiaoYu DeepSeek Token / Cost Control Policy — 2026-10-27

This document records the Lead-level cost controls for paid research under `D:\dsh-fish`.

## Goal

Optimize **actual DeepSeek cost**, not raw-token optics. DeepSeek V4.1 Flash charges cache-hit input, cache-miss input, and output at very different rates, so cache miss and unnecessary output are the primary cost targets.

Current frozen provider: `deepseek-flash` / DeepSeek-V4.1-Flash-1017, non-thinking, temperature 0.

Official pricing snapshot verified 2026-10-27 (CNY / 1M tokens):

| Token class | Off-peak | Peak |
|---|---:|---:|
| input cache hit | 0.02 | 0.04 |
| input cache miss | 1.00 | 2.00 |
| output | 4.00 | 8.00 |

Weekday Beijing peak windows are 09:00–12:00 and 14:00–18:00, excluding Chinese public holidays. The policy conservatively treats those weekday windows as peak; future benchmark work is blocked there unless Lead explicitly changes policy.

## Hard runtime guard

All paid calls continue to pass through `governance/research_api.py`. External OpenAI-compatible frameworks additionally pass through `governance/research_api_proxy.py`.

From the policy epoch stored in `policy.json`, every normalized budget scope has:

- rolling window: 15 minutes;
- rolling raw-token ceiling: 300,000;
- rolling cache-miss ceiling: 100,000;
- rolling output ceiling: 75,000;
- rolling call ceiling: 150;
- epoch raw-token ceiling: 600,000;
- epoch cache-miss ceiling: 200,000;
- epoch output ceiling: 150,000;
- epoch call ceiling: 300;
- single conservative reservation ceiling: 75,000;
- external proxy smoke completion ceiling: 8,192 tokens.

A call is rejected **before provider access** if its reservation would violate a raw-token ceiling. Cache-miss/output ceilings stop subsequent calls once observed committed usage reaches the ceiling. UNKNOWN outcomes remain fail-closed through their full reservation.

The global 5M smoke / 95M locked benchmark split remains unchanged. These scope guards are additional ceilings, not replacements.

## External framework tagging

External clients must use a local non-secret key in this form:

`Authorization: Bearer local-budget-proxy:<tag>`

Allowed tags contain only letters, digits, dot, underscore and hyphen, max 64 chars. Untagged proxy calls are rejected before provider access.

The tag becomes the durable scope, e.g. `proxy:hindsight`, `proxy:mem0oss`. For large or special runs, prefer a more specific tag so Lead can intentionally isolate its budget.

## Cache-friendly prompt contract

For repeated model-controlled experiments, keep the byte prefix stable:

1. Put frozen instructions, schema and few-shot examples first, preferably in the system message.
2. Put case-specific text, IDs, dates and benchmark payload **after** the invariant prefix, normally in the final user message.
3. Do not prepend timestamps, random IDs, batch numbers or per-case metadata before the invariant instructions.
4. Reuse the exact frozen system string across the whole batch; avoid semantically irrelevant whitespace/serialization changes.
5. JSON payloads should use deterministic serialization where scientific semantics permit it.
6. Use one stable `budget_scope` for one experimental family even if `purpose` contains case numbers.
7. Do not modify a frozen scientific prompt merely to improve cache if that would invalidate an existing comparison. New prospective runs may adopt the cache-friendly layout and must record the change.

Many current T04/HaluMem scripts already follow the correct pattern: fixed system message first, dynamic JSON/user payload second. Completed evidence is not rewritten merely to improve historical cache statistics.

## Reporting

`py -3.11 governance\research_api.py status`

shows global raw budget, cache telemetry coverage, cache hit rate, a CNY cost range, and active guard thresholds.

`py -3.11 governance\research_api.py report --hours 24 --limit 30`

groups usage by normalized scope and reports raw, input, output, cache hit/miss, telemetry coverage and cost range.

Historical calls predating cache telemetry can never be reconstructed exactly. Cost reporting therefore gives a lower/upper range: unmeasured input is treated as off-peak cache hit for the lower bound and peak cache miss for the upper bound.

## Benchmark launch rule

The 95M benchmark phase remains locked. Even after a future explicit unlock, weekday Beijing peak calls are blocked by default. Large benchmark execution should use off-peak pricing unless Lead deliberately records a reason to override the policy.

A benchmark service being online is not permission for an old client to resume unlimited work. The scope ceilings are the final provider-side circuit breaker.
