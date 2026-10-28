# T19 Hindsight Matched LongMemEval #499 Checkpoint — 2026-10-27

## Status

**MATCHED RETRIEVAL SMOKE COMPLETE (single public LongMemEval item only).**

This checkpoint records a controlled self-hosted Hindsight result on LongMemEval-S item #499. It is not an E2/E3 claim and does not unlock the 95M benchmark phase by itself.

## Frozen comparison item

- Dataset: local OmniMemEval LongMemEval-S cleaned copy already frozen by the project.
- Item index: `499`
- Category: `single-session-assistant`
- Question: asks for the Jamaican/Caribbean snapper dish with fruit that the assistant previously recommended.
- Golden answer: `Grilled Snapper with Mango Salsa`
- Conversation size: 50 sessions, 475,890 total message-content characters.
- Gold-bearing source: session index 47; assistant-origin evidence.

## Hindsight configuration

- Backend: `hindsight-api-slim 1.1.0`
- Database: embedded/local project deployment `pg0://xiaoyu-hindsight-t19`
- API: `http://127.0.0.1:18888`
- Embeddings: local `BAAI/bge-small-en-v1.5`
- Reranker: RRF
- LLM: non-thinking DeepSeek Flash through the governed local proxy
- Governed proxy: `http://127.0.0.1:18081/v1`
- Paid-call purpose tag: `proxy:hindsight`
- Temperature: 0
- Retain mode: synchronous, per-session
- OmniMemEval top-k: 20
- Recall budget: high
- Recall chunks enabled

Local run configuration:
`external/OmniMemEval/.hindsight_local_t19.env`

## Pre-flight evidence

### Repeated synthetic retain/cache probe

Evidence:
`plans/T19_HINDSIGHT_CACHE_PROBE_20261027.json`

- 1 governed Hindsight paid call
- prompt tokens: 3,153
- completion tokens: 175
- raw tokens: 3,328
- cache hit: 2,944
- cache miss: 209
- measured cache hit rate: **93.37%**
- user-origin synthetic fact recalled correctly
- assistant-origin synthetic fact recalled correctly
- delete succeeded; final memory count = 0

### Real public #499 gold-session adapter probe

Evidence:
`plans/T19_HINDSIGHT_LME499_SESSION47_ADAPTER_PROBE_20261027.json`

- Ingested only public session 47 before the full matched run.
- 4 memories created.
- Gold phrase was present in the upstream OmniMemEval Hindsight search context.
- Assistant-origin phrase was present.
- 2 governed Hindsight paid calls.
- raw tokens: 7,947
- cache hit rate: **82.81%**
- cleanup succeeded; final memory count = 0.
- rough 50-session projection at the session-47 rate: 397,350 raw tokens. This projection was intentionally treated only as a gate, not as a final cost estimate.

## Full matched #499 run

Version:
`hindsight_local_ds_assistant_499_smoke_20261027`

Result directory:
`external/OmniMemEval/results/lme/hindsight-hindsight_local_ds_assistant_499_smoke_20261027`

### Reliability / resume event

The first full attempt ingested sessions 0–36 successfully, then the local Hindsight API process terminated while session 37 was starting. OmniMemEval observed:

`ConnectionResetError(10054, 'remote host forcibly closed an existing connection')`

No provider-ledger UNKNOWN or RESERVED call remained from this failure.

The per-session durable checkpoint contained exactly:

`499_0 ... 499_36`

Session 37 was **not** falsely marked complete. Hindsight was restarted, health returned HTTP 200, and the same OmniMemEval version was resumed without `--restart-unit`. The harness skipped the 37 checkpointed sessions and continued from session 37. This is evidence that the existing per-session checkpoint path prevented duplicate re-ingestion and duplicate paid work for sessions 0–36.

The resumed run used one short conversation-level transient retry allowance (1 retry, 2-second fixed delay), but the resumed execution completed without needing another restart.

### Retrieval outcome

- Completed 50/50 sessions.
- Search status: **success**
- Search duration: **787.41 ms**
- Returned search context: **152,790 characters**
- Golden answer exact phrase present: **YES**
- `Grilled Snapper with Mango Salsa` appears in the **3rd returned memory block** in the flattened Hindsight context.
- The returned block retains the original assistant-origin conversation evidence containing the five snapper dishes.
- Final delete: **ok**
- Direct post-run bank check: HTTP 200 with `items=[]`, `total=0`

Result evidence:
- `.../tmp/hindsight_lme_search_results_499.json`
- `.../hindsight_lme_streaming_stats.json`
- `.../hindsight_lme_search_status.json`

## Governed token accounting

Accounting baseline: provider ledger rows strictly after rowid 1270, which was captured immediately before the full matched run.

This accounting deliberately includes:
- the successful paid work before the first Hindsight process termination,
- work from the resumed sessions,
- Hindsight LLM connection-verification traffic after restart,

so it is a conservative operational cost for obtaining this matched result rather than a cherry-picked success-only cost.

- Hindsight ledger rows: **216**
- COMMITTED: **216**
- UNKNOWN: **0**
- RESERVED: **0**
- raw tokens: **885,538**
- prompt tokens: **798,544**
- completion tokens: **86,994**
- cache hit tokens: **662,656**
- cache miss tokens: **135,888**
- measured prompt-cache hit rate: **82.98%**

After this run, project governed research budget status was:

- active phase: smoke
- total/smoke used-or-reserved: **2,923,607 / 5,000,000**
- smoke remaining: **2,076,393**
- benchmark phase: **LOCKED**
- benchmark allocation: 95M remains unavailable until comparator stability gates are satisfied.

## Matched single-item comparison

For LongMemEval-S #499 only:

| Backend | Result |
|---|---|
| XiaoYu V2 `literal_chunks` compatibility baseline | missed the gold evidence |
| Mem0 OSS matched smoke | retrieved gold at rank 2 |
| Hindsight matched smoke | retrieved gold in returned memory block 3 |

This is **not** sufficient to rank systems overall. It demonstrates that the current XiaoYu compatibility baseline has a concrete assistant-origin recall blind spot that two external memory systems can recover on this public item.

## Lead interpretation

1. Hindsight has now passed the handoff gates that were still open at 15:05: repeated-cache probe, OmniMemEval adapter/cleanup, cost estimation, and one full matched #499 retrieval smoke.
2. Hindsight cannot yet be called benchmark-stable: the API process terminated once during the 50-session ingest. Durable per-session resume worked correctly, but process-liveness reliability remains a deployment risk to record for larger runs.
3. The project should not replace its provenance-aware identity architecture with Hindsight. The useful external evidence is specifically around richer assistant-origin extraction/retrieval and durable ingestion checkpointing.
4. Benchmark phase stays locked. The next T19 gate is one architecturally different third self-hosted comparator with local cleanup and cost visibility, followed by a small frozen matched comparison before any large benchmark unlock.
5. Event-ledger correction is independently submitted as `sub-a79b217c6b514957` and must finish independent audit; Lead should not self-accept it.

## Next actions

- Preserve this Hindsight checkpoint as the matched single-item evidence.
- Investigate/record Hindsight process-liveness failure before any larger Hindsight sweep; do not confuse successful resume with uninterrupted stability.
- Select one third self-hosted comparator from the already-supported/local-feasible set; avoid broad framework collection.
- Keep the 95M benchmark allocation locked until the third comparator passes synthetic retain/search/delete and a small cost gate.
- Consume the independent audit result for `sub-a79b217c6b514957` when available; do not duplicate the event-ledger research.
