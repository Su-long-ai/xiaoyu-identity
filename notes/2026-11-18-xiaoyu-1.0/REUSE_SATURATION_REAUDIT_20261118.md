# Reuse-first saturation re-audit — 2026-11-18

Baseline: `fix/r18-release-manifest-bindings` (`f840460`).

## Decision rule

XiaoYu owns semantic authority and policy. Mature external components own commodity capability. External components may produce observations/candidates/results, but they do not become identity, memory, authorization, Purpose, Effect, erasure, restore, or release authority.

A replacement is accepted only when it reduces custom machinery without weakening: principal/audience/context isolation, per-attempt freshness, disclosure uncertainty, erasure fences, deterministic rebuild, or release/runtime digest binding.

## From-scratch module verdict

| Area | Verdict | External reuse / reason |
|---|---|---|
| Contracts / envelopes | KEEP | Small authority contracts; Pydantic would add dependency without removing core semantics. |
| SQLite persistence / migrations | KEEP | Native SQLite transactions, WAL and Online Backup API already provide the right substrate. |
| Canonical Event / Claim / R9 Temporal Truth | KEEP | XiaoYu authority kernel; external memory frameworks remain candidate/extraction/retrieval sources only. |
| Authorization / Effect / Outbox / Receipt | KEEP | Defines who may act and whether an external effect may already have happened. |
| Purpose / occurrence / miss policy | KEEP | Semantic scheduling authority; generic schedulers may only provide wake-up signals later. |
| Provider compatibility | REUSE | LiteLLM single-attempt backend is adopted. XiaoYu retains cross-provider fallback and per-attempt revalidation. |
| Provider disclosure boundary | KEEP | Requests/LiteLLM hooks do not expose an exact post-body-send boundary; custom transport fence remains justified. |
| Provider secrets | ADOPT | Prefer OS keyring (Windows Credential Locker); env stays deployment override; plaintext key file becomes legacy fallback. |
| Lexical retrieval | ADOPTED | SQLite FTS5 unicode61 + trigram + RRF replaces handwritten token overlap. |
| Semantic retrieval | TRIAL | FastEmbed shadow already works. Persistent same-SQLite vector index should trial `sqliteai-vector==1.1.2` before adding a separate vector DB. |
| Memory extraction / entity linking | RE-EVAL | Mem0 v3 and AgentOS mechanisms materially changed in 2026; benchmark as candidate producers, never authority. |
| Memory-use gate | KEEP BASELINE + TRIAL | Deterministic high-confidence gate is safe; uncertain cases may trial a classifier only under paired quality/cost evaluation. |
| Profile / Relationship / Promise | KEEP | Rebuildable projections/ledgers over XiaoYu authority. |
| Resource telemetry | ADOPTED | psutil + NVML provide machine state; ResourceBroker retains policy/leases. |
| Vision capture | ADOPTED / OPTIONAL | MSS stays low-rate default; DXcam is an optional Windows high-rate/game capture candidate. |
| Vision analysis | REUSE | Use replaceable external/local vision providers; no custom OCR/vision model. |
| Voice orchestration | ADOPTED | Pipecat owns audio pipeline/turn mechanics. Local engine candidates: sherpa-onnx (VAD/ASR/speaker) and Qwen3-TTS. |
| Guardian telemetry | ADOPTED | OpenTelemetry metadata sink; XiaoYu keeps independent checks. |
| Recovery / erasure | KEEP | SQLite backup + XiaoYu restore quarantine/fences are authority-specific. Litestream may later be a remote replica transport only. |
| Release authority | KEEP + HARDEN LATER | Internal release state stays XiaoYu-owned; Sigstore can sign artifacts and TUF can secure a future updater. |
| Long-running external tools | REUSE LATER | Target MCP 2026-07-28 Tasks extension rather than inventing remote polling. Purpose/Effect still own internal intent/effect state. |
| Third-party skill sandbox | REUSE LATER | Wasmtime/WASI Component Model remains the 1.x sandbox route. |
| Process-tree supervision | TRIAL WHEN NEEDED | Windows Job Objects should replace single-process kill logic once real sidecars spawn descendants. |
| File/config hot reload | REUSE WHEN NEEDED | watchdog 7.x rather than polling. No current requirement forces it into 1.0. |
| Cross-device multi-writer authority | HOLD | Automerge/Loro/sqlite-sync solve CRDT sync, but adding CRDT semantics now would create a second conflict model. Revisit only with real offline multi-writer requirement. |
| Durable workflow engine | HOLD | DBOS/Temporal are useful for future long workflows, but duplicate current Purpose/Effect durability for 1.0. |
| State-machine fuzzing | TRIAL | Hypothesis RuleBasedStateMachine is a strong fit for R9/Effect/Restore sequence red-team; keep it dev/test-only first. |

## New 2026 evidence that changes older decisions

### Mem0 v3

The 2026 OSS algorithm moved to single-pass ADD-only extraction and semantic + keyword + entity multi-signal retrieval. Old Mem0 2.x call/token-cost evidence is therefore not sufficient to reject v3. Re-run it as a comparator/candidate extractor. Do not make it authority.

### Embedded vector search

Two same-SQLite candidates were rechecked on Windows Python 3.11.9 / SQLite 3.45.1 with 384-d synthetic vectors.

- `sqlite-vec==0.1.9`: loaded successfully. 1k median KNN 0.543 ms; 10k 2.378 ms. Pre-v1; DiskANN is still alpha.
- `sqliteai-vector==1.1.2`: loaded successfully, AVX2 backend. 1k exact-scan median 0.129 ms; 10k 1.423 ms. PyPI 1.1.2 declares Apache-2.0 and has Trusted Publishing provenance.

Decision: `sqliteai-vector==1.1.2` is the stronger first trial. Do not replace FTS5+FastEmbed product ranking until paired retrieval/final-QA evidence demonstrates global benefit. No LanceDB/Qdrant dependency is justified yet.

### Windows credentials

`keyring==25.7.0` was installed in an isolated venv on this machine. Runtime selected `keyring.backends.Windows.WinVaultKeyring` with priority 5; a read-only lookup of a nonexistent test entry returned `None`. No credential was written.

Decision: OS keyring becomes preferred optional secret source; environment variables remain explicit deployment override; plaintext key files remain compatibility fallback only.

## External systems explicitly not promoted into 1.0 authority

- Graphiti/Zep: temporal graph/provenance remains a useful derived-graph mechanism, but current deployment still introduces graph-service infrastructure and prior XiaoYu cost probes were unfavorable.
- Hindsight: strong comparator and model/mechanism source; Postgres/vector runtime is too large for the local SQLite authority.
- Supermemory: useful comparator/API, but the memory engine is not fully open source and must not own XiaoYu truth.
- AgentOS: strong open mechanism reference for classifier routing, BM25+dense fusion and reranking; TypeScript agent framework is not a reason to replace XiaoYu core.
- MemOS/Letta/LangMem: useful memory abstractions and candidate producers, not replacements for authority.
- OPA/Cedar: defer until household/third-party policy complexity exceeds the current small deterministic policy.
- APScheduler 4: still pre-release; do not migrate the 1.0 scheduler.
- Celery: Windows remains unsupported; reject for this product.

## Near-term execution order

1. Finish R20 Memory Control / onboarding/offboarding without touching the authority boundary.
2. Merge the Keyring adapter after full regression.
3. Add a fixed paired retrieval trial: FTS5 baseline vs FastEmbed shadow vs FastEmbed + `sqliteai-vector==1.1.2`; quality must be identical-or-better and stale/deleted injection remain zero.
4. Re-run Mem0 v3 as a bounded external comparator on the same frozen memory benchmark; extract useful mechanisms, not authority.
5. Add Hypothesis stateful red-team before R22 soak if CI cost remains small.
6. R21 Desktop↔QQ E2E, then R22 soak/freeze.
7. When packaging an updater, use Sigstore + TUF rather than inventing signing/update metadata.

## Saturation stop condition

The final search rounds produced no new component that changes the authority architecture. New findings only refine implementation choices inside already-replaceable modules (credentials, vector index, capture, tool-task protocol, release distribution). Further broad searching is therefore lower value than running the frozen trials above.
