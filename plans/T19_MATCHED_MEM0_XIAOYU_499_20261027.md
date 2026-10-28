# T19 Matched LongMemEval Assistant-Memory Comparison — 2026-10-27

LongMemEval-S index 499, top-k 20, frozen dataset.

## XiaoYu V2 literal_chunks
- pipeline success across 49 sessions
- gold: Grilled Snapper with Mango Salsa
- gold answer in retrieval context: NO
- exact gold assistant evidence: NO
- context chars: 22,458
- search latency: 59.3 ms
- structural cause: current V2 does not index assistant-origin turns as long-term user memory.

## Mem0 OSS 2.2.1
- local Qdrant + FastEmbed BAAI/bge-small-en-v1.5
- extraction LLM: DeepSeek Flash through capped loopback gateway
- gold answer in retrieval context: YES, rank 2
- exact source wording not preserved because Mem0 stores extracted facts
- context chars: 4,224
- search latency: 17,285.7 ms
- matched memory is marked attributed_to=assistant.

This is direct evidence that an existing framework already solves one current XiaoYu assistant-memory blind spot. It does not prove overall superiority: Mem0 paid extraction used much more compute/tokens and search was roughly 291x slower on this sample.

## Mem0 smoke failure and isolation fix
The first index-499 run used about 611k tokens across 55 proxy calls and then hit a local Qdrant lock because another same-root process was alive. The temporary search result was recovered and is the result above.

The adapter now requires MEM0_OSS_ROOT to be unique per concurrent experiment; the shared env example no longer hardcodes one Qdrant directory. The delete path additionally removes Mem0 2.2.1 SQLite session-message residue and verifies both vector memories and session messages are empty.

Synthetic isolation smoke: 2 memories + 2 session messages before delete -> 0 + 0 after delete.

## Shared smoke-budget snapshot
- used/reserved at ~09:53 +08:00: 746,669 / 1,000,000
- T19 proxy: ~611,414 actual tokens
- T04 parser/ablation/prospective: ~86,863 actual tokens
- remaining usage mainly auditor/OOD and small injection tests
- formal 9M benchmark allocation remains locked.

Decision: do not run a second full Mem0 LongMemEval conversation during smoke; continue offline deployment of additional backends and only tiny paid connectivity tests after each backend is stable.