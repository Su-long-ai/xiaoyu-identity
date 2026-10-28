# XiaoYu Trust-Layer External Gap Closure / Re-Saturation — 2026-10-27

## Status

**RE-SATURATED FOR CURRENT P1/P2 ARCHITECTURE DECISIONS AFTER FIVE EXTERNAL SEARCH ROUNDS.**

This pass was triggered because the earlier external survey covered Mem0 / Hindsight / Graphiti / Cognee / Letta and benchmark infrastructure well, but did not contain several 2026 trust-layer papers directly overlapping XiaoYu's source-authority, deletion, portability and integrity goals.

The revised conclusion is narrower and stronger:

- the previous framework/component-selection saturation remains valid;
- the previous claim of broad research-frontier saturation was too strong;
- after this gap-closure pass, the current P1/P2 capability map is saturated enough to stop broad searching again;
- future external search should reopen only on a concrete falsifier, newly published capability class, retained-component/security event, or benchmark scope change.

No result below authorizes automatic production adoption. Papers and benchmarks remain references until independently reproduced or used under a frozen prospective protocol.

## Search protocol

Five rounds used independent query families rather than one keyword sweep:

1. Known missing names: Agent Zero Memory, MemIR, provenance laundering / PPMF, AfterDeleteBench and portable-memory work.
2. Security / isolation / portability: memory poisoning, write-time authority, cross-user leakage, multi-agent visibility, event sourcing and cross-model transfer.
3. Lifecycle / efficiency / learning: consolidation, forgetting, compression, heterogeneous memory routing, memory-operation credit and persona evolution.
4. October-2026 frontier: derived state, retrieval admissibility, governance-state corruption, relational memory, at-rest integrity and interoperability work.
5. Saturation cross-check: broad survey/registry/security queries plus targeted searches for intrinsic evaluation and eviction.

Saturation criterion: the final round added implementations/benchmarks inside already-identified capability classes, but no new top-level architecture dimension.

## A. Provenance and source authority — prior gap closed

### Agent Zero Memory — arXiv:2608.29606
Provenance-aware three-view memory: episodic events, entity-event graph and hierarchical documentary memory. Retrieval includes intent/source routing and citation locking.

Impact on XiaoYu:
- validates provenance-aware multi-view memory and read discipline as a real 2026 research direction;
- does not justify copying a triple-store architecture;
- supports keeping raw/source evidence separable from derived memory and requiring answer-time evidence admission.

Source: https://arxiv.org/abs/2608.29606

### MemIR — arXiv:2605.25869
Typed memory intermediate representation separating raw evidence, retrieval cues and truth-bearing claims; addresses provenance-role collapse.

Impact:
- strongly overlaps XiaoYu's evidence -> semantic projection -> authority/state separation;
- reduces originality claims around typed provenance separation;
- reinforces that retrieval cues are not themselves factual authority.

Source: https://arxiv.org/abs/2605.25869

### PPMF / Memory Provenance Laundering — arXiv:2607.29167
Shows that lossy consolidation can turn low-trust observations into apparent user/workflow authority; proposes non-amplification.

### Origin-Bound Authority / TMA-NM — arXiv:2606.24322
Formalizes memory poisoning under laundering and argues that content- or lineage-only defenses are insufficient; write-time origin binding is necessary under its threat model.

### MemLineage — arXiv:2605.14421
Cryptographic provenance + derivation DAG + sensitive-action gating.

Sources:
- https://arxiv.org/abs/2607.29167
- https://arxiv.org/abs/2606.24322
- https://arxiv.org/abs/2605.14421

Decision:
Keep XiaoYu's custom fail-closed source identity / authority / conflict semantics, but narrow the novelty claim. The novelty target is not provenance in general; it is the exact immutable-source + authority-non-amplification + same-source semantic-conflict contract and its integration with portable identity state.

## B. Deletion / forgetting semantics — prior gap materially expanded

### AfterDeleteBench — arXiv:2610.31366
Source deletion can leave recoverable information in descendants/summaries; provenance-aware closure is the relevant defense pattern.

### From Recall to Forgetting / Memora — ACL Findings 2026
Introduces forgetting-aware accuracy and tests obsolete-memory reuse.

### What Eviction Destroys — arXiv:2609.08279
Separates irreversible evidence destruction from retrieval miss and reader-utilization failure using restore counterfactuals.

Sources:
- https://arxiv.org/abs/2610.31366
- https://aclanthology.org/2026.findings-acl.1337/
- https://arxiv.org/abs/2609.08279

Decision:
Extend XiaoYu erasure testing with an exposed-then-deleted versus never-exposed behavioral control and reconstruction probes over descendants. Keep privacy erasure separate from capacity eviction.

## C. Persistent-memory security — new top-level gap

### InjecMEM — arXiv:2608.23471
Single-interaction memory-injection attack targeting later retrieval/generation.

### MemSecBench — arXiv:2607.27080
Write -> Execute -> Forget lifecycle benchmark across memory and model backends.

### Utility Under Attack — arXiv:2608.21230
Shows that simple content screening/provenance weighting can have severe utility/security tradeoffs.

### MemGauge — arXiv:2608.30177
Separates utility/risk effects of write admission, management and retrieval exposure.

### Microsoft AI Memory / Context Poisoning guidance
Treats persistent memory as a durable attack surface and recommends source approval, schema-bound memory, integrity/versioning and privileged writes.

Sources:
- https://arxiv.org/abs/2608.23471
- https://arxiv.org/abs/2607.27080
- https://arxiv.org/abs/2608.21230
- https://arxiv.org/abs/2608.30177
- https://learn.microsoft.com/en-us/security/zero-trust/catalog-ai-attack-techniques/ai-memory-context-poisoning

Decision:
Add a dedicated memory-security capability, distinct from ordinary hallucination:
1. poisoned write admission;
2. provenance laundering;
3. poisoned retrieval exposure;
4. downstream action consequence;
5. selective repair;
6. post-repair non-recurrence.

Do not rely on content classifiers alone.

## D. Cross-user / cross-agent admissibility — new top-level gap

### MemLeak — arXiv:2610.04195
Demonstrates cross-user semantic leakage in pooled multi-tenant retrieval and evaluates ownership gating.

### The Right Memory in the Wrong Context — arXiv:2610.07309
Separates relevance from admissibility and tracks candidate support -> prompt exposure -> answer disclosure.

### COLLABMEM — EMNLP 2026
Tests sharing, role access, routing, provenance, conflict resolution and retention in multi-agent systems.

### GroupMemBench — Microsoft Research 2026
Shows that multi-party conversations require speaker-grounded belief tracking beyond dyadic memory.

Sources:
- https://arxiv.org/abs/2610.04195
- https://arxiv.org/abs/2610.07309
- https://aclanthology.org/2026.emnlp-main.1194/
- https://www.microsoft.com/en-us/research/publication/groupmembench-benchmarking-llm-agent-memory-in-multi-party-conversations/

Decision:
Add principal / audience / scope / admissibility to the future context-envelope contract. For single-user XiaoYu P1 this is mostly latent, but it becomes mandatory before shared, group or multi-agent deployment. Relevant-but-inadmissible memory must be rejected before model-visible context.

## E. Derived state / dependency propagation — new top-level gap

### MemDerive — arXiv:2610.25373
Uses symbolic scenarios, gold derivation DAGs and supporting events. It finds that systems can hold the required intermediate state yet fail to gather or propagate it, especially under implicit changes.

Source: https://arxiv.org/abs/2610.25373

Decision:
Add a P2 derived-state gate:
- versioned rules;
- dependency DAG or equivalent provenance;
- implicit-update propagation;
- query-time gathering of prerequisite states;
- stale-derived-state detection.

## F. Memory correctness versus final-answer correctness — evaluation gap expanded

### Beyond Downstream QA / FEB-30 — arXiv:2610.22209
Separates intrinsic memory-transition quality from downstream QA.

### Governance-State Corruption — arXiv:2610.30698
Shows that validity/control-state corruption can damage answers even if retained content itself is unchanged.

### Retrieval Admissibility — arXiv:2610.07309
Shows that correct final answers do not prove that model-visible context was admissible.

Sources:
- https://arxiv.org/abs/2610.22209
- https://arxiv.org/abs/2610.30698
- https://arxiv.org/abs/2610.07309

Decision:
No E2 claim may rest on final-answer QA alone. Report at least:
1. source/stored-state correctness;
2. derived/current-state correctness;
3. retrieved/admitted-context correctness;
4. final-answer correctness.

## G. Cross-model portability / identity continuity — prior gap materially expanded

### Portable Agent Memory — arXiv:2605.11032
Protocol/reference implementation for heterogeneous memory transfer using content-addressed memory, Merkle-DAG provenance, capability access control and injection-resistant rehydration.

### W3C AI Agent Memory Interoperability Community Group
A 2026 Community Group exploring portable memory-cell shape, identity binding, sharing/revocation, audit anchors and cryptographic erasure.

Important: W3C Community Group work is not a W3C Recommendation or W3C-endorsed standard.

### Agent Memory Integrity IETF Internet-Draft
draft-khandelwal-bmwg-agent-memory-integrity-02 describes storage-level tamper/reorder/replay/rollback tests.

Important: an Internet-Draft has no IETF standards standing and may change or expire.

Sources:
- https://arxiv.org/abs/2605.11032
- https://www.w3.org/community/ai-agent-memory-interop/
- https://datatracker.ietf.org/doc/draft-khandelwal-bmwg-agent-memory-integrity/

Decision:
Before inventing a XiaoYu-specific portable wire protocol, compare against Portable Agent Memory and current interoperability work. Keep XiaoYu's authoritative SQLite snapshot as an internal artifact for now; treat interchange format as a separate layer.

## H. At-rest integrity / rollback — new explicit benchmark gap

Storage-level integrity work highlights attacks distinct from write-path poisoning:
- content tamper;
- tail/middle deletion;
- reordering;
- forged insertion;
- cross-context replay;
- rollback replay;
- metadata tamper;
- whole-store rollback.

Decision:
Add deterministic at-rest integrity tests before any tamper-evident portable-identity claim. Local checksums stored beside data are not treated as a sufficient external trust root. Do not overbuild cryptography during P1.

## I. Relationship / persona memory — P3 gap expanded

### DyadMem — arXiv:2610.03020
Separates user-side memory from user-conditioned relational agent memory: how this specific agent and user work together.

### PersonaTree — EMNLP Findings 2026
Uses a layered persona lifecycle with support paths from evidence to higher-level persona claims.

Sources:
- https://arxiv.org/abs/2610.03020
- https://aclanthology.org/2026.findings-emnlp.822/

Decision:
P3 should separate user facts/preferences from relationship-specific interaction history/policy. Persona claims need support paths and conservative lifecycle transitions. Do not create an unconstrained persona-growth engine.

## J. Procedural / action memory — deferred gap strengthened

Relevant public benchmarks now include:
- MemoryArena (ICML 2026): interdependent multi-session agentic tasks;
- AMA-Bench (ICML 2026): realistic agent trajectories with states/actions/observations/tool outputs;
- Mem2ActBench (ACL 2026): proactive memory use for tool choice and parameter grounding;
- STATE-Bench: stateful procedural outcomes and repeat reliability;
- LongMemEval-V2: experience/workflow memory with explicit latency.

Sources:
- https://proceedings.mlr.press/v306/he26am.html
- https://proceedings.mlr.press/v306/zhao26bs.html
- https://aclanthology.org/2026.acl-long.370/
- https://opensource.microsoft.com/blog/2026/05/19/introducing-state-bench-a-benchmark-for-ai-agent-memory/
- https://xiaowu0162.github.io/longmemeval-v2/

Decision:
Still defer as a release gate until XiaoYu performs persistent tool/workflow actions, but retain these references now so P4 does not invent a private benchmark later.

## K. Growth, compression and retrieval cost — gap found, not a current blocker

Representative work:
- MemForest — arXiv:2609.08273: structured compression / faster retrieval;
- All-Mem — arXiv:2603.19595: non-destructive consolidation retaining immutable evidence;
- Agent Memory systems characterization — arXiv:2606.06448: phase-aware construction/retrieval/generation cost profiling;
- MemAgent — arXiv:2609.32521: heterogeneous memory selection/routing;
- AgentIR — arXiv:2605.25092: adaptive retrieval cascade.

Sources:
- https://arxiv.org/abs/2609.08273
- https://arxiv.org/abs/2603.19595
- https://arxiv.org/abs/2606.06448
- https://arxiv.org/abs/2609.32521
- https://arxiv.org/abs/2605.25092

Decision:
XiaoYu's FTS5-first, semantic-fallback-only-when-needed direction remains justified. Compression must not destroy authoritative raw evidence merely to improve benchmark latency. No new custom compression/router subsystem in P1; measure real growth pressure first.

## L. Multimodal long-term memory — genuine future scope gap

### Mem-Gallery — ACL 2026
Tests long-term multimodal conversational memory across visual and textual information.

Source: https://aclanthology.org/2026.acl-long.1892/

Decision:
P1/P2 remains text-first. Add a future multimodal scope marker rather than changing the core architecture now. Avoid schema assumptions that make later non-text evidence impossible.

## M. Consolidation / update verification — prior HaluMem direction strengthened

### TrustMem — EMNLP Findings 2026
Adds a memory-transition verifier for coverage, preservation and faithfulness.

### Hindsight Memory-PRM — arXiv:2608.29605
Uses retrieval/citation traces plus controlled deletion-and-reanswer for intervention-calibrated memory-operation credit.

Sources:
- https://aclanthology.org/2026.findings-emnlp.2419/
- https://arxiv.org/abs/2608.29605

Decision:
Keep XiaoYu's deterministic transition validators and independent E1 audits. Intervention-style diagnostics are useful; RL memory management is not a P1 requirement.

## Updated capability gaps after re-saturation

| Capability | Prior coverage | New conclusion | P1/P2 action |
|---|---|---|---|
| Long-horizon recall | strong | no material gap | keep LongMemEval/OmniMemEval |
| Extraction/update hallucination | strong | intrinsic transition eval matters | add transition checks beside QA |
| Provenance/source role | partial | literature richer than prior survey | narrow novelty; retain exact custom contract |
| Authority non-amplification | weak | material missing research line | add write-time authority invariant |
| Deletion closure | partial | behavioral reconstruction gap | add AfterDelete-style audit |
| Memory poisoning | weak | major missing security line | add dedicated security track |
| Cross-principal isolation | weak | privacy/admissibility gap | add principal/scope before shared deployment |
| Derived-state propagation | partial | major diagnostic gap | add dependency/rule-version gate |
| At-rest tamper/rollback | partial | explicit integrity gap | add deterministic integrity suite |
| Cross-model portability | project goal, weak external coverage | existing protocol work found | compare before custom wire protocol |
| Relational/persona memory | exploratory | mature 2026 references found | use DyadMem/PersonaTree in P3 |
| Procedural/action memory | deferred | benchmark ecosystem richer | retain deferred external gates |
| Compression/scale | light | useful references, not blocker | measure first; no P1 subsystem |
| Multimodal memory | absent | genuine future scope gap | mark deferred; keep schema extensible |
| Multi-agent/group memory | absent | genuine future scope gap | defer until product scope expands |
| Intrinsic memory-state evaluation | partial | clear benchmark gap | add alongside final QA |

## Revised architecture implications

The core architecture remains valid, but four requirements become explicit:

1. Authority is write-time origin-bound metadata. It cannot be promoted by summarization, model confidence, tool echo or consolidation without an explicit policy transition.
2. Admissibility precedes model-visible context. Relevant-but-inadmissible memory must not be exposed and then merely ignored.
3. Derived state carries dependencies and rule versions. Implicit upstream changes must invalidate or recompute downstream state.
4. Integrity includes replay/rollback/control state. Correct content with corrupted lifecycle/ownership/freshness metadata is still corrupted memory.

No evidence from this pass justifies replacing the current SQLite + FTS5 + thin XiaoYu policy architecture with another full memory framework.

## Re-saturation conclusion

Round 5 mostly produced additional examples inside the same capability families:
- provenance/authority;
- deletion/forgetting;
- poisoning/security;
- principal/scope isolation;
- derived state;
- intrinsic evaluation;
- portability/integrity;
- persona/relationship;
- procedural/action memory;
- compression/performance;
- multimodal/multi-agent scope.

Therefore broad external research is again closed for current P1/P2 decisions.

Reopen only if:
- a new paper/framework introduces a capability not represented above;
- a retained component changes materially;
- a security advisory affects a retained dependency;
- prospective XiaoYu evidence falsifies one of the current architecture assumptions;
- project scope expands to multimodal, multi-user, multi-agent or persistent tool execution.
