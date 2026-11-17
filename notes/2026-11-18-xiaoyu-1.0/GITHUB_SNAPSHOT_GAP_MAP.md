# XiaoYu GitHub Snapshot Gap Map

**Date:** 2026-11-18  
**Source:** private GitHub repository `Su-long-ai/xiaoyu-identity`, main branch.  
**Important:** the GitHub snapshot is older than the disconnected local workspace. In particular, several local runtime modules discussed in the current project state are not present at the repository root. This document maps architecture only; it does **not** override fresher local authority.

---

# 1. What the GitHub snapshot already gets right

The current GitHub Core is not something that should be replaced.

## Identity authority

`identity_core.py` already has:

- provider-independent persona ID
- SQLite source of truth
- WAL mode
- event ledger
- persona versions
- human-confirmed growth
- export/import
- integrity verification

This already matches the final architecture principle:

> model/provider is replaceable; identity is not.

## Memory provenance

Existing structure:

```
conversation.user event
        ↓
memory proposal
        ↓
human review
        ↓
confirmed memory
```

A memory can only use canonical user evidence as source.

Bootstrap creator notes are separated from true shared memories.

This is a strong foundation and should remain.

## Memory lifecycle

The snapshot already supports:

- active
- archived
- superseded
- retracted

and already has:

- `correct_memory`
- `retract_memory`
- `archive_memory`

Corrections create a new canonical `memory.corrected` event and retire the old memory rather than rewriting history.

That is exactly the right event-sourced direction.

## Freshness

Pending memory proposals are not blindly accepted after newer evidence.

The snapshot already checks:

- explicit invalidation
- explicit reaffirmation
- newer accepted preference

and requires fresh confirmation for stale proposals.

## Monotonic memory generation

Schema v3 already contains `change_seq`.

This is valuable because derived indexes/surfaces can synchronize against a durable monotonic mutation sequence instead of relying on wall-clock timestamp uniqueness.

## Product retrieval authority

`ProductMemoryBridge` already contains a nontrivial authority layer:

- current identity memory must exist and be active
- corresponding product source must be active
- expected claim cardinality
- user role
- user-assertion authority
- active relation
- conflict edges reject ambiguous state
- recall linearization is protected by a transaction
- inconsistent transaction state fails closed

This is much stronger than a generic “vector similarity + prompt” memory layer.

## Export

The GitHub snapshot already uses SQLite's `Connection.backup()` to produce a consistent SQLite export snapshot.

Export includes:

- SQLite database
- portable JSON snapshot
- SHA-256 per file
- manifest
- identity id
- no provider configuration/API key

This means the long-term backup direction is already correct.

---

# 2. What should NOT be rewritten

Based on the snapshot and external survey, preserve:

```
IdentityStore
events ledger
memory_proposals
memories
persona_versions
change_seq
ProductMemoryBridge authority filtering
provider separation
export/import boundary
```

Do not replace these with:

- Mem0
- Letta
- Graphiti
- Hindsight
- DSH
- another vector DB
- a new “memory service”

External systems should only contribute ideas/projections/capabilities.

---

# 3. Main schema gaps

The current GitHub schema is intentionally small:

```
settings
events
memories
persona_versions
memory_proposals
```

The final product needs additional first-class state.

Recommended additions are **adjacent tables**, not a redesign of `memories`.

---

# 4. Temporal Fact Projection

## Gap

Current `memories` has:

- created_at
- updated_at
- category
- text
- source_event
- priority
- status
- change_seq

but does not explicitly represent:

- event time
- valid-from
- valid-to
- fact subject/predicate/value
- contradiction relation
- temporal scope

## Recommendation

Add a derived/authoritative fact layer:

```
temporal_facts
  fact_id
  subject
  predicate
  value_json
  source_event
  source_memory
  recorded_at
  event_time
  valid_from
  valid_to
  confidence
  trust_class
  status
  supersedes_fact_id
  change_seq
```

Do not delete or normalize away the original human-readable memory text.

The fact layer should remain traceable to the event ledger.

---

# 5. User Profile Projection

## Gap

Current categories such as `preference` exist, but there is no separate current-state user model.

## Recommendation

Add a rebuildable projection:

```
profile_items
  profile_key
  domain
  context
  value_json
  source_fact_ids
  confidence
  updated_at
  version
```

Sections:

- stable preferences
- contextual preferences
- habits
- important people
- active projects
- recurring routines
- interaction preferences
- proactivity preferences

Rule:

> profile is a projection, never the sole provenance authority.

If corrupted, it should be possible to rebuild from current facts/events.

---

# 6. Trust Class

## Gap

Current memory authority strongly protects owner-originated memory, but the final multimodal/social system needs a general source-trust model.

## Recommendation

Add explicit source trust:

```
OWNER_DIRECT
OWNER_CONFIRMED
LOCAL_TOOL_VERIFIED
LOCAL_OBSERVATION
EXTERNAL_WEB
THIRD_PARTY_MESSAGE
VISION_INFERENCE
MODEL_INFERENCE
AGENT_GENERATED
IMPORTED_UNVERIFIED
```

This can live on event/fact metadata before it is promoted to dedicated columns.

Critical rules:

- lower-trust content cannot rewrite identity
- lower-trust content cannot create standing permissions
- third-party content cannot silently become owner preference
- imported content cannot gain owner trust merely by being loaded

---

# 7. Audience Scope

## Gap

The current owner-centric product does not yet need audience boundaries, but QQ groups and multi-user devices will.

## Recommendation

Before group chat becomes a product feature, add:

```
audience_scope
  scope_id
  scope_type
  members / principal rules
```

Durable memory/facts should reference a scope.

Context assembly must filter before model input.

The correct principle is:

```
Authorization before Context
```

not “generate first, redact later.”

---

# 8. Purpose / Event State

## Gap

No first-class durable proactive state appears in the GitHub Core snapshot.

## Recommendation

Add:

```
purposes
  purpose_id
  source_event
  type
  title
  state
  due_start
  due_end
  confidence
  cancellation_rule
  supersedes
  created_at
  updated_at
  delivery_policy
  permission_requirement
```

States:

```
candidate
confirmed
scheduled
active
completed
cancelled
expired
superseded
```

Purpose is not memory.

Memory records “what happened.”

Purpose records “what is still pending.”

---

# 9. Delivery Ledger

## Gap

Final cross-surface presence requires one logical notification to be delivered once.

## Recommendation

Add:

```
deliveries
  delivery_id
  purpose_id
  logical_message_key
  preferred_surface
  actual_surface
  state
  sent_at
  seen_at
  acknowledged_at
  fallback_after
  external_receipt
```

This prevents Desktop + QQ + future phone from sending the same proactive notification independently.

---

# 10. Permission Grants

## Gap

The GitHub snapshot predates the final authorization architecture.

## Recommendation

Add deterministic policy state:

```
permission_grants
  grant_id
  principal
  action_class
  resource_scope
  audience
  max_amount
  valid_from
  valid_until
  reversibility
  source_event
  state
```

LLM output may request an action, but cannot synthesize a valid grant.

---

# 11. External Effect Ledger

## Gap

Tool success and persisted side effects need crash-safe reconciliation.

## Recommendation

Add:

```
effects
  effect_id
  intent_id
  idempotency_key
  tool
  target
  state
  requested_at
  dispatched_at
  external_receipt
  verified_at
  postcondition
```

Recovery states should include:

- pending
- dispatched_unknown
- externally_confirmed
- verified
- failed
- reconciliation_required

This is the basis for safe retries.

---

# 12. SkillBank

## Gap

Current memory describes user/history, not reusable procedures.

## Recommendation

Do not overload `memories`.

Add a separate skill model:

```
skills
skill_versions
skill_evidence
skill_verifications
```

A skill version needs:

- trigger
- preconditions
- steps
- branches
- contraindications
- permissions
- postcondition
- provenance
- verified providers/models
- success statistics

Admission must be replay-gated.

---

# 13. Relationship State

## Gap

The persona has `bond_description` and simulated numeric `bond`, but that is not yet a provenance-based relationship model.

## Recommendation

Do not turn `bond` into a pseudo-scientific emotional score.

Instead, later create a small relationship projection based on evidence:

- familiarity
- established interaction norms
- shared-project continuity
- preferred support style
- permission history

Keep any affect/bond meter as presentation/game state, not factual authority.

---

# 14. Presentation Affect

## Gap

Current state has `mood/hunger/energy/bond`.

These are useful for pet presentation but should not be confused with psychological truth.

## Recommendation

Rename/separate conceptually:

```
presentation_state
```

Use it for:

- animation
- expression
- tone
- idle behavior

It must not override identity, memory, permissions or user facts.

---

# 15. Memory Categories

## Current snapshot

The core still uses broad categories:

- shared
- preference
- relationship
- legacy/bootstrap

## Recommendation

Do not explode the `memories.category` enum immediately.

Keep memory text broad and move structure into fact/profile projections.

This avoids schema churn and preserves backward compatibility.

---

# 16. Correction path is already the seed of bi-temporal memory

Current `correct_memory()` already:

1. writes a correction event
2. records `supersedes_memory_id`
3. marks old memory superseded
4. creates a new active memory

So bi-temporal evolution should extend this path, not bypass it.

Future correction should additionally:

- close old fact `valid_to`
- create new fact `valid_from`
- preserve `recorded_at`
- update profile projection

This gives a natural migration path.

---

# 17. Recent-history projection is already safety-aware

The GitHub `model_adapter.py` snapshot contains `project_history()` logic that annotates or suppresses old user utterances when associated long-term facts were:

- superseded
- retracted
- archived
- physically deleted

This is a strong idea that should survive refactors.

It solves an important failure mode:

> stale raw conversation history reintroducing a fact that the memory layer already corrected.

Future temporal/audience handling should extend this projector rather than create a parallel history pipeline.

---

# 18. Current GitHub Provider Snapshot Is Stale

The GitHub `model_adapter.py` still contains `deepseek_web`.

The fresher local state, measured before local connectivity was lost, removed this path and uses API-only DeepSeek with Qwen fallback.

Therefore:

- do not “fix” the GitHub snapshot based on this gap document alone;
- when local connection returns, local code remains fresher authority;
- later synchronize the intended API-only runtime to GitHub through the normal project flow.

This is an explicit example of why this document is a structural map, not current-code authority.

---

# 19. Runtime Modules Missing From GitHub Snapshot

Files that were known to exist locally but not found at the private-repo root during this review include:

- `turn_runtime.py`
- `desktop_runtime_bridge.py`
- `tool_runtime.py`
- `qq_surface.py`
- newer desktop/runtime tests

Therefore no conclusion should be drawn that XiaoYu lacks:

- unified turn
- desktop bridge
- tool runtime
- QQ transport

Those capabilities were already validated locally before the connection was lost.

---

# 20. Recommended Migration Strategy

Do not create one giant schema migration.

Use incremental slices.

## Slice A — Temporal basics

Add:

- source trust metadata
- temporal fact table
- correction projection

Tests:

- old/current fact
- backdated fact
- correction
- retraction
- rebuild projection

## Slice B — Profile

Add:

- profile projection
- context/domain field
- rebuild command

Tests:

- work vs personal preference
- changed preference
- profile corruption/rebuild

## Slice C — Purpose

Add:

- purpose table
- cancellation
- completion
- due window

Tests:

- create
- reschedule
- cancel
- duplicate
- restart

## Slice D — Permissions/effects

Add:

- grants
- effect ledger
- receipts
- verifier

Tests:

- ALLOW/ASK/DENY
- crash boundaries
- duplicate prevention

## Slice E — Audience

Add:

- scopes
- viewer filtering

Only needed before group/multi-user surfaces.

## Slice F — Skills

Add after 1.0 stabilization.

---

# 21. Backward compatibility rule

Existing event/memory rows must retain original meaning.

Migration may add:

- projections
- metadata
- indexes
- relations

but must not retroactively infer unsupported facts.

If old data lacks a field:

```
unknown
```

is better than fabricated precision.

---

# 22. Rebuildability rule

Prefer:

```
events/memory authority
    ↓
derived projections
```

for:

- profile
- temporal current state
- search index
- embeddings
- summaries

The more derived state can be rebuilt, the easier:

- provider change
- model change
- embedding change
- bug repair
- migration
- deletion propagation

becomes.

---

# 23. Existing Tests Already Point in the Right Direction

GitHub tests already cover:

- bootstrap not counted as shared memory
- literal proposal provenance
- rejection not becoming memory
- fabricated growth evidence rejected
- provider switch preserving identity
- export/import identity continuity
- stale pending preference reconfirmation
- corrections/retractions reflected in projected history
- fail-closed history projection

These should become the base layer of the future acceptance matrix, not be replaced.

---

# 24. New Test Families To Add Later

## Temporal

- valid_from / valid_to
- historical belief vs current truth
- delayed/backdated correction

## Profile

- context boundary
- preference evolution
- behavioral realization

## Purpose

- cancellation
- completion
- exact time
- silent/wait

## Audience

- owner private vs group
- third-party source

## Effects

- crash/restart
- unknown dispatch
- duplicate prevention

## Skill

- baseline vs skill
- provider switch
- stale procedure

---

# 25. Global conclusion

The GitHub snapshot confirms the main external-research conclusion:

> XiaoYu does not need a new memory framework. It needs several new state types around an already sound event/provenance core.

The lowest-risk evolution is:

```
existing events + memories + persona
              ↓
      temporal/profile projections
              ↓
       purpose / permissions
              ↓
        effects / deliveries
              ↓
            skills
```

This preserves the project's strongest existing property:

**every durable claim remains traceable to evidence.**
