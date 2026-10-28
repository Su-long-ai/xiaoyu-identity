# E2 Token / Cache Optimization Freeze — 2026-10-28

Status: **IMPLEMENTED / FROZEN BEFORE FIRST E2 PAID CALL**

This record documents execution-layer optimization only. The frozen E2 scientific protocol, user-level pilot/confirmatory split, model configuration, scoring targets and claim rules are unchanged.

## Baseline

At E2 entry the historical paid ledger contained 4,561,306 smoke tokens. Cache telemetry over measured historical prompt tokens showed a 37.6218% hit rate, but this pooled heterogeneous smoke/framework experiments and is not an E2 quality or efficiency metric.

E2 benchmark usage at optimization freeze is:

- paid calls: **0**
- used/reserved benchmark tokens: **0**
- pilot hard cap: **1,000,000**
- 95M benchmark allocation remains only a global ceiling.

## Implemented controls

### Stable-prefix execution

Each E2 paid track has a frozen, repository-tracked prompt prefix. The proxy recomputes the byte-stable prefix SHA from all messages before the final dynamic user payload.

Frozen prompt source:
`governance/E2_PILOT_PROMPTS.json`

The prompt strings are byte-identical to their accepted P1 source protocols. Moving them into a tracked freeze file changes no scientific semantics; it removes dependence on gitignored historical workspaces.

The target is >=95% cache reuse for the stable invariant prefix. Whole-prompt hit rate is observational only because case-specific benchmark content is necessarily novel and DeepSeek telemetry does not expose a prefix-only denominator.

### Exact paid-case admission

The benchmark gateway accepts only the scopes and case IDs in:

`governance/E2_PILOT_EXECUTION_MANIFEST.json`

Current paid execution envelope:

| Track | Frozen paid cases | Completion cap |
|---|---:|---:|
| LongMemEval answer | 46 | 512 |
| HaluMem extraction | 32 | 1536 |
| HaluMem QA | 51 | 768 |
| **Total** | **129** | — |

Any old comparator scope, confirmatory case, missing case ID, prefix mismatch, response-format drift or per-track completion-cap violation is rejected before provider access.

### HaluMem engineering subsample

The user-level E2 split remains exactly:
- 2 pilot users;
- 18 untouched confirmatory users.

A full Medium+Long replay of the two pilot users contains 363 session occurrences and 652 QA items. Offline inspection found zero byte-identical Medium/Long session inputs and about 11.7 MB of full pilot session payload. Running the entire operation stream would be incompatible with the frozen <=1M nonpromotional pilot envelope.

Before the first E2 paid call, the execution envelope therefore freezes an engineering subsample *inside the already-frozen two pilot users*:
- one deterministic contiguous 8-session window per (user, variant);
- QA inside each window ranked deterministically by SHA256;
- at most 16 QA per (user, variant);
- selection uses dataset revision / IDs / indices only, never model outcomes or gold answers;
- confirmatory users touched: **0**.

This reduces the paid operation plan from 1061 possible calls to 129 while preserving extraction/update/QA coverage for the nonpromotional engineering pilot. It cannot support an E2 claim.

The selected HaluMem dynamic payload is about 878,806 bytes before fixed prefixes/retrieved context/output, roughly 220k–293k tokens under crude 4–3 bytes/token estimates; actual provider usage remains authoritative.

### Durable duplicate/retry protection

The usage ledger now persists:
- `case_id`;
- `prompt_prefix_sha256`.

A duplicate E2 case in RESERVED, COMMITTED or UNKNOWN state is rejected under SQLite `BEGIN IMMEDIATE`, closing concurrent check-then-insert races.

Checkpoint/resume therefore cannot silently pay for the same case twice. UNKNOWN remains fail-closed until explicit reconciliation.

### Warm-up and concurrency

Per scope:
- first 2 **real frozen pilot cases** execute serially;
- no synthetic paid cache warm-up;
- after two committed cases, bounded parallelism may begin;
- global paid reservation concurrency is hard-enforced at **2**.

This improves the chance that the provider cache has established the invariant prefix before parallel calls arrive without changing case content.

### Budget and cost guards

The provider path enforces all of the following:
- exact E2 scope allowlist;
- exact pilot case membership;
- execution-manifest hash binding;
- protocol/split hash binding;
- prompt-prefix hash binding;
- per-track completion caps;
- 1M E2 pilot hard cap;
- per-scope raw/cache-miss/output/call circuit breakers;
- weekday Beijing 09:00–12:00 / 14:00–18:00 benchmark block;
- confirmatory calls remain forbidden.

The runtime proxy was restarted so these controls are active in memory, not only on disk.

## Telemetry

`research_api.py status` now separates lifetime smoke history from current-phase E2 telemetry:

- phase prompt tokens;
- phase completion tokens;
- phase cache hit/miss tokens;
- phase cache hit rate;
- average prompt/completion/miss per call;
- phase cost estimate;
- E2 pilot hard-cap use / remaining;
- paid and unique case counts.

Use current-phase metrics for E2 decisions.

`e2_token_efficiency_doctor.py --require-ready` audits hashes, split membership, prefix stability, case admission, duplicate paid work, completion caps, peak-hour calls, current token use and scope-level cache/cost telemetry.

## Validation at freeze

- Token Efficiency Doctor: **healthy=true / ready=true**
- targeted API/proxy tests: **35 / 35 PASS**
- full governance regression before final documentation cleanup: **157 / 157 PASS**
- live HTTP negative test: missing E2 case ID -> HTTP 429 before reservation/provider
- benchmark paid calls: **0**
- benchmark used/reserved: **0**
- E2 claim allowed: **false**

Frozen hashes at this record:
- scientific protocol: `0d5805e8a8a773544955724c4490440c237aa1fcdd8876a0d342acad6f2caf14`
- split: `07f209183bea2b1c11c18f2073173a6576df3396396c4ffc520cd18afe3cfd1f`
- prompt freeze: `19300dd3f3cc7c52ae9a4836e637f0bc8b6f7ca20b2cce56649078d48729ddf9`
- execution manifest: `abe84b9c5620b8dd5c1218f96c4d3b09c90a824c13572e1f515f2323254513d6`
- execution freeze record: `f52413c63c877e3a875623e384ba4de4dfd2db41550b5e01615ea0d7e3087851`

## Nonclaims

This optimization does not claim:
- that DeepSeek has already achieved >=95% cache hit on E2;
- that 129 pilot cases are an E2 confirmatory sample;
- that the 1M cap must be consumed;
- that a lower token count is scientifically preferable to required context;
- E2 scientific acceptance or E3/product readiness.
