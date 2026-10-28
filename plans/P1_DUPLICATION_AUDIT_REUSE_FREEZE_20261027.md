# XiaoYu P1 Duplicate-Wheel Audit / Reuse Freeze — 2026-10-27

## Status

**LEAD DECISION — STOP BROAD REINVENTION; KEEP ONLY XIAOYU-SPECIFIC SEMANTICS.**

This audit was performed after catching up to the live local control plane:
- 102 submissions;
- 5 ACCEPT_E1;
- 2 pending E1 audits;
- 3/3 active slots;
- T19 external comparator evidence frozen across Mem0, Hindsight, Cognee, Graphiti;
- P1 architecture-freeze candidate already exists.

No production identity/private data was modified. The two new de-duplication probes are isolated Lead E0 experiments with zero paid/model calls.

---

## Executive decision

There **has been partial wheel reinvention**.

The project should distinguish:

1. **Commodity mechanism** — reuse a standard/local mature implementation.
2. **XiaoYu policy/semantics** — keep custom only when external systems do not satisfy the fail-closed identity/privacy contract.
3. **Comparator capability** — do not copy the whole framework; use it to falsify our requirements.

The architecture is changed accordingly.

---

## A. Persistent lexical postings — DUPLICATE WHEEL, REPLACE

### What XiaoYu built

The current Lead/Research persistent retrieval prototype manually implements:
- `evidence_terms(term, doc_key)`;
- posting-list maintenance;
- per-document delete/reinsert;
- rarest-posting DF lookup;
- restart rebuild/sync.

This is a small custom search engine layered over SQLite.

### Existing mechanism

The local Python SQLite 3.45.1 build has **FTS5 enabled at compile and runtime**.

A Lead E0 replacement probe keeps the XiaoYu tokenizer/policy but delegates posting storage to SQLite FTS5:
- XiaoYu `_keywords` still defines Chinese bigram + Latin-token semantics;
- keywords are deterministically encoded as ASCII tokens;
- FTS5 stores/updates postings transactionally;
- `fts5vocab` supplies document-frequency lookup;
- source role / authority / status stay ordinary relational metadata;
- XiaoYu keeps the high-DF fail-closed policy and ranking policy.

Evidence:
`governance/lead_workspaces/dedupe_fts5_20261027/fts5_dedupe_metrics.json`

Matched synthetic corpus: 3,202 docs.

Result:
- confirmed-user retrieval: **90/90**;
- assistant-history retrieval: **90/90**;
- assistant guess visible as history: PASS;
- assistant guess excluded from state: PASS;
- confirmed user memory remains state-authoritative: PASS;
- deletion removes retrieval: PASS;
- restart persistence: PASS;
- high-DF fail-closed: PASS;
- build: **0.123 s**;
- query median: **3.668 ms**;
- query p95: **9.235 ms**.

Prior handwritten posting prototype:
- same 90/90 + 90/90 correctness;
- build about **0.218 s**;
- query median **5.37 ms**;
- p95 **13.54 ms**.

### Decision

**Do not productionize the handwritten `evidence_terms` posting layer.**

Keep custom:
- evidence eligibility;
- source role / authority;
- current-state vs conversation-history separation;
- temporal/lifecycle filtering;
- high-DF fallback policy;
- evidence-aware ranking/context packing.

Reuse:
- SQLite FTS5 for lexical inverted-index storage and transactional posting maintenance.

Semantic fallback, if required, must reuse an existing embedding/vector implementation (e.g. already-deployed local FastEmbed + an existing vector backend) rather than implementing a custom ANN/vector database.

---

## B. Portable ZIP + dual JSON/SQLite archive — PATCH TREADMILL, REPLACE FUTURE FORMAT

### Evidence of over-research

Registry currently contains **26 submissions across 25 archive/import/export families**, including:
- dual representation consistency;
- JSON duplicate keys / non-finite numbers;
- ZIP duplicate entries / resource bounds;
- transactional staging;
- export atomicity / concurrent consistency / concurrent commit;
- schema/referential/lifecycle validation;
- authenticity/confidentiality;
- parser ambiguity.

Across these archive-related submissions:
- LEAD_READY: **0**
- ACCEPT_E1: **0**

The experiments are useful because they reveal the design surface, but continuing to patch the current ZIP container is poor leverage.

### Root cause

Current V2 export creates:
1. `identity.sqlite3`;
2. a separately-timed `identity.json` snapshot of the same logical state;
3. `manifest.json`;
4. ZIP container around all three.

This creates redundant representations and multiple parser/container surfaces.

### Single-SQLite Lead probe

Evidence:
`governance/lead_workspaces/dedupe_single_sqlite_archive_20261027/single_sqlite_archive_metrics.json`

Synthetic concurrent test:
- 100 SQLite online-backup snapshots;
- separate writer committed **1,179** concurrent synthetic events;
- 100/100 snapshots: SQLite integrity OK;
- 100/100 foreign keys OK;
- 100/100 identity ID stable;
- 100/100 memory source links valid;
- snapshot event counts monotonic;
- median backup: **3.914 ms**;
- direct single-file restore into a new home: PASS.

### Decision

For the future P1/P2 portable format, prefer:

**one authoritative SQLite backup snapshot**

rather than SQLite + duplicate identity JSON inside a custom ZIP.

This removes the need for production fixes for:
- SQLite-vs-JSON cross-view races;
- duplicate ZIP member interpretation;
- decompression-bomb handling for core state;
- identity JSON duplicate-key/non-finite parsing;
- ZIP extraction/staging atomicity for the core state.

Existing V2 ZIP import remains a **legacy migration compatibility path**, not the future architecture.

Still required and NOT solved by the simplification:
- authenticity/signature;
- rollback/fork freshness;
- semantic schema validation;
- pending-action portability policy;
- secure erasure of old copies.

Those are semantic/security requirements and should be solved directly, preferably with standard cryptographic primitives rather than a growing custom archive manifest protocol.

---

## C. Generic provenance ledger — PARTIAL DUPLICATION; REUSE MECHANICS, KEEP XIAOYU SEMANTICS

### External capability already present locally

Cognee 1.6.5-local already contains an Apache-2.0 provenance subsystem with:
- source document/location/quote/ref;
- parent / used entities / derived-from;
- validity intervals;
- supersedes / revision metadata;
- invalidation tombstones;
- sequence IDs;
- per-entry checksum + previous-checksum hash chain;
- lineage queries;
- transactional batch append;
- SQLite/Postgres concurrency serialization.

Graphiti also carries:
- episode UUID/source description;
- episodic provenance;
- valid-at / invalid-at temporal edges.

Therefore XiaoYu must **not** build a second generic W3C-style provenance platform merely because provenance is needed.

### Why the XiaoYu event boundary is still custom

Cognee is not a drop-in replacement for the accepted XiaoYu event semantics:

- Cognee entity ID is supplied by the caller; it does not derive immutable source identity from conversation/message/text positions.
- Re-tracking an entity versions it; it does not apply XiaoYu's same-source divergent-payload quarantine semantics.
- Cognee tracking methods deliberately degrade gracefully on storage failure ("provenance must never break the host operation").
- XiaoYu requires the opposite boundary for identity mutation: invalid/misaligned provenance must **fail closed** and prevent state mutation.
- Cognee does not establish XiaoYu's user-vs-assistant authority distinction.
- Graphiti episode identity/temporal edges likewise do not prove semantic-slot drift quarantine.

### Decision

Keep custom:
- source-event identity derivation;
- message/source immutable identity rules;
- semantic payload separation;
- wrong-slot / same-source conflict quarantine;
- source authority (user vs assistant history vs state);
- fail-closed coupling between evidence validity and identity-state mutation.

Reuse / borrow mature mechanism instead of inventing:
- provenance field vocabulary;
- lineage/invalidation model;
- transactional append patterns;
- checksum-chain implementation if an audit hash chain is required;
- temporal valid/invalid representation.

The Event Ledger should stay **small and policy-specific**, not grow into a general provenance framework.

---

## D. External memory frameworks — COLLECTION COMPLETE; DO NOT BUILD OR COLLECT MORE BY DEFAULT

Frozen evidence is already sufficient for the main architectural question:

- XiaoYu literal baseline misses assistant-origin evidence;
- Mem0 recovers it;
- Hindsight recovers it;
- Cognee recovers it;
- Graphiti is functional but cost-disqualified under the current guard.

This already falsifies the user-only retrieval assumption.

### Decision

Stop broad framework collection.

Retain:
- Mem0: extraction/attribution reference;
- Hindsight: extraction/retrieval + checkpoint reference;
- Cognee: graph/vector + provenance reference;
- Graphiti: temporal-graph architectural/cost reference;
- OmniMemEval: shared evaluation harness.

A new framework is admitted only if it tests a capability not represented by these retained references.

Do not implement:
- a custom graph database;
- a custom vector database / ANN;
- another generic memory framework abstraction;
- a separate benchmark harness duplicating OmniMemEval.

---

## E. P1 CI integrity contract — GENERIC, BUT CURRENTLY SMALL; FREEZE SCOPE

The top-level project is **not currently a Git repository**, so the current exact-file SHA trust root is doing real work; it cannot immediately be replaced by a frozen Git commit/tree without first changing project source-control layout.

The repaired CI contract is small (13 required integrity paths) and already has focused mutation tests.

### Decision

Do not expand P1 CI into a custom software-supply-chain system.

For P1:
- keep the minimal exact membership + SHA preflight;
- keep deterministic mandatory-gate execution;
- no new custom signing/package-distribution features.

Later, if the production source is placed under a clean top-level Git repository/build artifact pipeline, replace the bespoke file set with a standard content-addressed release/commit artifact rather than maintaining two integrity systems.

---

## F. Typed temporal/current state — KEEP CUSTOM POLICY, DO NOT BUILD A GRAPH ENGINE

External systems demonstrate temporal and graph facilities, but XiaoYu's state semantics include:
- direct-user authority;
- assistant-history non-authority;
- correction/withdrawal;
- quarantine/abstention;
- deletion lineage.

Those semantics are product policy, not a database primitive.

### Decision

Keep the typed state projector as a thin deterministic policy layer.

Do not turn it into:
- a custom general graph database;
- a custom ontology engine;
- a custom vector store.

Where graph traversal is genuinely needed, evaluate the already-running Cognee/Graphiti capability before adding new infrastructure.

---

## G. Updated build-vs-reuse boundary

Future candidate stack:

```
canonical SQLite source/event state
        |
        |  XiaoYu-specific: stable source identity + fail-closed conflict policy
        v
validated semantic events / typed current+historical state
        |
        |  standard mechanism: SQLite FTS5
        v
source-aware lexical evidence retrieval
        |
        +--> optional semantic fallback using existing FastEmbed/vector backend
        |
        v
XiaoYu-specific authority / temporal / provenance-aware packing
        |
        v
answer model + accepted response/evidence validator
```

Portable artifact:

```
single authoritative SQLite online-backup snapshot
        + standard authentication/freshness mechanism when required
```

External memory/graph systems remain comparator/reference layers, not a second production identity store.

---

## Stop-loss decisions

Effective immediately for Lead planning:

1. **No new handwritten lexical posting/index implementation** unless FTS5 is prospectively falsified on a required case.
2. **No new ZIP/identity.json patch family** for the future format. Existing findings become migration regression cases.
3. **No new generic provenance subsystem**. Event work must target XiaoYu-specific source identity/authority/quarantine semantics.
4. **No new external memory framework collection** without a distinct missing capability.
5. **No custom ANN/vector store or graph DB**.
6. **No CI supply-chain feature expansion** beyond the P1 gate contract.
7. Every new custom subsystem proposal must state the specific retained external/standard mechanism it cannot satisfy and provide a falsifier.

This converts the prior "avoid wheel reinvention" principle into an enforceable architecture boundary.
