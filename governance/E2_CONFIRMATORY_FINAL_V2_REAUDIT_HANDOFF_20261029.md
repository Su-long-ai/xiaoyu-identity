# E2 Confirmatory Final V2 Re-audit Handoff — 2026-10-29

Status: **READY FOR NEW INDEPENDENT AUDITOR / NO EXECUTION AUTHORITY**

This handoff supersedes the earlier GPT-4o, qwen3.8-max-0902, and pre-provenance-fix handoffs. The prior independent READY decision `sub-4c0c15b2baad4f6c` does **not** authorize the current package because the shared execution gate and HaluMem judge binding changed afterward.

## Exact current re-audit target

- manifest: `governance/E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.json`
- manifest SHA256: `272270f101bc20a69992aef1e60b53f6634f13f7dcb5c8885978dc31313d474f`
- schema: `xiaoyu-e2-confirmatory-final-reaudit-manifest-candidate-v2`
- unbound required: 0
- LongMemEval confirmatory cases: 454
- HaluMem confirmatory users: 18
- pre-freeze provider exposure: LongMemEval=0, HaluMem=0
- RESERVED/UNKNOWN: 0/0

Key exact control bytes:
- protocol candidate SHA256: `ed085b9bdf3f38746aa8826450a9e5224ab2ec4792c0ea9b86b34dc6b9b8da02`
- implementation bindings SHA256: `825330dc677aa64c02c3988d779b05a6e25d0aff73c9fd33c1694b3ed9e953ae`
- execution manifest SHA256: `beb12ce721648291b0c1441b2533cc4c05ebf0758ff9c938afc3813cb416f782`
- shared execution gate SHA256: `732d036a3684e2ac726f8696199ea72e5ad15f54150bf20af73c8c2fde27544e`

## Lead pre-audit metadata repair

Before assigning the current final-v2 audit, Lead found and fixed one manifest-only evidence-binding defect: the builder read a nonexistent `legacy_accepted_surviving_v5` source key and emitted null. The source audit actually records 9 legacy-accepted cases and 7 cases accepted by both legacy and structural-v5. The builder now reads `legacy_accepted_and_v5_accepted_cases`, fails closed unless the exact 9/7 counts hold, and the rebuilt manifest contains no null values. No confirmatory record/provider/judge call was touched.

## Why a new independent re-audit is mandatory

Two changes invalidate the prior READY scope:

1. **Final-freeze provenance remediation.** The shared gate now requires the final freeze to bind the exact independent re-audit submission, auditor lease/identity, result SHA, receipt SHA and exact re-audit manifest, with registry cross-check. A bare `reaudit_decision=READY_FOR_CONFIRMATORY_FREEZE` can no longer authorize execution.
2. **HaluMem judge rebase.** The unavailable GPT-4o runtime judge was replaced *before final freeze* by a separately frozen Alibaba Model Studio `qwen3.8-flash` judge. This is a new internal scoring baseline, not a claim of GPT-4o or qwen3.8-max-0902 equivalence.

## Current HaluMem judge contract

- provider: Alibaba Model Studio
- model: `qwen3.8-flash`
- temperature: 0
- max_tokens: 16384
- thinking: disabled
- substitution: forbidden
- required synthetic calibration: fresh qwen3.8-flash 12/12; prior judge receipts are not reusable
- external GPT-4o leaderboard/median scores: descriptive reference only, **not a formal gate**
- runtime credential: `DASHSCOPE_API_KEY`
- current credential state: absent; missing credential must block HaluMem judge execution.

The official HaluMem evaluation prompts/code remain frozen as reference; changing the judge intentionally invalidates direct GPT-4o score comparability.

## Required independent checks

The independent Auditor must verify the exact manifest bytes and at minimum:

1. exact split membership and zero pre-freeze confirmatory exposure;
2. exact ACCEPT_E1 dependency closure R47–R52;
3. LME gold/evaluator-metadata isolation, trusted-time contract and typed fail-closed path;
4. HaluMem R52 structural-v5 user projection, assistant raw-history boundary and no destructive auto-confirmation;
5. all 36 Halu predictions seal before any gold/judge access;
6. existing prediction/calibration reuse is bound to durable provider/judge receipts, not local files alone;
7. exact Qwen judge binding, thinking disabled, 12/12 calibration, no runtime substitution;
8. shared execution gate verifies independent re-audit provenance and exact case membership before any reservation;
9. current `research_api.py` / proxy / runner hashes match the manifest;
10. prefreeze and token-efficiency doctors remain green while execution and E2 claims remain false.

Required independent decision:
`READY_FOR_CONFIRMATORY_FREEZE`

## Hard boundary

This handoff itself grants **no** provider-call or execution authority.

Do not:
- read untouched confirmatory outcomes;
- make confirmatory paid calls;
- create a final execution freeze before the independent READY;
- reuse the old READY decision for the current bytes;
- substitute another HaluMem judge if Qwen or its credential is unavailable.
