# XiaoYu P1 Architecture Freeze Candidate — 2026-10-27

## Status

**CANDIDATE FREEZE FOR INTEGRATION / PROSPECTIVE VALIDATION.**

This document turns accepted E1 evidence plus the T19 external-comparator results into one candidate architecture. It is not an E2/E3 release claim. Components with pending independent audit remain gated.

## Candidate pipeline

```
immutable/stable source events + provenance
        |
        v
validated semantic-event extraction
        |
        v
typed temporal/current/historical state
        |
        +--------------------------+
        |                          |
        v                          v
persistent global evidence index   derived state/index rebuild metadata
(user + eligible assistant)
        |
        v
query-conditioned retrieval
        |
        v
evidence-aware context packing
(source role + stable evidence identity + temporal status)
        |
        v
answer model
        |
        v
response/evidence validation + abstention/quarantine
```

## Accepted E1 foundations

### Stable event ledger — ACCEPT_E1

Use stable conversation/message source identity plus validated textual event position for event identity. Keep payload hash separate. Divergent payload for the same source identity is quarantined rather than silently overwritten.

Reason: reordered retry, duplicate delivery, race and crash-point evidence reproduced independently.

### DeepSeek Chinese semantic event projector — ACCEPT_E1

Use non-thinking DeepSeek Flash as a candidate semantic-event extractor under the frozen controlled track.

Important boundary: model output is a candidate projection, not authority. Evidence pointers and state effects are validated deterministically before commit.

### Strict model-response boundary — ACCEPT_E1

Require expected case/event bijection, schema validity, source-event grounding and duplicate/conflict checks. Malformed or misattributed model output cannot mutate state silently.

### Public MEME state extraction — ACCEPT_E1

Retain the demonstrated ability to recover facts, deletions, dependencies and conditional replacements from natural language without exposing benchmark gold/task labels to the model.

### Long-tail retrieval defect — ACCEPT_E1 direction

The newest-1000 candidate truncation is not acceptable. Replace it with a persistent/incremental global retrieval layer; do not merge the earlier in-memory prototype as-is.

## T19-induced source policy

### User-origin evidence

Direct user assertions remain the strongest ordinary source for user preferences/facts, subject to temporal correction, withdrawal and conflict handling.

### Assistant-origin evidence

Assistant evidence is now explicitly **retrieval eligible** because Mem0, Hindsight and Cognee independently recover a real public assistant-origin LongMemEval fact that XiaoYu's literal compatibility baseline structurally misses.

But assistant evidence is not automatically equivalent to user state:
- a recommendation can be retrieved as "the assistant recommended X";
- a prior assistant explanation can support questions about what was previously said;
- an assistant guess does not become "the user prefers X";
- state-changing claims still require semantic/source validation.

### Provenance is part of memory semantics

At minimum, retrievable evidence must retain:
- stable conversation/message/event identity;
- source role;
- source text or exact support span / reconstructable source;
- temporal information where available;
- projection/version identity;
- lifecycle status (active/superseded/deleted/quarantined).

## Retrieval requirements

The next production-candidate retrieval layer must:

1. search beyond the newest 1000 active memories;
2. cover eligible assistant-origin evidence as a distinct source class;
3. preserve source identity through ranking and context packing;
4. support temporal/supersession filtering rather than treating retrieval score as current truth;
5. remain incrementally persistent and crash-consistent;
6. remove or invalidate derived postings when evidence is deleted/superseded;
7. expose enough retrieval evidence for response validation and independent audit.

A flat "embed everything and return top-k text" implementation is not sufficient for this project even if it scores well on one benchmark.

## Reliability and cost boundary

All paid model calls remain behind `governance/research_api.py` and the tagged loopback proxy.

Cost controls are safety/reliability boundaries, not scientific targets:
- necessary samples are not dropped merely to improve cache or cost;
- ablations that alter scientific conditions get a new prospective version;
- abnormal stale/recursive benchmark work is circuit-broken;
- UNKNOWN provider outcomes remain fail-closed.

External comparator results show that transport/runtime details can materially distort cost and reliability (Hindsight restart/resume, Cognee 1024-token truncation, Graphiti cost amplification). Deployment correctness is therefore part of the comparison protocol.

## Current integration gates

Before calling this architecture E2-ready:

1. keep the now-ACCEPT_E1 P1 fail-closed CI integrity contract frozen at its minimal gate scope; do not expand it into a general supply-chain subsystem;
2. implement/integrate a persistent global evidence index that satisfies the accepted long-tail and assistant-source requirements;
3. bind semantic projection -> stable event ledger -> typed state atomically enough to survive retries/crashes;
4. run provenance/source-role counterexamples where assistant guesses and recommendations are deliberately mixed with user corrections;
5. run deletion/replay/restore gates over both user- and assistant-derived projections;
6. run a small frozen matched prospective suite against the retained external comparators or their frozen evidence;
7. require the P1 CI runner to fail closed when any mandatory gate is absent, crashes, times out or regresses.

## Deferred / rejected shortcuts

- Do not copy Mem0/Hindsight/Cognee wholesale as the identity architecture merely because they recover #499.
- Do not promote all assistant messages into user memory.
- Do not force Graphiti through a raised cost ceiling merely to obtain a score.
- Do not merge the accepted long-tail in-memory index prototype without persistence/incremental/crash consistency.
- Do not unlock the 95M benchmark allocation just because three external systems recover one assistant-origin case.
- Do not claim E2/E3 until the integrated prospective gates pass.

## Lead decision

The research direction is now sufficiently constrained to stop broad framework collection.

Primary engineering/research focus moves to:
- integrate the accepted source/event/model boundaries;
- build the persistent source-aware global retrieval layer;
- close P1 CI and archive/concurrency reliability;
- validate the resulting whole pipeline prospectively.

External frameworks remain falsification references, not the project roadmap.


## Lead update — post-freeze blockers and retrieval prototype

Two later independent audits materially narrow integration readiness:

1. **P1 CI runner remains NEEDS_WORK** (`sub-839517a177254863`).
   The submitted runner did not bind required `integrity_files` membership into the frozen contract. Omitting only `erasure_e0.py` from integrity coverage then substituting the same-name script can still produce PASS. The remediation is now backlog **R10 / ci.p1.integrity_contract**.

2. **Latest Event Ledger integration revision remains NEEDS_WORK** (`sub-ce0e2a744b164029`).
   Although the previously accepted event-ledger E1 remains valid evidence for its tested scope, the newer revision exposed an in-scope multi-slot source-identity P1: model-declared semantic slot can influence `subject_anchor`, so slot drift can change `source_event_id` without quarantine. The remediation is backlog **R11 / eventledger.source_identity.multislot**.

Therefore no earlier ACCEPT_E1 should be interpreted as permission to integrate a later branch that has a newer material counterexample.

Separately, the Lead source-aware retrieval E0 prototype now passes:
- 90/90 confirmed-user long-tail retrieval;
- 90/90 assistant-history long-tail retrieval;
- authority separation (assistant guess visible as history, excluded from state);
- archive cleanup;
- assistant suppression across restart;
- missed-index restart recovery;
- high-DF fail-closed routing;
- 4/4 explicit SQLite crash-atomicity cases when source + index share one transaction.

This is queued for independent replication as **R09 / retrieval.source_aware.persistent**. It is not yet E1.


### Lead E0 CI remediation update

The CI integrity-coverage P1 now has a Lead-isolated repair prototype. Exact required integrity membership + SHA256 are frozen in the runner trust root rather than selected by the manifest.

Lead evidence:
- 11/11 new integrity-contract mutations fail closed before gate execution;
- original 13/13 runner mutations still fail closed;
- clean suite remains 4/4 PASS;
- real erasure regression substituted under the required filename is rejected by actual SHA preflight before any gate executes.

This does **not** change `sub-839517a177254863` from NEEDS_WORK. Formal replication remains queued as R10.


## Lead de-duplication / reuse freeze — 2026-10-27 18:xx +08

See `plans/P1_DUPLICATION_AUDIT_REUSE_FREEZE_20261027.md`.

Two implementation choices are now narrowed by direct local E0 evidence:

1. **Persistent lexical posting storage:** do not productionize the handwritten `evidence_terms(term,doc_key)` posting engine. A matched SQLite FTS5 + `fts5vocab` probe preserved 180/180 user/assistant long-tail retrieval, authority separation, deletion, restart and high-DF fail-closed behavior while improving the synthetic median/p95 query latency (3.668/9.235 ms vs 5.37/13.54 ms) and build time (0.123 vs 0.218 s). XiaoYu retains source/authority/eligibility/ranking policy; SQLite owns lexical postings.

2. **Future portable identity format:** stop expanding the SQLite + duplicate identity.json + manifest ZIP design. A single authoritative SQLite online-backup prototype passed 100/100 concurrent snapshots during 1,179 concurrent writes, with integrity/FK/source-link/identity consistency and direct new-home restore all passing. Existing V2 ZIP becomes legacy migration input, not the future P1/P2 authority format.

The external-framework boundary is also frozen:
- Mem0/Hindsight/Cognee/Graphiti + OmniMemEval are sufficient retained references;
- no broad framework collection by default;
- no custom graph DB/vector DB/ANN;
- Cognee/Graphiti generic provenance/temporal mechanics are reference/reuse candidates;
- XiaoYu keeps only the fail-closed source-identity, semantic-conflict quarantine, source-authority and identity-state policy they do not establish.

This update supersedes any wording in this candidate that implies a custom handwritten posting engine or continued ZIP-format hardening is the preferred production direction.


## Live-status clarification after de-duplication pass

- `ci.p1.integrity_contract` submission `sub-fc06b3ec2b554566` is now **ACCEPT_E1** after independent audit. Its accepted scope is the minimal P1 gate/integrity contract; reuse freeze forbids turning it into a general software-supply-chain framework.
- `retrieval.source_aware.persistent` submission `sub-4642b7fe04994bd6` is **LEAD_READY / PENDING independent audit**. If accepted, the scientific claim applies to source-aware authority/lifecycle/persistence semantics. Production lexical posting storage is separately constrained to SQLite FTS5 by the matched Lead de-duplication probe; acceptance of R09 does not authorize the handwritten `evidence_terms` implementation.
- Event-ledger v5 source-identity repair remains pending independent E1 audit; the generic provenance mechanics comparison with Cognee/Graphiti does not waive XiaoYu-specific fail-closed source-conflict requirements.


## External-research saturation update — 2026-10-27

Build-vs-Reuse is now V2; see `governance/REUSE_GUARD.md`, `REUSE_CATALOG.json`, `COMPONENT_ADMISSION.md`, and ADRs under `governance/decisions/`.

Additional frozen boundaries:

- New self-directed research must review local prior work before claim. Same family/lineage always requires explicit prior-work review; exact submitted hypotheses require intentional falsification/replication rather than accidental rerun.
- Reuse catalog entries now carry lifecycle/owner/source/version/license/health/review metadata. Generic vector/embedding aliases are deprecated.
- External dependencies are admitted by Lead with version/license/security/maintenance evidence; no network scan runs in the normal lease hot path.
- Existing active lease decisions remain frozen to the catalog revision they started with. Catalog drift is reported by `reuse-doctor`; new work uses the latest revision.
- Benchmark expansion is capability-oriented, not framework-oriented: see `plans/P1_BENCHMARK_CAPABILITY_MATRIX_20261027.md`.
- Erasure claims distinguish logical erasure/beyond-use/replay prevention from physical deletion of every historical backup copy; see `plans/P1_ERASURE_BACKUP_SEMANTICS_20261027.md`.
## Trust-layer re-saturation update — explicit requirements

The five-round external gap-closure pass did not justify replacing the frozen thin architecture, but it adds four explicit requirements:

1. **Origin-bound authority.** Source authority is immutable write-time metadata. Summarization, model confidence, tool echo, repeated retrieval or consolidation must not silently promote assistant/external evidence into user authority.
2. **Admissibility before exposure.** Principal, audience, scope, lifecycle and authority checks happen before memory enters model-visible context. Relevant-but-inadmissible evidence is not a valid candidate.
3. **Dependency-aware derived state.** Derived/current states retain sufficient dependency and rule-version information for implicit upstream changes to invalidate or recompute them.
4. **Control-state and rollback integrity.** Integrity covers lifecycle/ownership/freshness metadata, replay and whole-store rollback, not only content hashes.

Additional scope decisions:
- deletion E2 must include behavioral reconstruction/closure probes, not only record absence;
- persistent-memory poisoning gets a dedicated security gate;
- future portable wire-format work compares existing portable-memory/interoperability references before inventing a XiaoYu protocol;
- P3 persona/relationship work anchors to DyadMem/PersonaTree-style evidence-backed separation;
- multi-user/group, multimodal and persistent procedural/tool memory remain deferred scope, but the core schema must not unnecessarily preclude them.

See plans/P1_TRUST_LAYER_EXTERNAL_GAP_CLOSURE_20261027.md and governance/decisions/ADR-009-trust-layer-gap-closure-and-resaturation.md.


## Trust-layer reconciliation — 2026-10-27

The re-saturation survey adds exactly two P1 hard gates: R21 memory-security lifecycle (including authority laundering) and R22 pre-context retrieval admissibility. Derived-state propagation, behavioral deletion closure and rollback/control-state integrity are P2 HOLD; portable-memory interchange is P3 HOLD.

P1 assembly now treats authority as origin-bound/non-amplifying and requires principal/scope/authority/lifecycle admission before model-visible context. Integration readiness is dependency-aware; individual E1 evidence does not bypass blocked upstream stages.

Detailed decision: `plans/P1_TRUST_LAYER_LEAD_DIGEST_20261027.md`.


## R40 semantic falsification / representation split — 2026-10-28

R40 cleanly falsified the P1 requirement that one whole-message model call must losslessly enumerate every transient same-slot event: both fresh rounds were 29/32 full-sequence exact but 32/32 final-state exact, with the same three transient omissions and a clean paid-evidence ledger.

Lead therefore does not rescore R40. R35 is prospectively reopened with a different frozen semantic target: immutable raw message remains SOURCE/history; canonical structured state retains only the final effective grounded SET/CLEAR per slot. P1 does not claim lossless structured intra-message transient history. See `governance/decisions/ADR-010-structured-current-vs-source-history.md`.


## R44 falsification / R45 provenance-context boundary — 2026-10-28

Independent R44 audit discovered a P1 representation leak: a whole-message `evidence_quote` accepted by the strict validator was copied verbatim into each surviving canonical event, resurrecting a deleted sibling's plaintext in 80/80 attacks despite deletion of the sibling source row.

P1 therefore freezes a stronger representation boundary:
- raw quote/source text = sealed provenance surface;
- canonical model-visible memory = event-local op/slot/value semantics + opaque provenance references/hashes;
- partially erased multi-fact raw SOURCE/history is non-model-visible unless separately redacted/event-localized.

Lead E0 closes the known R44 attack 80/80 -> 0/80 and separately falsifies raw message-level history after partial sibling erasure. Fresh R45 Research A evidence is under independent audit; do not promote until ACCEPT_E1.

See `plans/P1_R45_PROVENANCE_CONTEXT_SEPARATION_LEAD_E0_20261028.md`.
