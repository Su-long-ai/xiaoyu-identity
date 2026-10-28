# T19 Hindsight Local Smoke — 2026-10-27

## Frozen environment
- Distribution: hindsight-api-slim 1.1.0
- CLI/API version: Hindsight v1.1.0
- Isolated venv: D:\dsh-fish\external\hindsight_venv
- Isolated run dir: D:\dsh-fish\external\hindsight_t19_run
- Database: embedded pg0 instance pg0://xiaoyu-hindsight-t19
- HTTP bind: 127.0.0.1:18888 only
- Vector: pgvector
- Text search: native
- Embeddings: local BAAI/bge-small-en-v1.5
- Reranker: rrf (model-free passthrough)
- LLM: deepseek-flash through http://127.0.0.1:18081/v1 only
- Proxy tag: local-budget-proxy:hindsight
- LLM max concurrent: 1; retries: 0; temperature: 0
- retain max completion tokens: 4096

## Zero-model deployment
With LLM_PROVIDER=none:
- embedded PostgreSQL started successfully
- full first-run migrations completed
- REST API and MCP started
- GET /health => HTTP 200, database connected
- GET /openapi.json => HTTP 200
- no paid DeepSeek calls required

A Hindsight 1.1.0 inconsistency was found: reranker provider 'none' is rejected
although some messages/documentation suggest it. The supported model-free
passthrough is 'rrf', which works.

## DeepSeek-mode startup
Hindsight uses an OpenAI-compatible client pointed only at the capped local
proxy. Startup connection verification used one tiny 8-input + 1-output call.

The first retain attempt was rejected locally because Hindsight defaults
RETAIN_MAX_COMPLETION_TOKENS to 64,000 while the XiaoYu research proxy permits
at most 32,768. No provider tokens were consumed by that rejected request.
The controlled config now uses 4,096 output tokens (> retain chunk size 3,000).

## Synthetic retain / recall / delete smoke
Bank: hindsight_synthetic_smoke_20261027

Input document:
- User: My favorite tea is jasmine tea.
- Assistant: For dinner in Rome, I recommend Roscioli.
- context: synthetic two-speaker benchmark conversation
- document_id: synthetic-session-1
- explicit timestamp and synthetic tags

Synchronous retain: HTTP 200.
Provider usage:
- prompt: 3,150
- completion: 165
- total raw: 3,315
- cache hit: 0
- cache miss: 3,150
- reasoning/thoughts: 0

Hindsight extracted two source-role-aware memories:
1. User's favorite tea is jasmine tea | Involving: user
   - type: world
2. Assistant recommended Roscioli for dinner in Rome | Involving: assistant
   - type: experience

Recall question: What tea does the user prefer?
- top-1: jasmine-tea user fact
- semantic score ~0.7917
- keyword score 0.6

Recall question: Which restaurant did the assistant recommend in Rome?
- top-1: Roscioli assistant fact
- semantic score ~0.74045
- keyword score 0.5

The stored memory rows preserve:
- source document_id
- context
- mentioned timestamp
- tags
- entities
- extracted speaker role in fact text

DELETE /memories:
- HTTP 200
- deleted_count: 2
- subsequent list: 0 memories

## Interpretation
Hindsight independently confirms the same capability gap exposed by Mem0:
mature memory systems can extract and retrieve assistant-origin information
that XiaoYu V2 currently does not index.

Compared with Mem0, Hindsight also exposes explicit world/experience types,
timestamps, document provenance, tags, semantic/keyword stage scores and
curation APIs. This makes it especially relevant to XiaoYu's provenance,
temporal-state and conflict goals.

This is a synthetic smoke only; no claim of LongMemEval superiority is made.

## Next
1. Repeat a structurally identical synthetic retain with changed facts and
   measure DeepSeek cache hit/miss.
2. Adapt OmniMemEval Hindsight client to this local service with isolated bank
   cleanup verification.
3. Estimate per-session retain cost before running matched LongMemEval #499.
