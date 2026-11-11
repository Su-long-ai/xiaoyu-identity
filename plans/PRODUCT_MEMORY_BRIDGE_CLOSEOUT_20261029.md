# Product Memory Bridge Closeout Status — 2026-10-29

Status: **CURRENT BOUND BYTES INDEPENDENTLY RECHECKED / PRIOR FINAL-SEND P1 CLOSED**

This is a product status record, not a new governance gate.

## Current exact product bytes

- `identity_core.py`: `0be0a8bb19824a42630141c9c0ccaa32a88de6f45229b2c022ad39ffcbf69337`
- `product_memory_bridge.py`: `1ef7e2fd63652beef7aafc97a0e01888894f12eb88c9f49366a4510f15c195ff`
- `model_adapter.py`: `5203fa979238117e889131c0217f2d36acfb7053d962c7208a84841c4da502ef`
- `companion.py`: `141176fdcc7692541b1c730e01d1bdd9a255b7239d53b1d58ff5645e2cc38a65`
- `test_product_memory_bridge.py`: `770688619d717a5ecc8810bd4ad7f0e1f5cb5605d631ab5be4eff33cd0014d16`

## What is now in the real product path

`companion.py` uses `ProductMemoryBridge` for long-term-memory retrieval. The bridge reuses exact accepted R52/R47/R49 authority/current-state components locally and uses SQLite FTS5 only as a derived retrieval accelerator.

Current product behavior:
- user-confirmed memory only enters current state;
- correction supersedes old memory and creates a fresh sourced row;
- retraction/archive removes memory from current recall;
- schema V3 uses durable monotonic `change_seq` for mutation discovery;
- direct/out-of-contract DB drift is still detected through a secondary timestamp/integrity path and quarantined;
- V1 derived handwritten posting DBs are discarded and rebuilt as FTS5;
- V1/V2/V3 identity archives restore to a new home;
- provider switches do not mutate identity or the pre-model identity-context bytes;
- bridge init/recall failure is **fail-closed**: explicit empty long-term memory is passed to `identity_context`, and the UI shows a memory-bridge warning instead of silently invoking legacy recall.

## Independent findings and remediation status

### Same-second ghost — previous P1 productization blocker

Independent Auditor `xy-auditor-independent-20261026-01` reproduced the old bug on pre-remediation bytes:
- retract/archive/correct: 3/3 ghost current memories;
- restart: 3/3 ghosts persisted.

The Auditor then independently rechecked the change-sequence remediation on:
- `identity_core.py` SHA `bcf98f...`
- pre-final-failover-fix bridge SHA `c6a4f4...`

Result:
- same-second ghost failures: **0**
- persistent restart ghosts: **0**
- previous P1: **CLOSED / independently verified**

The current bridge retains the same `change_seq` remediation.

### Bridge-unavailable fallback — previous P2

That same independent recheck found the old companion failover still used `memories_override=None`, which re-entered legacy recall. On 1005 memories, healthy bridge retrieved the long-tail target with zero filler, while legacy fallback missed it and injected 7 zero-overlap rows.

Lead remediation after that audit:
- added `safe_product_recall()`;
- missing/broken bridge returns explicit `[]`;
- `companion.py` always passes that explicit list to `identity_context`;
- UI shows memory-bridge unavailable/abnormal state;
- no legacy long-term-memory fallback occurs.

Targeted remediation tests: **2/2 PASS**.
Current complete product suite: **38/38 PASS**.

Because this failover patch changed exact product bytes after the Auditor submitted, this final P2 remediation is **Lead-verified and awaiting independent recheck**. Do not relabel it independently closed until that recheck occurs.

### Canonical source provenance — P1 remediation

The Independent Auditor reproduced a P1 on the older exact bytes `identity_core.py=bcf98f...` and `product_memory_bridge.py=01c192...`: assistant/system-origin active rows could be laundered into `user_state`, including across export/import.

Current Lead remediation follows the Auditor's minimal reference:
- `IdentityStore.add_memory(..., source_event=...)` rejects non-user canonical source events;
- `ProductMemoryBridge` independently revalidates canonical event actor/kind before admission;
- allowed user-owned kinds are `conversation.user`, `memory.saved`, and `memory.corrected`;
- assistant/system/unknown restored rows are quarantined and never become model-visible `user_state`.

Current targeted provenance tests: **2/2 PASS**. Current complete product suite: **38/38 PASS**. The 5,000-memory longitudinal smoke also passes on the remediated exact bytes. This remediation is **Lead-verified and awaiting independent exact-byte recheck**; the old Auditor P1 remains historically valid for the old hashes and must not be rewritten as if it never occurred.

### Final-send tombstone failure — current P1 remediation

Independent audit of submission `sub-6561399f2267463d` found a real P1 on the prior exact bytes: if a physical-delete tombstone write failed, long-term recall failed closed but old recent-dialog plaintext could still enter the model payload.

Current product remediation is intentionally minimal and located at the final model-send boundary:
- any hard memory bridge/reconciliation error produces explicit empty long-term memory;
- `companion.send` passes the just-recorded current user event ID to `project_history`;
- in that mode all earlier recent dialogue is withheld, so stale/deleted plaintext cannot bypass the memory bridge;
- `quarantined_memories:*` is treated as a visible warning, not a hard bridge failure, so healthy admitted rows/history remain usable.

Current Lead re-verification:
- exact tombstone fault recheck: **16/16 PASS**; deleted plaintext visible **0/16**, current user turn preserved **16/16**, provider calls **0**;
- complete product regression: **38/38 PASS**;
- a separate read-only Codex review found no counterexample in current source and supports the remediation, but is explicitly non-authorizing secondary evidence.

Formal status: **PRIOR_P1_CLOSED_ON_BOUND_BYTES**. Registered independent Auditor xy-auditor-independent-20261026-01 rechecked the handoff-bound exact bytes in workspace fish-eba8bfe5b6864d51: 16/16 tombstone-write failure cases, 16/16 retry-closure cases, 8/8 healthy cases, 8/8 quarantine cases and the complete 38/38 product regression passed. The remaining cold-start/legacy physical-delete path is P2 advisory because physical delete is not currently exposed.

### Proposal freshness

Current `IdentityStore` review path now prevents an older pending literal-preference proposal from being silently promoted after newer accepted/invalidating user evidence. Stale acceptance requires explicit current reconfirmation and creates a fresh canonical user-owned source event; unrelated activity and explicit reaffirmation remain usable. The independent remediation recheck froze **72 lifecycle cases** and reported no new material finding. This is product-review lifecycle hardening and does not change the R47/R52 scientific claim.

## Current product regression

Command:

`py -3.11 -m unittest -v test_identity test_identity_v2 test_product_memory_bridge`

Result: **38/38 PASS**.

Coverage includes migration, canonical-source provenance, memory approval, correction/retraction/restart, FTS5 rebuild, deleted/orphan reconcile, source-text drift quarantine, assistant/system-source quarantine, provider switch continuity, same-timestamp mutation and fail-closed bridge outage.

## Longitudinal 5000-memory smoke

Command:

`py -3.11 tools\xiaoyu_longitudinal_product_smoke.py --count 5000 --repeat 10 --max-median-recall-ms 120`

Latest longitudinal reference from the preceding exact product revision (memory-core performance reference; current send/proposal hardening has not been re-benchmarked at 5,000 rows in this continuation):
- pass: true
- initial build: **32,229.66 ms**
- recall median: **48.96 ms**
- recall p95: **49.25 ms**
- restart: **49.93 ms**
- correction hit: true
- old state absent after correction: true
- retraction absent: true
- restart continuity: true
- restart full reconcile: false
- provenance_invalid_initial_absent: true
- provenance_invalid_initial_quarantined: true
- provenance_invalid_restart_absent: true
- provenance_invalid_restart_quarantined: true

Cold initial construction is the remaining visible performance debt. It does not recur on each conversation and does not currently justify a new memory architecture.

## Stop rule

Do not add another memory framework or governance layer from this point unless:
- independent recheck finds a new product P0/P1;
- longitudinal use exposes a new correctness failure;
- the current cold-build cost becomes a real user-facing blocker.

Next product work after independent recheck should move toward cross-model behavioral identity/persona continuity rather than deeper memory-framework research.

## Cross-model behavior shadow

当前产品 adapter 已增加一等 `qwen` provider：默认 `qwen3.8-flash`，凭据 `DASHSCOPE_API_KEY`，thinking disabled。真实产品 adapter 连通性请求已 PASS（返回 OK，30 tokens）。

`tools/xiaoyu_cross_model_behavior_shadow.py --trials 3` 使用纯合成一次性身份，DeepSeek Flash 3/3、Qwen3.8-Flash 3/3 全部通过，且对身份名、当前城市、更正/撤回状态、鞋偏好的结构化语义完全一致。该 shadow 不读取私人 identity，也不是正式 E2 结论。


## 2026-10-30 budget-aware continuation

The Owner increased the hard total-project API ceiling to **RMB 100**, while retaining staged spending and stop-loss discipline. Formal HaluMem confirmatory prediction remains checkpoint-paused (2626 COMMITTED + 1 historical UNKNOWN; one stream complete and the next at 59/77) rather than discarded. The current Stage-A decision gate remains governance/BUDGET50_HALUMEM_DEV_GATE_V1.json (legacy filename retained because its exact dev proxy is byte-bound): exact-current structural-v5 + R52 semantics on the already-exposed 647-turn / 51-QA pilot, with formal confirmatory bytes and holdout left untouched. Full confirmatory may resume only if this fixed pilot passes the predeclared budget-worthiness thresholds, fresh qwen3.8-flash calibration passes 12/12, and the next-stage cost projection fits the remaining budget.
