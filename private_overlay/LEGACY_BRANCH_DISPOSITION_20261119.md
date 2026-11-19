# Legacy branch disposition — 2026-11-19

Product frontier: `private/neko-overlay-v1`

## Decision rule

N.E.K.O is the single runtime authority for memory, persona evolution, tasks/effects, voice, vision, tools and plugin execution. A legacy XiaoYu implementation branch is not merged merely because it contains more code or more tests.

For every legacy branch:

1. Preserve a product requirement only if it still matters to the private XiaoYu product.
2. Express that requirement as an overlay acceptance test or live evidence first.
3. Prefer N.E.K.O configuration or a mature external component.
4. Add a private adapter only if the acceptance test still fails.
5. Patch N.E.K.O core only as a last resort, with a reproduced live gap and bounded patch budget.
6. Never revive a second memory/persona/task/effect authority.

## Branch disposition

| Branch | Disposition | Reason |
| --- | --- | --- |
| `feat/product-reuse-gate` | **ABSORBED** | The core reuse-policy, catalog, guard, gate, CI and test files are byte-identical in the product frontier. Git ancestry differs, product content does not. |
| `feat/reuse-first-credentials` | **ABSORBED / ANCESTOR** | Already in the overlay history. |
| `feat/reuse-first-memory-retrieval` | **ABSORBED / ANCESTOR** | Already in the overlay history. |
| `feat/reuse-first-runtime-adapters` | **ABSORBED / ANCESTOR** | Already in the overlay history. |
| `feat/r20-product-controls` | **REPLACED BY MOTHER PROJECT** | The branch extends the old `xiaoyu/*` memory/relationship runtime. N.E.K.O now owns memory/persona state. Keep only user-visible control requirements as overlay acceptance tests if a real gap appears. |
| `fix/provider-fallback-privacy-isolation` | **REQUIREMENT CARRIED FORWARD; LEGACY RUNTIME NOT MERGED** | Provider privacy remains a product requirement. It is enforced in the overlay provider policy/preflight and has live product evidence. Do not re-import the old `model_adapter.py` / `send_guard.py` fallback runtime. |
| `fix/recovery-restore-erasure-migration` | **REPLACED; ACCEPTANCE RETAINED** | N.E.K.O owns persistent memory and has native forget/tombstone fencing. Overlay live evidence already covers scoped erasure, erase-race fencing and no resurrection. Do not restore a parallel XiaoYu persistence/recovery authority. |
| `redteam/recovery-state-continuity-r20` | **QUARANTINED LEGACY HARDENING** | It hardens the retired XiaoYu canonical store and R20 controls. Re-open only if a concrete N.E.K.O disaster-restore product failure is reproduced. |
| `fix/redteam-execution-reliability-sprint` | **REPLACED BY N.E.K.O TASK/TOOL RUNTIME** | It hardens the retired XiaoYu effect/outbox/authorization runtime. Bring back individual invariants only when a real non-idempotent action in N.E.K.O fails an overlay acceptance test. |
| `fix/redteam-occurrence-effect-exclusivity` | **QUARANTINED LEGACY HARDENING** | Same retired effect/outbox authority. No merge without a reproduced N.E.K.O product failure. |
| `fix/redteam-scheduled-purpose-occurrence-binding` | **QUARANTINED LEGACY HARDENING** | Same retired scheduler/effect authority. N.E.K.O is authoritative for tasks. |
| `fix/redteam-r20-privacy-freshness` | **REQUIREMENTS RETAINED; IMPLEMENTATION REPLACED** | Private audience isolation and freshness remain mandatory. Current live group-canary evidence and provider privacy gates cover the product requirement without reviving the old context/product-control runtime. |

## Current frontier evidence

As of 2026-11-19:

- private QQ roundtrip: PASS
- real trusted group roundtrip: PASS
- unauthorized group blocking: PASS
- owner-private canary non-disclosure in real group: PASS
- identity continuity across restart: PASS
- identity continuity across provider/model swap: PASS
- correction behavior: PASS
- scoped erasure: PASS
- no resurrection after restore/restart: PASS
- erase race generation fence: PASS
- proactive delivery: PASS
- vision: PASS
- tool invocation: PASS
- TTS: PASS
- realtime voice transport: PASS
- physical microphone utterance: PENDING
- provider privacy: automatic gate PASS; owner-side final recheck remains

## Consequence

The old branches remain useful as adversarial requirement libraries, not as code sources to merge wholesale. New work should target the N.E.K.O-backed product frontier and convert any valuable old invariant into a failing product acceptance test before implementation.
