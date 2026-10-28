# T19 External Memory Benchmark Checkpoint — 2026-10-27

## Frozen inputs

- OmniMemEval upstream commit: `7c79d46e31dd85f3da2509b430bba9406656dd28`
- LongMemEval-S: 500 records, 277,383,467 bytes
- LongMemEval-S SHA256: `D6F21EA9D60A0D56F34A05B609C79C88A451D2AE03597821EA3D5A9678C3A442`
- XiaoYu production identity_core.py is not modified by the benchmark adapter.
- Evaluation state is isolated under `external/OmniMemEval/.xiaoyu_eval_state`.

## Paid-research budget

Owner-approved research cap (raised 2026-10-27): 100,000,000 DeepSeek tokens.
Smoke phase cap: 5,000,000; 95,000,000-token benchmark phase remains locked.
At this checkpoint: 1,147 tokens used-or-reserved:
- 2 COMMITTED calls
- 1 UNKNOWN call retained fail-closed at its full reservation
Historical snapshot below predates the 100M cap increase; ledger usage itself was not reset.

All external OpenAI-compatible model calls must go through
`governance/research_api_proxy.py` on loopback, backed by
`governance/research_api.py`.

## XiaoYu adapter modes

### literal_source
Exact V2 constraint baseline. User turns are indexed literally; assistant turns
are provenance-only. V2 rejects a memory longer than 1500 chars.

On LongMemEval-S indices 0-19:
- completed: 2/20
- failed: 18/20
- all failures: `Memory must be 2-1500 characters`

### literal_chunks
Minimal compatibility baseline, not a claim about current production V2:
- complete original text remains provenance;
- >30,000-char source messages are split into exact provenance event segments;
- retrieval index is split into literal <=1500-char chunks;
- no summarization, no LLM extraction, no assistant-to-user-memory promotion.

Unit tests prove:
- >30,000-char source reconstruction is byte-for-character exact at Python str level;
- every event <=30,000 chars;
- every indexed memory 2..1500 chars;
- assistant-only content does not enter active user memories.

Indices 0-19:
- pipeline completion: 20/20
- answer literal in top-20: 15/20
- answer literal top-1: 10/20
- answer literal top-5: 14/20
- exact user evidence in context: 19/20
- average context: 8,409.5 chars
- average search latency: 42.45 ms

## Stratified retrieval-only sample

Total: 45 questions.

| Type | n | answer literal hit | top1 | top5 | user evidence hit | assistant evidence hit | avg context chars | avg search ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| single-session-user | 20 | 15 | 10 | 14 | 19/20 | 0/1 | 8409.5 | 42.45 |
| multi-session | 5 | 2 | 2 | 2 | 4/5 | — | 11668.4 | 44.07 |
| single-session-preference | 5 | 0* | 0 | 0 | 3/5 | — | 7936.0 | 44.86 |
| temporal-reasoning | 5 | 2 | 2 | 2 | 5/5 | — | 10412.4 | 44.30 |
| knowledge-update | 5 | 3 | 2 | 3 | 5/5 | — | 10211.2 | 49.15 |
| single-session-assistant | 5 | 0 | 0 | 0 | — | 0/5 | 11324.0 | 44.36 |

* Preference gold answers are synthesized preference descriptions, so literal
answer matching is not a valid standalone quality metric; evidence recall is the
more meaningful retrieval-only signal.

## Confirmed defects / limitations

1. Production V2 has a 1500-character active-memory hard limit.
2. Production V2 has a 30,000-character event hard limit.
3. Assistant-origin facts are not indexed as long-term memories, producing a
   structural 0/5 assistant-evidence recall on the sampled assistant questions.
4. Keyword recall often finds evidence but returns large noisy contexts.
5. Temporal questions show evidence recall 5/5 but answer-literal hit only 2/5:
   retrieval and temporal reasoning are separate problems.
6. Multi-session composition similarly cannot be inferred from literal answer
   matching; evidence aggregation/reasoning must be evaluated separately.

## Next work

- Deploy Mem0 OSS as the first external self-hosted comparator:
  local embeddings/vector store; extraction LLM only through the capped proxy.
- Run tiny synthetic Mem0 smoke before any LongMemEval ingestion.
- Then run matched retrieval-only / answer+judge smoke under the same frozen
  DeepSeek non-thinking configuration.
- Keep the 9M benchmark allocation locked until external-framework smoke is stable.


## Mem0 OSS Comparator Update ? 2026-10-27 09:58 +08:00

### Frozen local deployment

- mem0ai 2.2.1
- fastembed 0.9.1
- spaCy 3.8.18 + en_core_web_sm 3.8.0
- local Qdrant via qdrant-client 1.20.0
- embedding: BAAI/bge-small-en-v1.5, 384 dimensions
- Mem0 telemetry explicitly disabled with MEM0_TELEMETRY=False and sample rate 0
- DeepSeek credential is not exposed to Mem0; LLM calls go only to the loopback capped proxy.

### Streaming isolation

Mem0 2.2.1 delete_all(user_id) does not remove its SQLite session-message rows. The local adapter therefore performs vector delete plus same-scope SQLite message delete and verifies both stores are empty. A contradictory-fact smoke passed: jasmine + Roscioli -> delete -> 0 vector memories and 0 session rows -> re-add oolong -> oolong retrieved and jasmine absent.

### Local Qdrant compatibility

OmniMemEval creates one client for ingestion and another for search. Qdrant local mode rejects two independent clients opening the same storage directory in one process. Mem0OssClient now reuses a process-local shared Memory/Qdrant object for identical frozen config. Verification: SAME_MEMORY=True and SAME_QDRANT=True. The failed official run left a complete 50-session checkpoint (499_0 through 499_49); the resumed run skipped all 50 paid adds, completed search, verified final delete, and exited 0.

### Official LongMemEval-S assistant-memory smoke

Index 499:
- question asks for a previously assistant-recommended Jamaican snapper dish with fruit
- gold: Grilled Snapper with Mango Salsa
- official OmniMemEval search status: success
- gold appears in top-20; target assistant memory is the second actual retrieved memory (result-file literal-line calculation reports rank 3 because the 'Conversation memories:' header is also a non-empty line)
- target memory is explicitly attributed_to=assistant
- context: 4,224 chars
- search duration: 17,285.7 ms
- final delete: 56,869.6 ms

The corresponding Mem0 memory says the user was recommended Caribbean snapper dishes including Grilled Snapper with Mango Salsa. This directly demonstrates a viable design for XiaoYu's sampled assistant-memory blind spot, at substantially higher compute/latency cost than XiaoYu's current keyword recall (~40-50 ms in the sampled runs).

### JSON extraction reliability defect and fix

The first 50-session run logged 3 malformed JSON extraction responses. Mem0 continued instead of failing, so those sessions could silently lose extracted memories. Root cause was the XiaoYu local proxy ignoring Mem0's response_format={type: json_object} request.

The proxy/gateway/model adapter now accept only the exact json_object response format and forward it to DeepSeek; arbitrary schemas/tools remain rejected. Governance regression is 44/44 PASS. A standard OpenAI SDK JSON-mode smoke returned parseable {"ok": true}. A fresh post-fix Mem0 run on index 499's real evidence session 47 completed with no parse error, produced 6 memories, contained the gold, retrieved it, and attributed the gold memory to assistant.

### Current paid ledger

After all T19 smoke work above:
- total used or reserved: 846,551 / 10,000,000
- smoke phase: 846,551 / 1,000,000
- smoke remaining: 153,449
- benchmark phase: 9,000,000 tokens, still locked
- calls: 337 COMMITTED, 1 UNKNOWN

No further large paid framework run should use the remaining smoke allowance. The next external backend should be deployed and validated locally/offline first; benchmark unlock remains a separate gate.

### Identity invariants after T19 work

- identity/identity.sqlite3 SHA256: 03679C1CF7CE44C94A9BBE530C3DCAABC0C84ED4BCFFA5A3BDF727F23B70A99C
- identity_core.py SHA256: 23DAFEA0EBC92A3E8DF809332CC8BDE6EDD7F06B812F831C0FCD799340E2B000

Both match the pre-benchmark invariants.
