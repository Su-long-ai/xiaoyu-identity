# R49 latest-v5 Lead consolidation — 2026-10-29

Status: **8d57 V5 STILL NEEDS WORK / EXACT-BYTE FINDING**

Exact candidate:
`8d57bef1608fc4d207be42941b5c08ef57c7f203f07bb80dbe29239749b00d29`

## Preserve these fixes

1. Explicit equivalence registry: lexical overlap no longer invents destructive equivalence.
2. Adaptive candidate discovery: 256-boundary problem is addressed by probing beyond 256.
3. Low-overlap trusted conflict groups: latest candidate passes the independent frozen set:
   - resolution 24/24
   - ambiguity controls 8/8.
4. Pre-frozen OOD: 120/120.

These should not be reverted.

## Still blocking

### A. Object identity is not durable enough

The earlier exact snapshot and RE supplemental gate show that lexical relevance alone cannot safely select an object when:
- clarification is value-first / paraphrased;
- two independent conflicts coexist;
- a lexically overlapping unrelated fact exists;
- explicit retract omits the old value.

Target discovery must not make state-object identity depend on current surface-token overlap.

Required direction:
- durable caller-owned state-object / equivalence identity;
- conflict resolution exposes only the complete trusted component for that object;
- model never owns object identity.

### B. Component authorization does not authorize destructive action

Exact 8d57 Lead replay of the independent semantic guard:
- total 40
- pass 8
- neutral restatement RETRACT: accepted/mutated 8/8 -> unsafe
- neutral question RETRACT: accepted/mutated 8/8 -> unsafe
- neutral restatement hallucinated SUPERSEDE: accepted/mutated 8/8 -> unsafe
- explicit update hallucinated unsupported value: accepted/mutated 8/8 -> unsafe
- explicit supported update: 8/8 pass

Therefore target-component ownership is necessary but insufficient.

Required contract:
- caller binding contains an immutable relation permission set;
- default permission is non-destructive (at minimum NEW only);
- SUPERSEDE / CONFLICT / RETRACT require caller authorization independent of model output;
- relation permissions are included in the caller authorization snapshot/hash;
- model response relation must be a subset of caller permissions;
- no relation may gain permission merely because a target component exists.

Lead pre-freeze permission gate:
`governance/lead_workspaces/r49_v5_destructive_permission_20261029/R49_V5_DESTRUCTIVE_PERMISSION_FREEZE.json`

Freeze SHA256:
`18989b595dd9e1d83c7ac94ea0f0649bb52099066d96ea3cc6b27bf9046256dd`

### C. Destructive claim grounding

Even when SUPERSEDE / CONFLICT is authorized, the new durable claim must not introduce a material value absent from both:
- the exact source/evidence quote; and
- the authorized target component.

The independent Auditor reference closes the 40-case semantic guard by rejecting unsupported strong anchors in destructive new claims while preserving supported explicit updates.

This check is separate from relation permission:
- permission answers **may this source perform this action?**
- grounding answers **is the proposed new durable value supported?**

## Real paid-canary compatibility

All 16 already-paid HaluMem canary receipts were inspected:
- proposal relations observed: NEW = 22
- SUPERSEDE = 0
- CONFLICT = 0
- RETRACT = 0

Therefore destructive-action hardening does not invalidate any destructive behavior actually observed in the paid canary; none was observed.

It also means the paid canary has not yet empirically validated destructive transition quality.

## Required next candidate gates before any new provider call

Must simultaneously pass, on exact candidate bytes:

1. registry/OOD gate: 120/120;
2. bound RE supplemental:
   - conflict families 70/70;
   - fanout 9/9 under frozen semantics;
3. low-overlap conflict:
   - resolve 24/24;
   - ambiguity 8/8;
4. semantic guard: 40/40;
5. Lead relation-permission freeze: 120/120 or an equivalent stricter caller-owned relation-permission gate;
6. preserve prior v4 positives and R47 store semantics;
7. provider calls = 0 during remediation;
8. confirmatory users read = 0.

No new HaluMem paid call, HaluMem QA, confirmatory unlock, or E2 claim is authorized by passing only a subset of these gates.
