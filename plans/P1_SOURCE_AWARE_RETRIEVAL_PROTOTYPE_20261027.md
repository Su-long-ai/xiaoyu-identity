# P1 Source-Aware Persistent Retrieval Prototype — 2026-10-27

## Status

**LEAD E0 PROTOTYPE PASS — FORMAL REPLICATION QUEUED AS R09.**

This work is deliberately isolated under:
`governance/lead_workspaces/p1_source_aware_retrieval_20261027`

It does not modify production `identity_core.py`, the real identity database or private conversation data. It makes no paid/model calls.

## Why this prototype exists

Two independently supported defects/requirements now meet at the retrieval layer:

1. Accepted E1 `retrieval.longtail.1000cap` proves V2's newest-1000 candidate truncation makes older active memories structurally unreachable.
2. T19 external comparison proves V2's current long-term-memory policy has an assistant-origin blind spot: Mem0, Hindsight and Cognee recover the same public assistant-origin LongMemEval #499 evidence that the XiaoYu literal compatibility baseline misses.

The design requirement is **not** "store every assistant utterance as user memory". The index must preserve source authority.

## Prototype layout

Side tables in a disposable V2 SQLite store:

- `research_evidence_docs`
  - stable document key
  - `source_event`
  - optional `memory_id`
  - `source_role`
  - `source_kind`
  - `authority`
  - text / priority / status
- `research_evidence_terms`
  - persistent lexical posting list using the existing XiaoYu Chinese-bigram + Latin-token tokenizer
- `research_evidence_suppressed`
  - prototype tombstone for derived-retrieval suppression

Two authority classes are intentionally distinct:

- `confirmed_memory`: active approved/confirmed memory; eligible for current-state retrieval.
- `conversation_history`: assistant conversation evidence; retrievable as prior conversation evidence but **not** current user state.

Raw user transcript is not globally indexed by this prototype, so it does not silently bypass V2's memory-approval policy.

Candidate expansion follows the accepted rarest-posting idea:
- choose the rarest overlapping term;
- if posting DF > 128, return `FALLBACK_HIGH_DF` instead of scanning a huge candidate set;
- a future semantic fallback is a separate gate.

## 3200-document long-tail result

Synthetic disposable corpus:
- 1,600 confirmed user memories;
- 1,600 assistant conversation-history events.

Initial persistent build:
- 3,200 expected docs;
- 3,200 indexed;
- 78,389 posting rows;
- build: 0.218 s on this local run.

### Confirmed user-memory retrieval

90 queries: old / middle / newest = 30 each.

- old: 30/30
- middle: 30/30
- newest: 30/30
- total: **90/90**
- candidate median: 1
- candidate max: 1

### Assistant-history retrieval

90 queries: old / middle / newest = 30 each.

- old: 30/30
- middle: 30/30
- newest: 30/30
- total: **90/90**
- candidate median: 2
- candidate max: 2

Combined query latency:
- median: 5.37 ms
- p95: 13.54 ms

These numbers are only local synthetic lexical measurements, not production latency claims.

## Authority-separation counterexample

Synthetic conversation:
- assistant guess: "I guess your favorite tea is jasmine tea."
- confirmed user memory: "I like oolong tea."

For a broad tea-preference query:

History/evidence mode:
- assistant guess is visible;
- tagged `source_role=assistant`;
- tagged `authority=conversation_history`.

State-only mode:
- assistant guess is excluded;
- confirmed user oolong memory is present;
- tagged `source_role=user`;
- tagged `authority=confirmed_memory`.

This is the core architectural property required by T19:
**assistant evidence can be remembered without being promoted to user truth.**

## Lifecycle / restart gates

Archive:
- archiving a confirmed memory triggers removal of its evidence doc and postings;
- archived target is absent from state retrieval;
- PASS.

Assistant suppression:
- a source-event tombstone immediately removes the derived assistant evidence;
- restart + sync does not resurrect it;
- PASS.

Missed-index recovery:
- a canonical memory write is intentionally committed without the side-index update;
- after restart, idempotent sync inserts the missing evidence doc;
- target is retrievable;
- PASS.

High-DF query:
- 40/40 common-term probes return `FALLBACK_HIGH_DF`;
- no large posting expansion is returned as an answer;
- PASS.

Overall structural prototype: **PASS**.

Evidence:
- `source_aware_persistent_index.py`
- `source_aware_persistent_index_metrics.json`
- `source_aware_memory_cases.jsonl`
- `source_aware_assistant_cases.jsonl`

## Explicit crash-atomicity experiment

A second disposable experiment writes canonical mutation + derived index mutation inside one explicit SQLite transaction, then kills the child process with `os._exit()`.

Four cases:

1. assistant event + index, crash before commit:
   - event 0
   - docs 0
   - terms 0
   - retrieval absent
   - integrity ok

2. assistant event + index, commit then abrupt exit:
   - event 1
   - doc 1
   - retrieval present
   - integrity ok

3. confirmed-memory row + index, crash before commit:
   - pre-existing source event remains
   - memory 0
   - docs 0
   - retrieval absent
   - integrity ok

4. confirmed-memory row + index, commit then abrupt exit:
   - memory 1
   - doc 1
   - retrieval present
   - integrity ok

Result: **4/4 PASS**.

This proves the SQLite transaction shape can provide both-or-neither source/index visibility. It does **not** claim production IdentityStore currently uses that shape.

Evidence:
- `source_aware_index_atomicity.py`
- `source_aware_index_crash_atomicity_metrics.json`

## FTS5 ablation

Local SQLite FTS5 availability was tested.

- `unicode61`: Chinese phrase matching failed for the tested unsegmented text.
- `trigram`: 3-character Chinese substrings matched.
- `trigram`: 2-character query did not match.

Therefore "just use default SQLite FTS5" is not accepted as the Chinese retrieval solution. The existing XiaoYu bigram tokenizer remains useful, potentially combined with another semantic/high-DF fallback.

## What remains unproven

This Lead E0 does not solve:

1. semantic Chinese paraphrase retrieval;
2. a production retention/deletion policy for all assistant transcript history;
3. integration into production methods without duplicated transaction logic;
4. cross-process multi-writer index stress;
5. schema migration/backfill on real archives;
6. the currently unresolved Event Ledger multi-slot source-identity P1;
7. full context-packing and answer-grounding quality.

Because of these boundaries, the result is queued for independent research replication as **R09**, not self-promoted to E1.

## Lead decision

The source-aware retrieval direction is now concrete enough for formal research:

> persistent global index + explicit source role + authority separation + bounded lexical routing + deterministic lifecycle recovery.

It should replace neither semantic state projection nor provenance validation. It is the retrieval substrate underneath those layers.
