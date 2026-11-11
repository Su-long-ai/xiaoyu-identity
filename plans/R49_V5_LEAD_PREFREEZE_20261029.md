# R49 v5 Lead pre-freeze handoff — 2026-10-29

Status: **FROZEN BEFORE V5 IMPLEMENTATION**

Current direct E2 closeout blocker: R49 only.

## Why v4 cannot be promoted

Pending v4 submission:
- submission: `sub-a7020a325f364b9a`
- contract SHA256: `927c9787ee487ae5868ac1c686224097fb552e4ec4cb31a6e27eec6661b80d7f`

The submitted v4 self-checks are strong but incomplete:
- public updates safe 16/16;
- unrelated singleton destructive blocked 32/32;
- duplicate registered components 32/32;
- old v3 contract 120/120;
- auditor holdout 64/64;
- forbidden target forgery rejected 80/80;
- hostile 19/19;
- determinism 1280/1280.

Post-freeze independent/OOD evidence falsifies promotion:

1. **Equivalence over-grouping**
   - frozen v5 OOD: v4 passes only 40/120;
   - duplicate_without_registry 0/20;
   - incomplete_registry 0/20;
   - shared_anchor_distinct 0/20;
   - two_distinct_relevant 0/20.
   - lexical overlap is incorrectly used to invent destructive component membership.

2. **High-fanout prefilter false negative**
   - at fanout 25/32/48/64/96 the default bounded pool drops the uniquely correct target;
   - full admissible-pool scoring recovers it in all 5/5 cases.

3. **One-way conflict state**
   - 4/4 synthetic conflicts are created successfully;
   - later clarification sees zero prior candidates and binding_mode=missing because user_conflict is excluded;
   - the frozen R47 store resolves the same full conflict component correctly when caller supplies it.

4. **Cross-subject destructive mutation**
   - 16/16 overgroup probes merge “my X” and “my sister’s X” into one lexical component;
   - validator accepts the destructive response;
   - all 16 unrelated sister claims are actually superseded.

These are safety/correctness blockers, not cache or cost advisories.

## Frozen v5 Lead gate

Directory:
`governance/lead_workspaces/r49_v5_gate_20261029`

Gate:
`R49_V5_LEAD_PREFREEZE_GATE.json`

Gate SHA256:
`5f5b5c68130be348cdb6e454ad0ee67e51976326320cd33fe2c3943ce3853347`

Doctor:
`r49_v5_lead_gate_doctor.py`

Current exact-v4 result:
**FAIL**, with the eight material failure records expected from the frozen negative controls.

## Required v5 semantic boundary

The remediation must separate three concepts that v4 conflates:

1. **relevance** — may use lexical scoring to find likely targets;
2. **equivalence/object identity** — must be caller-owned / explicitly registered, never inferred solely from shared lexical anchors;
3. **conflict component membership** — must come from the trusted R47 state graph and be available for explicit resolution.

Required properties:
- lexical overlap may rank candidates but may not merge destructive components;
- absent/incomplete equivalence registry fails closed;
- shared-anchor distinct claims remain distinct;
- multiple distinct relevant claims remain ambiguous;
- complete admissible set must be scored before bounded candidate exposure, or an equivalent recall guarantee must be proven;
- user_conflict can be exposed only through an explicit resolution path and only as the complete caller-owned conflict component;
- assistant conversation_history cannot enter user destructive authority;
- target IDs remain model-nonowned.

## Acceptance before any new paid call

Must pass the pre-frozen Lead gate:
- v5 OOD: **120/120**;
- fanout >24 default target recovery: **5/5**;
- conflict resolution prior nonempty / full component authorizable: **4/4**;
- overgroup merged: **0/16**;
- unrelated mutation: **0/16**.

And preserve v4 positives:
- public safe 16/16;
- unrelated singleton blocked 32/32;
- old v3 120/120;
- auditor holdout 64/64;
- forbidden target reject 80/80;
- hostile 19/19;
- determinism 1280/1280.

Provider calls during remediation: **0**.
Confirmatory users read: **0**.

Passing this gate is still not paid-execution authorization and does not establish HaluMem QA or E2 acceptance.
