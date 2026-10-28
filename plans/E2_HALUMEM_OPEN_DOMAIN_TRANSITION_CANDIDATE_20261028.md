# E2 HaluMem Open-Domain Transition Candidate — 2026-10-28

Status: **PROPOSAL ONLY / NOT AUTHORIZED FOR PAID EXECUTION**

## Why this transition is required

The frozen E2 protocol makes HaluMem a required pilot track, but the frozen execution manifest correctly holds both HaluMem scopes:

- `halumem_extract = HOLD_OPEN_DOMAIN_SCHEMA_MISMATCH`
- `halumem_qa = HOLD_DEPENDS_ON_VALID_HALUMEM_MEMORY_PIPELINE`

LongMemEval is now complete (46/46 COMMITTED), but the overall non-promotional E2 pilot remains incomplete and confirmatory remains locked.

The blocker is scientific, not budgetary. The accepted R27/R35 extractor is a finite-slot current-state projector. HaluMem is an open-domain memory benchmark whose official ingestion passes the whole user+assistant conversation to the memory framework.

## New pilot-only evidence

Offline inspection of only the already-exposed HaluMem pilot users/windows:

- selected sessions: 32
- user turns: 647
- assistant turns: 647
- memory points in those windows: 213
- updates: 45
- memory types:
  - Persona Memory: 124
  - Event Memory: 67
  - Relationship Memory: 22

Diagnostic lexical support:
- assistant-lean memory points: 142
- tie: 66
- user-lean: 5

This lexical attribution is not provenance proof, but it is enough to falsify the frozen **user-only** extraction contract as a faithful implementation of HaluMem full-dialogue ingestion. Expanding the slot vocabulary alone would still be structurally wrong.

## Prior work / reuse decision

### Reuse directly

Keep the thin XiaoYu architecture. Reuse:

1. **XiaoYu/SQLite authoritative store**
   - existing generic free-text memory/event capacity;
   - one SQLite authority;
   - durable/restartable state.

2. **Stable source identity + caller-owned authority**
   - model does not mint source IDs, authority, principal, conversation IDs or approval state;
   - user and assistant source roles remain immutable write-time metadata.

3. **P1/P2 trust layer**
   - authority non-amplification;
   - admissibility before model exposure;
   - lifecycle/deletion/quarantine;
   - partial-erasure provenance separation;
   - rollback/freshness controls.

4. **SQLite FTS5 source-aware retrieval**
   - persistent lexical index;
   - SOURCE/history versus current/conflict remains explicit;
   - no new vector/graph database is required for this transition.

5. **R18/R29 context-answer protocol**
   - existing context/question answerer can remain the HaluMem QA surface once a legitimate memory state/context exists.

6. **R23-derived-state / temporal-state patterns**
   - explicit dependency/current/conflict semantics may be reused where the extracted relation actually supports them.

### Reuse as semantic/reference patterns, not as direct extractor

- MEME FACT/DELETE/RULE work demonstrates structured natural-language state extraction, but its accepted extractor uses a fixed 89-entity vocabulary. It is not open-domain HaluMem extraction.
- Mem0, Hindsight, Cognee and Graphiti remain frozen reference/falsification systems; do not replace XiaoYu's store or trust policy with one of them merely to unlock HaluMem.
- Historical HaluMem `fish-bf1f...` results directly ingest released `memory_points` and use oracle update/interference metadata in some arms. They validate retrieval/conflict risks, not dialogue-to-memory extraction.

## Minimal new scientific component

Only one capability family should be newly investigated:

**source-grounded open-domain claim projection + update-target binding**

Everything downstream should reuse accepted XiaoYu components.

### Proposed paid-case granularity

Do not double the frozen 647-case envelope into 1294 independent role calls.

For each existing HaluMem extraction anchor, form one **exchange-pair case**:

- target user message;
- immediately corresponding assistant reply;
- immutable caller-owned message indices/roles;
- bounded prior active-claim candidates supplied by the caller where update resolution is needed.

This preserves:
- the existing 647 extraction anchors/case-count geometry;
- both source roles required by official full-dialogue ingestion;
- stable per-message provenance;
- bounded paid-call count.

It changes scientific semantics and payload hashes, therefore it requires a **new separately frozen HaluMem transition manifest/scope**. The existing HOLD manifest remains immutable.

## Proposed model boundary

The model is a candidate projector, not authority.

A new open-domain response should contain only source-grounded claim candidates and update relations over caller-supplied candidate indices. Example logical fields:

- operation: ASSERT / RETRACT / REVISE
- atomic claim text
- source message index
- exact evidence quote
- optional prior-candidate index for RETRACT/REVISE

The model must never output:
- source_event_id;
- claim_id;
- authority;
- principal;
- lifecycle state;
- conversation/user ID;
- arbitrary target IDs not supplied by the caller.

Caller binds all stable identities and source roles.

## Mandatory deterministic validation

Before any claim can affect state:

1. source message index belongs to the supplied exchange;
2. source role is caller-owned and immutable;
3. evidence quote is a unique continuous span of that source message;
4. claim text is grounded by the quote;
5. update/retraction target may only reference a caller-supplied prior candidate;
6. assistant-origin evidence cannot silently become user authority;
7. malformed/ambiguous target binding fails closed to NEW HISTORY or unresolved conflict, never silent supersession;
8. same source identity with divergent payload quarantines;
9. retries are idempotent.

## Update-target requirement

Do not use exact text equality as the production resolver.

Existing public HaluMem analysis observed:
- 3,788 `original_memories` update references;
- exact prior-string resolution archived only 799 stored rows;
- hit ratio: 21.1%.

Therefore the new transition must prospectively test semantic target binding or explicit unresolved-conflict behavior. Released `original_memories` may be used only as post-call pilot gold/diagnostics, never model input or runtime target authority.

## State representation

Maintain two surfaces:

### SOURCE/history
Immutable role-bound source evidence:
- user source -> user-history class;
- assistant source -> conversation-history class;
- never authority-laundered through summarization/retrieval.

### Canonical claims/current
Validated atomic claims:
- direct user assertions may become user-current when temporal/update rules establish a unique current value;
- assistant claims remain assistant/conversation evidence unless later user evidence independently establishes user state;
- supersession is explicit;
- unresolved competing claims remain conflict;
- deletion/quarantine propagates through provenance/dependencies.

Raw multi-fact source text is not copied into every canonical claim.

## Retrieval / QA

After ingestion:

- build/query the accepted persistent FTS5 evidence layer;
- retrieve formal current/history/conflict records with source metadata;
- preserve whole evidence identity;
- feed only admitted context into the already accepted R18/R29 answer protocol;
- HaluMem QA remains blocked until this generated state/context pipeline is frozen.

Hand-built QA context and released benchmark `memory_points` are forbidden as runtime context.

## Frozen-development boundary

Development/evaluation may use only the two already-exposed pilot users.

The 18 confirmatory HaluMem users remain prohibited from:
- tuning;
- prompt inspection;
- outcome inspection;
- target-threshold selection;
- paid execution.

Public dataset files can remain locally pinned for hash verification/split bookkeeping, but no confirmatory-user records should be selected into transition experiments.

## Required prospective falsifiers before paid HaluMem pilot can resume

A separately authorized transition must freeze these before calls:

1. **Source-role coverage**
   - user-only ablation must be rejected;
   - exchange-pair candidate must preserve user and assistant evidence identity.

2. **Open-domain extraction**
   - held-out pilot-window messages, no benchmark memory_points in model input;
   - exact quote/source grounding;
   - no unsupported claim creation.

3. **Update target binding**
   - direct updates, paraphrased updates, retractions, unrelated same-topic claims;
   - exact-string baseline included only as a falsifier;
   - ambiguous relation => conflict/no supersession.

4. **Authority laundering**
   - assistant guess/recommendation cannot become user state;
   - assistant-history remains retrievable where the question asks about prior assistant content.

5. **Lifecycle**
   - superseded/deleted/quarantined claim absent from current context;
   - provenance/history behavior follows P1/P2 contracts.

6. **Restart/idempotency**
   - exact retry no duplicate;
   - divergent retry quarantine;
   - crash/restart preserves source/claim/update links.

7. **Budget preflight**
   - tokenizer-based projection over all 647 pair payloads;
   - existing total pilot cap of 1,000,000 raw tokens remains a hard ceiling unless Lead explicitly refreezes a different cap before any transition call.

## Execution transition required

No paid HaluMem call is authorized by this document.

Before first transition call, Lead must explicitly freeze:

- new open-domain projector prompt/hash;
- exchange-pair payload builder/hash;
- deterministic validator/hash;
- update-target resolver contract/hash;
- new HaluMem transition manifest with payload hashes;
- dedicated paid scope/run header;
- completion caps and total token projection;
- pilot-only case membership (same two exposed users);
- scoring layers and descriptive metrics;
- independent pre-execution audit that confirmatory split remains untouched.

Only after that freeze may the existing HaluMem HOLD be superseded for the pilot users. The original manifest/receipts remain immutable historical evidence.

## Alternative

Lead may explicitly amend the scientific protocol to remove HaluMem as a required track, but that narrows the E2 capability claim and must occur before confirmatory threshold freeze. It must not be achieved by silently treating the completed LongMemEval subtrack as the whole pilot.

## Recommendation

Prefer the minimal open-domain transition over dropping HaluMem:

- it exercises a capability the project actually needs;
- it reuses almost all accepted architecture;
- it directly addresses the benchmark's extraction/update hallucination goal;
- it avoids adopting a second memory framework;
- it preserves the already-fixed confirmatory split.

Until this transition is separately frozen and audited:

**E2 overall pilot remains incomplete and confirmatory remains closed.**
