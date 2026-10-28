# XiaoYu E2 Pilot Entry Checkpoint — 2026-10-28

Status: **E2 NON-PROMOTIONAL PILOT ENTERED / CONFIRMATORY CLAIMS LOCKED**

## Transition completed

The project has formally left the paid `smoke` phase and entered the frozen E2 pilot execution phase.

- P1 integration: **12 / 12 READY**
- P2 closeout: **7 / 7 READY**
- P2 active research: **0**
- P2 pending E1 audit: **0**
- E2 pilot protocol: **FROZEN_BEFORE_EXECUTION**
- protocol SHA256: `0d5805e8a8a773544955724c4490440c237aa1fcdd8876a0d342acad6f2caf14`
- split manifest SHA256: `07f209183bea2b1c11c18f2073173a6576df3396396c4ffc520cd18afe3cfd1f`
- benchmark paid phase: **UNLOCKED**
- control-plane phase: **E2_PILOT**
- self-directed research: **CLOSED**
- confirmatory calls: **FORBIDDEN**
- E2 scientific claim: **NOT ALLOWED**
- E3/product claim: **NOT ALLOWED**

## Smoke exit

Smoke exit passed with:
- used/reserved: **4,561,306 / 5,000,000**
- unused smoke contingency: **438,694**
- UNKNOWN calls: **5** (unchanged frozen fail-closed reserve)
- RESERVED calls at transition: **0**

Unused smoke allowance was not consumed merely to reach the cap.

## Benchmark unlock

`governance/BENCHMARK_PHASE_UNLOCK_RECORD.json`

Unlock record SHA256:
`bb331ea8de41564dcb0c03577b70ef45b516459e5d3c8a0070be1c03050a8b88`

The paid research gateway now reports:
- active_phase: `benchmark`
- benchmark_unlocked: `true`
- benchmark phase used/reserved: **0 / 95,000,000**
- benchmark remaining: **95,000,000**

This unlock authorizes only execution under the already frozen E2 pilot protocol.

## Frozen pilot scope

Required tracks:
1. LongMemEval-S pilot — 46 already-exposed/frozen pilot cases; 454 confirmatory cases remain untouched.
2. HaluMem pilot — 2 frozen pilot users; 18 confirmatory users remain untouched.
3. Trust-layer controls — accepted R21/R22/R24 and frozen P1/P2 controls; no new private benchmark.

The pilot is explicitly **NONPROMOTIONAL**:
- pilot quality metrics are descriptive only;
- pilot results cannot support an E2 claim;
- confirmatory thresholds/protocol must be frozen separately before any confirmatory call.

## Cost-window state at entry

Benchmark paid calls remain subject to the existing Beijing weekday peak guard:
- blocked windows: **09:00–12:00 and 14:00–18:00**
- current entry occurred inside the **14:00–18:00 blocked window**

Therefore no paid E2 benchmark call was forced during this transition. Entering E2 does not override the cost policy.

## Regression invariants

The transition preserves:
- frozen P1 contract/candidate hashes;
- P2 integration readiness;
- Build-vs-Reuse enforcement;
- no private identity data in paid benchmark scope;
- all paid calls must use an allowlisted local proxy;
- source/authority/admissibility/privacy failures remain fail-closed.

## Exact interpretation

The project is now **in E2 pilot execution stage**, but it has **not achieved E2 scientific acceptance**.

The next scientific transition is:
E2 pilot execution -> pilot audit -> freeze separate confirmatory thresholds/protocol -> untouched confirmatory execution -> independent formal audit -> only then evaluate whether an E2 claim is warranted.


## Entry validation

After the phase transition:
- governance regression: **148 / 148 PASS**;
- P1 Integration Doctor: **12 / 12 READY**;
- P2 Integration Doctor: **7 / 7 READY**;
- Reuse Doctor: **healthy=true, errors=0, warnings=0**;
- phase-priority: **E2_PILOT**, closeout mode active, no self-directed work;
- benchmark reservation preflight during the Beijing weekday peak window was rejected **before reservation/provider call**;
- benchmark phase used/reserved remained **0**;
- COMMITTED/UNKNOWN call counts were unchanged by the peak-guard preflight.

The E2 pilot is therefore open and frozen, but paid execution remains naturally dormant until an allowed cost window or an explicit policy change.


## Token-efficiency hardening

Before the first E2 paid call, the execution layer was hardened and frozen separately from the scientific protocol. See `plans/E2_TOKEN_OPTIMIZATION_FREEZE_20261028.md` and `governance/E2_PILOT_EXECUTION_FREEZE_RECORD.json`.

The E2 engineering pilot now has an exact 129-case paid envelope and 1M-token hard cap. The scientific protocol/split remain unchanged and confirmatory users/cases remain untouched.
