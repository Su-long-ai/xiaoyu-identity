# XiaoYu P2 Closeout / Smoke-Exit Gate Checkpoint — 2026-10-28

Status: **P2 CLOSEOUT IN PROGRESS / SMOKE EXIT LOCKED**

## Frozen baseline

P2 is evaluated strictly on top of the frozen P1 integration-ready baseline:

- P1 contract SHA256: `b8dcb1659f40886e984a3531dcaf11f4858d38252935d70bb3ca3332dc9e4668`
- P1 candidate SHA256: `2a20aa552c4bc50356f6bffeaa08cb58b8f40d1c9302586aea8b43c4bc78fe83`
- P1 remains 12/12 integration-ready; E2 is not granted by P2.

## P2 closeout contract

`governance/P2_INTEGRATION_CONTRACT.json` currently requires seven stages:

1. R23 derived-state dependency propagation — ACCEPT_E1.
2. R25 whole-store rollback/integrity — ACCEPT_E1.
3. R24 behavioral erasure closure — closed by named ACCEPT_E1 remediation; original NEEDS_WORK remains immutable.
4. Direct-conflict blocker — pending independent review.
5. Derived formal-context authority — pending independent review.
6. Runtime validation of the external freshness anchor — ACCEPT_E1.
7. Derived-rule admission atomicity — original candidate NEEDS_WORK after deterministic concurrency falsification; named atomic repair is active.

The rule-admission concurrency defect is concrete:
- original direct watermark race: 12/12 independently reproduced;
- original same-output rule race: 12/12 independently reproduced;
- Lead E0 BEGIN IMMEDIATE same-connection repair: direct race 64/64 safe, rule race 64/64 safe, serial smoke PASS;
- the Lead did not start a duplicate task after discovering Research B had already claimed the equivalent repair. R46 was marked superseded before execution.

## Smoke budget state at gate construction

- active paid phase: smoke
- smoke cap: 5,000,000 tokens
- used/reserved: 4,561,306
- remaining: 438,694
- benchmark unlocked: false
- UNKNOWN outcomes: 5 (existing fail-closed reserve)

Remaining smoke budget is contingency. Exhausting it is explicitly **not** an exit condition.

## E2 protocol candidate

`governance/E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json` is still `DRAFT_PRE_FREEZE`.

Required core tracks are now fingerprint-ready:

### LongMemEval-S
- 500 records
- SHA256 `D6F21EA9D60A0D56F34A05B609C79C88A451D2AE03597821EA3D5A9678C3A442`

### HaluMem
Pinned public dataset revision:
`cb04336aa1b732d4b24f5186c552456b4099806e`

- Medium: 33,511,525 bytes; 20 users; 1,387 sessions; 60,146 dialogue turn records; 14,948 memory points; 3,467 questions; SHA256 `486fbc130a5c8781a2af27ffa508a1d7855245137aa449c193ac4d29c45634e7`
- Long: 106,535,674 bytes; 20 users; 2,417 sessions; 107,032 dialogue turn records; 14,948 memory points; 3,467 questions; SHA256 `dfdbed570b402b7b8c17e0d7808fc6f3ae7a53b6144f18feb16bbdd3f55cb0c9`

The public files are cached only under gitignored `external/halumem_dataset_cache`.

### Trust-layer controls
Reuse accepted R21/R22/R24 synthetic/prospective receipts. No new private benchmark and no private identity data.

## Smoke exit mechanism

`governance/smoke_exit_doctor.py` is read-only and local.

It requires:
- pinned evaluation-policy hashes unchanged;
- P1 integration ready;
- P2 closeout ready;
- no active or pending P2/protocol-pre-freeze scope;
- E2 protocol status `FROZEN_BEFORE_EXECUTION`;
- all required E2 tracks fingerprint-ready;
- smoke phase still within cap;
- benchmark still locked before the explicit phase switch;
- UNKNOWN outcomes not increased beyond the frozen five.

`governance/freeze_e2_protocol.py` is also fail-closed:
- default mode is dry-run;
- `--freeze` is permitted only after all pre-freeze conditions pass;
- it never changes paid phase;
- it never grants E2/E3.

The later paid-phase switch must be a separate explicit Lead action after smoke-exit PASS.

## Current blockers

At this checkpoint smoke exit remains locked until:
- derived formal-context authority is independently accepted;
- direct-conflict blocker is independently accepted;
- atomic rule-admission repair is independently accepted;
- E2 pre-freeze integrity work/audit is quiescent;
- the protocol is then frozen before execution.

No additional external framework or large paid smoke is justified by these blockers.
