# T19 Cognee Local Comparator Checkpoint — 2026-10-27

## Status

**LOCAL SYNTHETIC PASS + PUBLIC LME #499 GOLD-SESSION PASS.**

This is a controlled self-hosted comparator gate. It is not a full LongMemEval benchmark and does not unlock the 95M benchmark phase.

## Frozen deployment

- repository: `D:\dsh-fish\external\cognee`
- upstream/local commit before compatibility patch: `37f788bd287750e10d7610173e5332b3843f6ebd`
- package: Cognee 1.6.5-local
- clean isolated venv: `external\cognee_venv_t19`
- API: loopback `127.0.0.1:18084`
- relational DB: SQLite under `external\cognee_t19_run\system\databases`
- vector DB: LanceDB
- graph DB: Ladybug
- embedding: local FastEmbed `BAAI/bge-small-en-v1.5`, 384 dimensions
- auth/multi-tenant: disabled for loopback comparator
- LLM: governed non-thinking `deepseek-flash` through `127.0.0.1:18081/v1`
- proxy scope: `proxy:cognee`
- temperature: 0
- OmniMemEval search: `GRAPH_COMPLETION`, `onlyContext=true`
- benchmark allocation remains locked.

## Environment / install finding

The pre-existing `external\cognee_venv` had broken/incomplete package metadata and could not resolve the editable install. It was not repaired in place. A clean isolated venv was created and `pip check` reports no broken requirements.

First startup performed the normal Cognee SQLite migration chain and downloaded/cached the local BGE model. Health after startup:
- `/`: HTTP 200
- `/health`: HTTP 200, ready/healthy, version 1.6.5-local
- initial datasets: `[]`

## Synthetic retain/search/delete gate

Evidence:
`plans/T19_COGNEE_SYNTHETIC_SMOKE_20261027.json`

Synthetic facts:
- user favorite tea = oolong tea
- assistant restaurant recommendation = Trattoria Sostanza

Observed:
- before dataset count: 0
- after retain: 1
- oolong retrieved: YES
- Sostanza retrieved: YES
- final dataset count after delete: 0
- ingest: 14.207 s
- governed calls: 3
- raw tokens: 2,525
- prompt: 2,028
- completion: 497
- cache hit: 0
- cache miss: 2,028
- UNKNOWN/RESERVED: 0
- PASS: true

## Public LongMemEval-S #499 gold-session gate

Evidence:
`plans/T19_COGNEE_LME499_SESSION47_COST_GATE_20261027.json`

Frozen public item:
- dataset index 499
- category used by project: single-session-assistant
- gold-bearing session index: 47
- source session id: `answer_ultrachat_399000`
- 12 turns / 4,300 chars
- question asks for the fruit-containing Jamaican snapper dish previously recommended by the assistant
- gold: `Grilled Snapper with Mango Salsa`

Observed:
- dataset before: 0
- dataset after ingest: 1
- ingest: 25.349 s
- search: 1,281 ms
- returned context: 14,633 chars
- gold exact phrase present: YES
- assistant-origin phrase present: YES
- final dataset after delete: 0
- cleanup error: none
- governed calls: 10
- COMMITTED: 10
- UNKNOWN/RESERVED: 0
- raw tokens: 23,834
- prompt: 16,330
- completion: 7,504
- cache hit: 12,672
- cache miss: 3,658
- measured input cache hit: 77.60%
- PASS: true

A naive 50-session projection from this one session is 1,191,700 raw tokens. This is only a cost gate; it is not used as an estimate accurate enough to authorize a full run.

## Reliability defect found

The real session log showed several `KnowledgeGraph` JSON validation retries caused by output truncation. Provider ledger rows confirm every Cognee structured-output request was sent with `max_tokens=1024`; several responses ended exactly at 1,024 completion tokens.

Cognee's active configuration was independently checked:
- configured `llm_max_completion_tokens`: 8,192
- resolved Cognee token ceiling: 8,192
- `llm_args`: temperature only
- LiteLLM has no model-cost entry forcing 1,024 for `openai/deepseek-flash`

Root cause: `NativeLiteLLMAdapter` stores `self.max_completion_tokens` but ordinary chat/structured-output methods did not propagate it into LiteLLM kwargs. Therefore provider/LiteLLM defaulted to 1,024.

A minimal local compatibility patch is in progress: when no per-call `max_tokens` is supplied, propagate the adapter's configured ceiling. The patch does not change prompts, schemas, source data, extraction algorithm or retrieval algorithm. It only prevents transport-level output truncation. Focused unit coverage was added for default propagation and explicit per-call override precedence.

Do not expand Cognee beyond the single-session gate until this reliability patch passes focused tests and a matched session-47 rerun.

## Comparator interpretation

Cognee is materially different from Mem0/Hindsight and has now demonstrated that assistant-origin #499 evidence can be retained and retrieved with local graph/vector storage. It is dramatically cheaper on the single-session gate than Graphiti's blocked real-session attempt, but more LLM-intensive than a literal XiaoYu retrieval path.

Current external evidence on the same assistant-origin blind spot:
- XiaoYu V2 literal compatibility baseline: misses assistant-origin evidence structurally
- Mem0 OSS: retrieves gold
- Hindsight: retrieves gold
- Cognee: retrieves gold on gold-bearing session
- Graphiti: synthetic works, but real session cost gate hit the project's cache-miss circuit breaker before a quality result

This is already sufficient to reject the assumption that XiaoYu's user-only active-memory policy is an adequate general long-term retrieval design. It does not establish an overall winner among external systems.


## Transport max-token compatibility patch — VALIDATED

The local compatibility patch is now validated.

Patch scope:
- file: `cognee/infrastructure/llm/structured_output_framework/litellm_native/native_adapter.py`
- behavior: when a call does not explicitly set `max_tokens`, pass the adapter's already-configured `self.max_completion_tokens` to LiteLLM;
- explicit per-call `max_tokens` continues to override the adapter ceiling;
- no prompt, schema, benchmark data, graph extraction algorithm or retrieval algorithm changed.

Focused upstream/local unit test file:
- `cognee/tests/unit/infrastructure/llm/test_litellm_native.py`
- result: **33/33 PASS**
- two new tests prove default propagation and explicit override precedence.

Ledger proof:
- pre-fix #499 session47 rows 2040–2049 imply `max_tokens=1024`;
- post-fix rows 2050–2056 all imply `max_tokens=8192`;
- formula: `reserved_tokens - request_bytes - 1024 = max_tokens`.

### Same-session A/B

Post-fix evidence:
`plans/T19_COGNEE_LME499_SESSION47_POSTFIX_20261027.json`

| Metric | pre-fix | post-fix |
|---|---:|---:|
| gold retrieved | yes | yes |
| cleanup empty | yes | yes |
| governed calls | 10 | 7 |
| raw tokens | 23,834 | 11,894 |
| prompt tokens | 16,330 | 8,040 |
| completion tokens | 7,504 | 3,854 |
| cache hit | 12,672 | 6,912 |
| cache miss | 3,658 | 1,128 |
| measured hit rate | 77.60% | 85.97% |
| ingest seconds | 25.349 | 33.405 |
| search ms | 1,281 | 1,619 |

Cost/reliability effect:
- raw tokens: **-50.1%**
- cache-miss tokens: **-69.2%**
- completion tokens: **-48.6%**
- calls: **-30.0%**
- no `KnowledgeGraph` JSON validation-retry warnings appeared in the post-fix server log;
- quality/cleanup gates remained unchanged.

The wall-clock ingest/search timing was slower on this single rerun, so the patch is accepted as a **reliability and provider-cost fix**, not a latency optimization.

The post-fix one-session naive 50-session projection is 594,700 raw tokens, approximately half of the pre-fix projection. This remains only a rough cost gate and does not authorize a 50-session run.
