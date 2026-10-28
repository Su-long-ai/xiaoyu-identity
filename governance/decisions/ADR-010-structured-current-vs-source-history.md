# ADR-010 — Separate canonical current-state projection from immutable source history

Status: Accepted P1 semantic boundary
Date: 2026-10-28
Trigger: R40 prospective semantic falsification

## Context

The caller-bound whole-message extractor was tested under a clean pre-frozen contract in R40:
- fresh 32-case / 82-event challenge;
- two independent paid rounds;
- 64/64 COMMITTED authenticated HTTP-proxy calls;
- exact frozen scope;
- 24,813 raw tokens <= 32,000 cap;
- zero unsupported events;
- zero structural failures.

Both rounds reproduced the same failure pattern:
- full outcome/semantic/source sequence exact: 29/32;
- final state exact: 32/32;
- the same three cases omitted earlier transient same-slot SET/CLEAR events.

Therefore the provider/model is reliable for the effective final state on these cases but not for a lossless structured account of all state transitions that occur and are superseded inside one source message.

## Considered options

1. Keep repeating or prompt-tuning the same full-sequence contract until it passes.
2. Add clause routers / more model calls to force event enumeration.
3. Rescore R40 post hoc as final-state-only and call it a pass.
4. Explicitly split representations:
   - immutable raw source message = historical evidence;
   - structured projection = final effective SET/CLEAR per slot for current-state processing;
   - cross-message typed-state history remains structured under trusted effective time;
   - no P1 claim of lossless structured transient history inside one utterance.

## Decision

Choose option 4.

R40 remains NONPASS under its frozen full-sequence target. It is never rescored into a pass.

R35 is reopened prospectively to test the weaker-but-explicit P1 projection contract on fresh cases. Its promotion evidence must be entirely new and pre-frozen.

## Required semantics

For each trusted source message:

1. Preserve the immutable full source text and source identity.
2. Validate model candidates with the accepted strict grounding boundary.
3. Deterministically order grounded candidates by source anchor.
4. For each slot, retain at most the final effective grounded SET/CLEAR for canonical state projection.
5. Preserve distinct slots independently.
6. Fail closed when final meaning or grounding is ambiguous.
7. Never infer user authority from the model output.
8. Store/retrieve raw source separately as SOURCE/history evidence.

Across messages, final per-slot projections remain structured typed-state history under trusted globally comparable effective time.

## Explicit non-claims

P1 does not claim:
- a lossless structured timeline of every transient state mentioned and superseded within one source message;
- reconstruction of such transient events from the canonical state table alone.

Historical questions requiring those details must use the immutable source evidence and must not fabricate missing structured events.

## Why this is not deletion of history

The raw utterance is never replaced by the canonical projection. The projection is a purpose-specific current-state representation. Source history and canonical current state have different scoring targets and different authority roles.

This aligns with the existing RAW / SOURCE / CANONICAL_CURRENT benchmark scoring policy.

## Revisit when

Reopen lossless structured intra-message history only if:
- a materially different extraction method demonstrates prospective reliability on the known R40 failure families; and
- the added cost/complexity is justified by a real product requirement rather than benchmark completeness alone.
