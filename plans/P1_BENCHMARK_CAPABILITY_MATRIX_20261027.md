# XiaoYu Benchmark Capability Matrix — 2026-10-27

Status: **planning freeze v2; benchmark phase remains locked**

This matrix prevents two kinds of wheel reinvention:
1. building a private evaluation when a public capability benchmark already exists;
2. collecting another memory framework when the missing question is actually security, state semantics, admissibility, deletion, portability or procedural use.

The October-27 trust-layer re-saturation is recorded in plans/P1_TRUST_LAYER_EXTERNAL_GAP_CLOSURE_20261027.md.

| Capability question | Primary benchmark/reference | Current role | Decision |
|---|---|---|---|
| Long-horizon retrieval, update/temporal evidence, assistant-origin recall | LongMemEval-S via OmniMemEval | Already integrated | Keep |
| Extraction/update/QA hallucination propagation | HaluMem | Active local audit/research | Keep; high priority |
| Intrinsic memory-transition correctness independent of final QA | FEB-30 / TrustMem transition-verifier pattern | Reference | Add transition-level checks to E2; do not rely on QA alone |
| Explicit temporal/source/scope restraint | TimlMemBench | External reference | Add targeted prospective slice after P1 freeze |
| Deletion closure and post-delete behavioral reconstruction | AfterDeleteBench + Memora/FAMA | Newly identified gap | Add a small frozen behavioral deletion gate before E2 erasure claims |
| Persistent-memory poisoning across write -> retrieval/use -> repair | MemSecBench; InjecMEM/TMA-NM as attack/defense references | Newly identified security gap | Add dedicated security track; content filter alone is insufficient |
| Query-time relevance versus admissibility / ownership | Retrieval Admissibility + MemLeak | Newly identified privacy gap | Add principal/scope/admissibility synthetic gate now; public multi-user benchmark only if scope expands |
| Implicit derived-state propagation and prerequisite gathering | MemDerive | Newly identified state gap | High-priority P2 diagnostic after event/state integration |
| Long-horizon implicit/composed conversational use | LOCOMO-CONV | Not yet integrated | Add only after P1 pipeline freeze |
| Latent goals, values, user-state constraints under semantic disconnect | LoCoMo-Plus | Not yet integrated | Add only after P1 pipeline freeze |
| Relationship-specific / dyadic memory and persona support paths | DyadMem + PersonaTree | P3 reference | Use as primary P3 external anchors |
| Multi-party speaker belief / role-scoped shared memory | GroupMemBench + COLLABMEM | Outside current single-user P1 scope | Defer, but require before group/multi-agent deployment |
| Procedural/tool-action memory and stateful outcomes | STATE-Bench + MemoryArena + AMA-Bench + Mem2ActBench | Outside current companion P1 scope | Defer until XiaoYu performs persistent tool/workflow actions |
| Experience/workflow memory with latency | LongMemEval-V2 | Future P4 reference | Use when procedural scope opens |
| At-rest tamper/reorder/replay/rollback integrity | Agent Memory Integrity Internet-Draft methodology + local deterministic mutations | Newly explicit integrity gap | Add local deterministic suite before any tamper-evident portability claim; draft is not a standard |
| Cross-model / cross-agent memory portability | Portable Agent Memory + W3C AI Agent Memory Interop CG | Architecture reference | Compare before defining a custom interchange wire format; W3C CG is not a Recommendation |
| Retrieval/maintenance cost and compression under growth | LongMemEval-V2 latency + MemForest / systems-characterization references | Scale reference | Measure real pressure first; no custom P1 compression/router subsystem |
| Multimodal long-term memory | Mem-Gallery | Outside current text-first scope | Defer; keep source schema extensible |
| Generic framework comparison | Mem0 / Hindsight / Cognee / Graphiti | Reference set frozen | Do not add more by default |

## Four-layer scoring requirement

Future E2 results must separate at least four layers whenever the benchmark permits:

1. source/stored-state correctness;
2. derived/current-state correctness;
3. retrieved and admitted context correctness;
4. final-answer correctness.

A correct answer does not prove the memory state was correct, and an inadmissible memory that reached model-visible context is still a privacy/policy failure even if the answer did not quote it.

## Scoring-target freeze

All matched retrieval studies continue to follow plans/P1_BENCHMARK_SCORING_POLICY_20261027.md and predeclare one of:
- RAW;
- SOURCE;
- CANONICAL_CURRENT;
- unchanged external TASK_DEFINED.

Ranked outputs must retain source/authority/temporal/admissibility linkage so target-sensitivity audits can rescore offline without rerunning paid retrieval.

## Benchmark admission gate

A benchmark may be added only when its row answers a capability question not already resolved by this matrix. The Lead must state:
1. the missing capability;
2. why retained benchmarks do not answer it;
3. fixed cost/sample gate;
4. success/falsification criterion;
5. cleanup and reproducibility plan.

New framework count is not a capability. No benchmark addition unlocks the 95M paid phase by itself.

## Scope boundary

P1/P2 remains:
- text-first;
- primarily single-user;
- identity/memory focused rather than a general tool-acting agent;
- external frameworks used as falsification references, not parallel production identity stores.

Multi-user, multi-party, multimodal and procedural/action benchmarks are retained now so future phases can reuse public evaluations rather than invent private ones.
