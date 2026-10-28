# T19 Graphiti Local Synthetic Smoke — 2026-10-27

## Status

**PASS — synthetic retain/search/delete gate.**

This is a local integration and cost smoke only. It is not a LongMemEval quality result and does not unlock the benchmark phase.

## Frozen deployment

- Graphiti repo: `D:\dsh-fish\external\graphiti`
- commit: `2b5db9e139b2627c3ba18ff55f9181569b0d8224`
- graphiti-core: 0.31.2
- Graphiti REST: loopback `127.0.0.1:18083`
- Neo4j: Community 5.26.32 LTS, project-isolated, loopback Bolt `17687` / HTTP `17474`
- Neo4j archive SHA256: `00eca54f38f601b3adb596611505280a4784d9726c6df5f0b72b7a4a04cc87ec`
- Embeddings: local `BAAI/bge-small-en-v1.5`, loopback OpenAI-compatible endpoint `127.0.0.1:18082/v1`, 384 dimensions
- LLM: governed `deepseek-flash` through `127.0.0.1:18081/v1`
- cross-encoder: fail-closed; OmniMemEval basic search uses Graphiti hybrid+RRF path
- Neo4j usage reporting disabled; Graphiti telemetry disabled.

## Compatibility work required

The current Graphiti reference server and the frozen OmniMemEval adapter had version drift:

1. OmniMemEval requires synchronous `POST /messages/sync`; the current reference server only exposed asynchronous `POST /messages`.
   - Added a thin compatibility endpoint that sequentially awaits the native `graphiti.add_episode()` path.
2. Current Graphiti structured output uses OpenAI `responses.parse`; XiaoYu governance proxy intentionally exposes only `chat/completions`.
   - Added a REST-layer transport shim using `response_format={type:json_object}`.
   - The response model's Pydantic JSON Schema is appended as an explicit formatting instruction because Graphiti's original prompts rely on `responses.parse` for schema injection.
3. Graphiti defaults to 16,384 completion tokens; smoke policy caps proxy completions at 8,192.
   - Governed transport clamps max completion to 8,192 instead of loosening policy.
4. Graphiti LLM client normally retries provider failures twice.
   - Governed subclass uses `MAX_RETRIES=0` so a comparator failure cannot multiply UNKNOWN reservations.

These are deployment/transport compatibility changes; the extraction prompts, graph algorithms, hybrid retrieval, and native `add_episode()` logic are unchanged.

## Synthetic result

Evidence:
`plans/T19_GRAPHITI_SYNTHETIC_SMOKE_20261027.json`

Synthetic facts:
- user favorite tea = oolong tea
- assistant restaurant recommendation in Florence = Trattoria Sostanza

Observed:
- before ingest: 0 nodes / 0 relationships
- after ingest: 7 nodes / 8 relationships
- tea search contains `oolong`: YES
- restaurant search contains `Sostanza`: YES
- final cleanup: 0 nodes / 0 relationships
- ingest time: 17.334 s
- PASS: true

Governed paid calls for the successful smoke:
- calls: 7
- COMMITTED: 7
- UNKNOWN: 0
- RESERVED: 0
- raw tokens: 12,093
- prompt tokens: 11,648
- completion tokens: 445
- cache hit: 512
- cache miss: 11,136
- cache hit rate: **4.40%**

## Failed integration attempts preserved

Before the successful smoke:
- one run failed on missing `/messages/sync` before any paid call;
- one run was blocked by the 8,192 smoke max-token guard before reservation;
- an earlier structured-output attempt generated three `proxy:graphiti` UNKNOWN reservations (17,490 each) because the provider adapter returned RuntimeError and Graphiti's default LLM retries produced three attempts.

Those UNKNOWN reservations remain conservatively charged. They are not cleared because provider billing could not be proven absent.

## Lead interpretation

Graphiti is now locally runnable and passes the synthetic retain/search/delete/cleanup gate, but its successful synthetic workload used seven paid LLM calls for only two messages and showed low prompt-cache reuse. Therefore a full 50-session #499 run is not justified yet.

Next gate: run only the public #499 gold-bearing session 47 through the upstream OmniMemEval Graphiti adapter, confirm assistant-origin retrieval and cleanup, then use measured cost to decide whether any larger matched smoke fits the remaining smoke/runtime guards.
