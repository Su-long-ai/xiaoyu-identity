# T19 Assistant-Origin Comparator Freeze — 2026-10-27

## Decision scope

This checkpoint freezes the **small matched evidence needed to decide the assistant-origin memory requirement**. It is not an overall memory-system leaderboard, does not claim E2/E3, and does not unlock the 95M benchmark phase.

Frozen public probe: LongMemEval-S item #499, whose gold-bearing evidence is an assistant recommendation in session 47. Gold answer: `Grilled Snapper with Mango Salsa`.

## Matched evidence

| Backend | Scope actually run | Assistant-origin gold | Cleanup / isolation | Operational note |
|---|---|---|---|---|
| XiaoYu V2 `literal_chunks` compatibility baseline | frozen LongMemEval retrieval baseline | **MISS** on #499; sampled assistant evidence 0/5 | isolated evaluation state | active-memory policy structurally omits assistant-origin evidence |
| Mem0 OSS | official OmniMemEval #499 streaming smoke | **PASS**, target memory approximately rank 2 and attributed to assistant | vector + session-row cleanup verified | richer extraction works, but materially higher latency/compute than XiaoYu keyword baseline |
| Hindsight 1.1.0 | full #499, 50/50 sessions | **PASS**, gold in returned memory block 3 | final bank empty | 885,538 raw tokens, 82.98% measured prompt cache hit; service died once but durable per-session resume prevented duplicate ingest |
| Cognee 1.6.5-local | gold-bearing session 47 cost/quality gate | **PASS** | final dataset count 0 | post transport-fix: 7 calls, 11,894 raw, 1,128 cache-miss, 85.97% measured cache hit |
| Graphiti 0.31.2 | synthetic PASS; real session47 attempted | **NO QUALITY RESULT** | synthetic and failed-attempt cleanup verified | real session hit the XiaoYu 100k cache-miss circuit breaker before completion; do not raise the guard merely to force a result |

## Cognee compatibility fix

The frozen Cognee repo exposed a transport bug in the local comparison path: `NativeLiteLLMAdapter` stored the configured 8,192-token output ceiling but did not pass it to ordinary LiteLLM structured-output calls. Provider requests therefore defaulted to 1,024 tokens and large KnowledgeGraph JSON was truncated, causing validation retries.

Local compatibility patch:
- only propagates the already-configured max token ceiling when the call has no explicit override;
- does not change prompts, schemas, graph algorithms, benchmark data or retrieval;
- explicit per-call max token remains authoritative;
- focused test file: 33/33 PASS;
- provider ledger proves pre-fix requests used 1,024 and post-fix requests used 8,192;
- same-session A/B preserved retrieval/cleanup and reduced calls 10→7, raw 23,834→11,894, cache miss 3,658→1,128;
- patch SHA256: `AAC4B36641183AED55CAD64C12A6EF18DF7BE8825D4AB974953F482AA5BF8E86`;
- patch file: `external/cognee_t19_max_tokens_compat.patch`.

## What the external comparison proves

The evidence is sufficient to reject this design assumption:

> "Only user-origin statements need to be retrievable as long-term evidence."

The same public assistant-origin fact is missed by XiaoYu's literal compatibility baseline and recovered by three architecturally different external systems: Mem0, Hindsight and Cognee.

This does **not** prove that every assistant message should become a user memory. Doing that would create a different, dangerous failure mode: assistant guesses, suggestions or hallucinations could be promoted into user state.

The requirement is instead:

> XiaoYu must preserve and retrieve eligible assistant-origin evidence with explicit source role and provenance, while keeping source authority separate from semantic truth/current user state.

## Frozen architecture requirements induced by T19

1. **Source-role preservation**
   - Every retrievable evidence object carries immutable source identity and role: user / assistant / system/tool where applicable.
   - Assistant-origin evidence never masquerades as a direct user assertion.

2. **Assistant evidence is retrieval-eligible, not automatically state-authoritative**
   - Recommendations, prior explanations and shared conversational commitments may be useful evidence.
   - A model-generated guess does not become a user preference simply because it is stored.

3. **Semantic projection remains validated**
   - State-changing events require the accepted semantic-event projector plus deterministic evidence/source validation.
   - Unsupported or mismatched evidence pointers are quarantined/abstained rather than attached.

4. **Raw event/provenance log remains source of truth**
   - Derived memories/index entries are rebuildable projections.
   - Stable event identity and conflict quarantine follow the accepted event-ledger E1.

5. **Global retrieval must not have the newest-1000 structural blind spot**
   - The accepted long-tail E1 proves the current cap must be replaced.
   - The replacement must index eligible user and assistant evidence explicitly rather than inherit source-role ambiguity.

6. **Context packing must expose provenance**
   - Answering receives source labels / evidence identity, not a flat bag of memory text.
   - Answer correctness must not authorize a bad source pointer.

7. **Deletion and archive semantics apply to derived assistant evidence too**
   - Rebuild/delete/restore must not leave inaccessible or stale projections that can later reappear.

## Comparator disposition

- **Mem0**: retain as external reference for assistant-aware extraction and memory attribution.
- **Hindsight**: retain as external reference for assistant-aware extraction/retrieval and durable ingestion checkpoints; process liveness remains a deployment warning.
- **Cognee**: retain as the third architecturally different graph/vector comparator; local max-token compatibility patch is required for fair governed DeepSeek runs.
- **Graphiti**: retain as a synthetic/architectural reference only for now; real matched expansion is cost-disqualified under the current guard.
- **XiaoYu custom layers**: keep only where accepted evidence demonstrates identity/provenance/privacy semantics or reproducible quality advantages unavailable from simply adopting an external backend.

## Benchmark decision

The 95M benchmark allocation remains **LOCKED**.

The project now has enough external evidence to freeze the assistant-origin architecture requirement without paying for another full 50-session comparator run. The next value is in integrating/falsifying the XiaoYu candidate pipeline under small prospective gates, not collecting more frameworks.
