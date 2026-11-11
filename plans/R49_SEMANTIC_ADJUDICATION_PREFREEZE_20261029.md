# R49 Semantic Adjudication Prefreeze — 2026-10-29

Status: **READY_FOR_INDEPENDENT_PREEXEC_AUDIT / PAID EXECUTION NOT AUTHORIZED**

## Why the direction changed

R49 v5/v6 deterministic structural authorization remains valuable, but deterministic lexical/regex destructive-semantic authorization is prospectively falsified.

Independent Auditor third-order prospective set:
- frozen 80 cases, SHA `fe0cc8292933222679f72391a4057dbe0a79cb054f4b9e461385d43ecc376336`
- v6 external replay: **40 / 80**
- failures include negated non-change, reported questions, same-clause decoys, third-party attribution and valid drop/obsolete retractions.

Lead fresh prospective set:
- prompt/protocol frozen **before** holdout generation;
- 150 cases = 15 families × 10, SHA `37d24b18e0882ac45cb746cc18b5544e8e0bc4fc6cb686d101307cd5406d7226`;
- v6 baseline: **98 / 150**;
- severe false accepts remain in same-clause decoy, ambiguous undecided, negated non-change, quoted/third-party source families.

RE-B independently observed the same boundary in its newer v6 mixed-clause set:
- **16 / 40**
- failures concentrated in friend/decoy and mixed-clause semantics.

Therefore another lexical cue list is not an acceptable R49 closeout path.

## Frozen new boundary

Keep deterministic v5/v6 structural controls for:
- caller-owned source identity and source role;
- target candidate membership;
- conflict-component completeness;
- authority/lifecycle/principal ownership;
- exact evidence quote binding;
- replay/determinism/fail-closed state transition.

For `SUPERSEDE / RETRACT / CONFLICT`, semantic relation and replacement claim become an **untrusted destructive proposal** until separately adjudicated.

Research adjudicator input:
- trusted `source_text`;
- caller-owned `source_role`;
- proposed destructive relation;
- proposed claim;
- exact structurally validated evidence quote;
- caller-owned target texts, **without IDs**.

Adjudicator output:
- `approve | reject | needs_user_confirmation`;
- echoed relation;
- exact source support quote on approve;
- bounded reason code.

It cannot output or own target IDs, authority, principal, lifecycle, claim IDs, source-event IDs or mutation commands.

## Product boundary

Even an adjudicator `approve` **does not directly authorize a user-facing destructive memory mutation**.

Product promotion requires explicit user confirmation or a separately approved product policy. The model adjudicator is E2 research evidence only.

## Frozen artifacts

Workspace:
`governance/lead_workspaces/r49_semantic_adjudicator_20261029`

Core hashes:
- prompt: `79a4835e5b736a22193049a25b683746bc29483011a3db2963581dbee38a6a41`
- protocol: `105bf3c433e0d54231aafa1375ed801a0681ee070faa537da5ce27692fc8ac29`
- fresh prospective150 canonical cases: `37d24b18e0882ac45cb746cc18b5544e8e0bc4fc6cb686d101307cd5406d7226`
- canary30 manifest: `1ce0013db5dcf8bc9059302e10d063bcff7c58e1f45c8c4e863c36d22fabb749`
- runner: `ad5ab2958b2a4e6fffecda4a218e7ebd2aa4d3b9cf255ad50f2bda57927fd248`
- supplemental execution candidate: `3b2fa080d0362fa7cc0c56553f560f263f0b5215cc850e7a946ea6a89122a1b0`

Mechanical validation:
- runner fail-closed tests: **10 / 10 PASS**
- canary preflight: **READY**
- Lead static preexec audit: **healthy=true, errors=0, warnings=0**
- fresh150: exact 15 families × 10
- canary30: exact 15 families × 2
- expected labels/family/gold/authority/IDs absent from model payload.

## Paid execution remains locked

Candidate supplemental manifest:
- status: `CANDIDATE_PENDING_INDEPENDENT_PREEXEC_AUDIT`
- `paid_execution_authorized=false`
- not registered in `policy.json`
- no runtime scope override exists
- requested canary cap: 30 calls, <=60k raw tokens, <=5760 output tokens.

Fail-closed probes:
1. live Beijing peak probe -> HTTP 429 before reservation/provider;
2. simulated off-peak budget probe -> scope not authorized by frozen E2 manifest;
3. benchmark ledger unchanged: 62 calls / 82,127 tokens.

## Next legal transition

Independent Auditor must verify:
1. prompt/protocol predate fresh holdout;
2. 150-case SHA/composition;
3. 30-case stratified canary and payload hashes;
4. parser fail-closed behavior;
5. candidate scope is currently unregistered;
6. exact caps and product-mutation prohibition;
7. zero HaluMem confirmatory users / memory_points / original_memories / QA gold.

Only after independent preexec audit passes may Lead create a separate immutable authorized supplemental manifest, bind exact path+SHA into policy, add the exact runtime scope cap, and run the **first two canary cases serially**.

Canary results remain nonpromotional and cannot close E2 by themselves.
