# R49 deterministic destructive-semantic guard stop-loss — 2026-10-29

Status: **STOP_LOSS_REACHED / STRUCTURAL V6 RETAINED / LEXICAL CLOSEOUT PATH CLOSED**

## Evidence

R49 v6 current SHA:
`88fcc4b47970424d066ad4d01a96e188a6fd1871d3cd10004d80c37a75c89e30`

v6 remains strong on development/regression material:
- v6 grounding: 96/96
- auditor first-order replay: 40/40
- auditor second-order replay: 64/64
- legacy semantic gold: 96/96
- v3 regression: 120/120
- low-overlap conflict/ambiguity: 32/32
- R47 state guard: 104/104
- RE-B mixed-clause set improved from 16/40 to 40/40
- governance regression: 177/177

However two external prospective sets remain materially failed after the mixed-clause repair:

1. Independent Auditor third-order prospective80, frozen before v6:
   - SHA `fe0cc8292933222679f72391a4057dbe0a79cb054f4b9e461385d43ecc376336`
   - latest v6: **40/80**
   - false accepts remain in negated non-change, reported question, same-clause negated decoy and third-party switch;
   - valid `drop` retraction remains rejected.

2. Lead fresh prospective150, generated only after semantic-adjudicator prompt/protocol freeze:
   - SHA `37d24b18e0882ac45cb746cc18b5544e8e0bc4fc6cb686d101307cd5406d7226`
   - latest v6: **98/150**
   - same-clause decoy 0/10;
   - ambiguous undecided 1/10;
   - negated non-change 1/10;
   - quoted/third-party false 1/10 each.

The latest v6 change turned its own mixed-clause development set green but produced **zero improvement** on either external prospective set.

## Decision

Keep v6 deterministic mechanisms that are genuinely structural:
- candidate discovery and component completeness;
- caller-owned target IDs;
- source role / authority / lifecycle ownership;
- exact source/evidence binding;
- ambiguity fail-closed;
- conflict-component integrity;
- R47 state transition/replay/determinism.

Do **not** accept further lexical/regex cue growth as sufficient R49 closeout evidence unless a materially new falsifiable mechanism improves a previously untouched prospective set.

Destructive semantic authorization now requires one of:
1. independently evaluated semantic adjudication for E2 research; or
2. explicit user confirmation boundary for product mutation.

The current frozen semantic-adjudicator prefreeze is documented in:
`plans/R49_SEMANTIC_ADJUDICATION_PREFREEZE_20261029.md`

This stop-loss does not reject v6 as a structural safety layer and does not authorize paid adjudicator execution or E2 acceptance.
