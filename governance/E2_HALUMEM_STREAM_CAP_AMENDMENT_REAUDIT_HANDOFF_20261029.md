# E2 HaluMem Confirmatory Stream-Cap Amendment Independent Audit — 2026-10-29

Status: **AUDIT ONLY / EXECUTION NOT AUTHORIZED**

## Why this exists

The exact base final manifest froze:
- max_case_calls = 10,000
- max_calls_per_stream = 768

Recovery V2 safely reached the old per-stream boundary:
- durable ledger: 767 COMMITTED + the original 1 UNKNOWN
- current stream: m / uuid_hash prefix 8e00ab0ec2dd
- next case: hm-c-m-8e00ab0ec2dd-s36-t22
- next case has an immutable request intent but no durable ledger row and no response receipt
- therefore the 429 occurred before provider dispatch.

A structural-only byte scanner then established the real frozen case shape:
- pilot control: observed 7,900 user turns == pre-existing frozen 7,900
- confirmatory streams: 36
- exact confirmatory semantic calls required: 75,691
- max per stream: 2,917
- min per stream: 1,296
- streams over old 768 cap: 36/36
- gold fields materialized: 0
- provider calls during structural count: 0

## Exact candidate

- amendment:
  governance/E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json
  SHA256 f1a5dbbf40c7391017cfe5781f7504978d0277899a20b313dd08c798a0217b84
- gateway shim:
  governance/confirmatory_stream_cap_gateway_v1.py
  SHA256 a7120f137a3fa6549ffdf14fe15aa55a6786e1a374c48c52f780582425ebf7fa
- dedicated proxy shim:
  governance/research_api_proxy_recovery_cap_v1.py
  SHA256 b7eeddfb2e93c8e1ff4a1155fc79255ddb4b046b7d2f2249f2cdcb511f223eb2
- structural scanner:
  governance/lead_workspaces/halumem_stream_shape_20261029/count_safe_roles.py
  SHA256 5ba52539c20ab7fd542889f9cf371404a5abbc69e029f1d2bd3fd1c4bc10d2d7
- structural result:
  governance/lead_workspaces/halumem_stream_shape_20261029/HALUMEM_SAFE_STREAM_COUNTS.json
  SHA256 80a00c37b67d80cb53ad92af705075e412283267f446592257b2c58323ad6e01
- offline tests:
  governance/test_halumem_stream_cap_amendment_v1.py
  current Lead result 6/6 PASS.

## Amendment semantics

Only these two numbers change:
- max_case_calls: 10,000 -> 75,691
- max_calls_per_stream: 768 -> 2,917

Everything else must remain identical to the base Halu semantic track:
case membership, variants, case-id rule, session/turn bounds, max completion tokens,
response format, prompt/schema/prefix hashes, duplicate paid-case rule,
RESERVED/UNKNOWN no-retry rule, serial state order, recovery V2 checkpoint/request
binding, qwen3.8-flash post-seal 12/12 calibration.

The original research_api.py and research_api_proxy.py remain byte-identical to the
base final freeze. The dedicated loopback proxy reuses the exact original HTTP
handler and ResearchApiBudget, wrapping only validate_confirmatory_case() after
separate amendment authorization. In E2_CONFIRMATORY it rejects any budget scope
other than the Halu semantic confirmatory scope. LongMemEval remains disabled.

## Required independent READY checks

Formal READY requires result.json with:
classification = READY_FOR_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE
decision = READY_FOR_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE
amendment_sha256 = f1a5dbbf40c7391017cfe5781f7504978d0277899a20b313dd08c798a0217b84
findings = []

checks, all true:
- exact_candidate_and_parent_hashes
- safe_scanner_uuid_role_only
- pilot_7900_control_exact
- confirmatory_counts_36_75691_2917
- cap_hit_boundary_no_provider_dispatch
- only_two_numeric_caps_change
- base_gateway_bytes_unchanged
- amended_proxy_halu_only
- longmemeval_remains_disabled
- authorization_fail_closed_without_freeze
- provider_calls_during_audit_zero
- judge_calls_during_audit_zero
- gold_reads_during_audit_zero

Required family:
audit.e2.confirmatory.halumem_stream_cap_amendment_v1

Required auditor identity:
xy-auditor-independent-20261026-01

No provider/judge/gold access is permitted during this audit.

After exact READY only, Lead may run:
py -3.11 governance/build_e2_halumem_stream_cap_amendment_freeze_v1.py

The resulting freeze still requires exact policy registration before the amended
proxy can start. Any candidate/gateway/proxy byte change invalidates this audit.
