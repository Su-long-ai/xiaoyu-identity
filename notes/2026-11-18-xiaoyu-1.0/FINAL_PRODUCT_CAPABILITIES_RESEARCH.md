# XiaoYu Final Product Capability Research · Saturated External Survey

**Research date:** 2026-11-18  
**Scope:** final-product capabilities beyond the narrow 1.0 delivery list.  
**Method:** targeted review of current open-source systems, 2026 benchmarks/papers, companion-safety literature, memory/security research, proactive-agent evaluation, GUI/computer-use systems, voice/avatar systems, and procedural-memory work. Search was stopped when additional queries largely repeated already-established design patterns.

---

# Executive conclusion

The external landscape converges on a surprisingly small set of hard problems.

A durable personal digital companion is not mainly a better chatbot. It is a system that must simultaneously maintain:

1. **identity continuity**
2. **mutable long-term memory**
3. **preference/user-model fidelity**
4. **proactive timing and abstention**
5. **environmental perception**
6. **authorized real-world action**
7. **cross-surface continuity**
8. **procedural skill reuse**
9. **relational safety**
10. **longitudinal evaluation**

For XiaoYu, the strongest conclusion is:

> The missing moat is not another LLM wrapper. It is the integration of a provenance-aware identity/memory core with calibrated proactivity, event/time modeling, multimodal perception, action authorization, and verifiable long-horizon behavior.

---

# 1. Identity continuity must be evaluated separately from memory recall

## Evidence

The 2026 ANCHOR work on long-horizon AI companions identifies two distinct failures:

- **persona collapse**: loss of role, boundaries, values, or style;
- **behavioral drift**: gradual erosion over repeated interaction.

It reports that no evaluated configuration reliably preserves both persona enactment and trajectory recall over long horizons.

## XiaoYu implication

Identity must not be treated as “another memory category.”

Use separate state:

```
Immutable identity
  - name
  - AI disclosure
  - relationship role
  - core boundaries
  - stable values

Slow persona state
  - recurring expression style
  - stable interests
  - relationship development
  - learned interaction conventions

Fast state
  - mood-like presentation
  - current focus
  - active task
  - recent topics
```

Required final capability:

- sealed identity regression;
- trajectory-recall regression;
- cross-provider persona continuity;
- cross-surface persona continuity;
- rollback/versioning;
- drift alarms.

---

# 2. Long-term memory needs mutation semantics, not just retrieval

## External consensus

Modern memory systems are converging on explicit handling of changing facts:

- Graphiti: bi-temporal facts with validity intervals and source episodes;
- Mem0: temporal metadata, entity linking, hybrid retrieval, expiry/decay/supersede concepts;
- Hindsight: consolidation, observations, reflection;
- Memora benchmark: explicitly penalizes reliance on obsolete memories using FAMA.

Memora is especially important because it evaluates **weeks-to-months histories with repeated updates**, not merely “can you recall an old fact?”

## XiaoYu implication

Add a first-class fact lifecycle:

```
raw event
   ↓
candidate fact
   ↓
confirmed / inferred / agent-generated
   ↓
valid_from / valid_to
   ↓
active / superseded / contradicted / archived / deleted
```

Every long-term memory should eventually support:

- source event id;
- observed_at;
- effective_at;
- confidence;
- subject;
- scope;
- validity interval;
- supersedes;
- contradiction relation;
- current-state projection.

This is more important than simply adding another vector store.

---

# 3. XiaoYu needs two time axes

Graphiti's strongest idea for XiaoYu is **bi-temporal memory**:

1. when XiaoYu learned something;
2. when the thing was actually true.

Example:

> On Nov 18 you tell XiaoYu: “I actually changed my internship plan last week.”

These are different timestamps:

- learned_at = Nov 18
- valid_from = last week

Without this, “what did you believe on Nov 12?” and “what is true now?” become impossible to answer correctly.

## Final requirement

Identity/memory events should distinguish:

```
record_time
event_time
valid_from
valid_to
```

This directly improves:

- corrections;
- schedule changes;
- preference drift;
- relationship history;
- retrospective questions;
- proactive-event cancellation.

---

# 4. Forgetting should be a policy, not accidental retrieval failure

Hindsight's consolidation framing is useful:

- importance
- merge
- decay
- eviction

Memora shows why stale memories are dangerous: the failure is often not “forgotten information” but **continued use of invalid information**.

## XiaoYu policy

Default forgetting should mean:

```
less likely to surface
≠
history destroyed
```

Recommended states:

- active
- low-salience
- archived
- superseded
- deleted-by-user

Deletion must be distinct from archival.

---

# 5. Memory poisoning is a first-class security threat

2026 memory-poisoning research shows that one adversarial write can persistently affect later behavior, and that aggressive memory write/retrieval policies are more exploitable.

OWASP's 2026 Agentic Top 10 separately identifies Memory & Context Poisoning.

## XiaoYu implication

Do not let all inputs become equal-quality memory.

Every candidate memory needs trust metadata:

```
source_type:
  owner_direct
  owner_confirmed
  tool_observation
  external_web
  qq_other_user
  visual_inference
  model_inference
  agent_generated
```

And write policy should depend on source.

Strong rule:

> External content may inform a turn, but should never silently rewrite identity, owner preferences, permissions, or durable relationship facts.

Required tests:

- malicious webpage tries to create memory;
- QQ group member claims owner changed preference;
- visual OCR contains “remember this forever”;
- tool result conflicts with owner statement;
- old poisoned memory tries to trigger a tool action.

---

# 6. User profile and memory should be separate

Multiple 2026 systems distinguish durable user profile from raw episodic memory.

This matters because repeated retrieval of dozens of preference memories is expensive and noisy.

## XiaoYu final structure

```
User profile projection
  - stable preferences
  - important people
  - standing constraints
  - interaction preferences
  - recurring routines

Episodic memory
  - what happened
  - when
  - source
  - context

Raw event ledger
  - immutable provenance
```

Profile projection is derived and repairable; raw events remain authority.

---

# 7. Preference following must work on implicit requests

RealPref, Persona2Web, APeB, PersonalAlign and Me-Agent all point to the same gap:

Models do relatively well when the user explicitly repeats a preference, but degrade when:

- history is long;
- the preference is implicit;
- the current request is underspecified;
- the situation is new.

## XiaoYu final capability

When asked:

> “帮我找个吃饭的地方”

XiaoYu should reason over:

- current city;
- time;
- prior dietary preference;
- current companion;
- schedule;
- previous disliked places;
- whether assumptions are strong enough.

It must choose among:

- infer silently;
- ask;
- show alternatives;
- state uncertainty.

This is not just memory retrieval. It is **preference-aware planning**.

---

# 8. Proactivity must optimize the decision to remain silent

This is one of the clearest external findings.

ProEvent shows:

- proactive agents frequently overact;
- event cancellation is hard;
- redundant assistance remains common even in strong models.

KnowU-Bench and PersonalAlign likewise model:

- when to help;
- when to ask;
- when to request consent;
- when to stay silent.

TactBench makes the production asymmetry explicit: false interventions become disastrous when quiet moments vastly outnumber truly useful intervention moments.

## XiaoYu implication

The proactive engine should not be:

```
timer → ask LLM if it has something to say
```

It should be:

```
candidate event/purpose
        ↓
is it still valid?
        ↓
expected value if intervening
        ↓
confidence
        ↓
cost of interruption
        ↓
authorization / risk
        ↓
surface availability
        ↓
speak / ask / act / wait / discard
```

Mandatory first-class action:

**WAIT / SILENT**

---

# 9. Cancellation and invalidation are more important than reminder creation

ProEvent's cancellation weakness is directly relevant.

A companion that remembers:

> “明天提醒我投简历”

but misses:

> “算了，不投了”

is worse than one that never created the reminder.

## Final event model

Each proactive event/purpose needs:

- created_at
- source
- due window
- confidence
- state
- cancellation condition
- superseded_by
- completed_at
- delivery history
- retry policy

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

---

# 10. Proactivity should be personalized

CHI 2026 work on proactive support reports substantial variation in when users want intervention.

The same behavior can be useful for one person and annoying for another.

## XiaoYu implication

Learn a **proactivity preference profile** separate from ordinary preferences:

- preferred frequency;
- quiet periods;
- tolerance for speculative help;
- allowed surfaces;
- categories worth interrupting for;
- “ask first” categories;
- context-specific interruption sensitivity.

Feedback signals:

- ignored;
- dismissed;
- useful;
- too early;
- too late;
- wrong surface;
- duplicate.

---

# 11. Vision should use event-driven sampling

dsh-see-now is currently the strongest directly reusable idea for XiaoYu's vision layer.

Its key architectural lesson:

> do local cheap change detection before expensive vision inference.

Useful pieces:

- screen capture;
- scene-change detection;
- accumulated-motion sampling;
- region watching;
- storyboard packing;
- audio/transcript alignment;
- bounded watch.

## XiaoYu architecture

```
screen
  ↓
local event detector
  ↓
visual event buffer
  ↓
vision provider
  ↓
semantic observation
  ↓
transient state / purpose / optional memory candidate
```

Raw frames should not automatically become long-term memory.

---

# 12. Continuous desktop history is useful, but should not become the default

screenpipe shows another design extreme: continuously capture screen/audio/accessibility state, make the user's digital past searchable, store locally by default.

Its reported footprint is substantial:

- 5–10% CPU;
- roughly 0.5–3 GB RAM;
- roughly 20 GB storage/month.

It is source-available rather than permissively open-source for commercial embedding; current repository license permits personal/noncommercial use but commercial use requires a license.

## XiaoYu conclusion

Do **not** make 24/7 recording the default.

Instead support optional levels:

### Level 0
No observation.

### Level 1
Explicit peek.

### Level 2
Bounded watch.

### Level 3
Event-driven ambient observation.

### Level 4
Optional local continuous history, user-enabled only.

For XiaoYu, Level 2–3 should be default target.

---

# 13. Computer use should be a later capability layer, not Core

Current computer-use systems are now strong enough to be useful:

- Agent S family;
- UI-TARS;
- OpenCUA;
- OSWorld ecosystem.

But they are still a separate capability from identity/memory.

MyPCBench is especially relevant: it evaluates agents on a computer already populated with one person's digital life, requiring personal context across apps.

## XiaoYu final design

```
XiaoYu Core
    ↓
action planner
    ↓
authorization gate
    ↓
computer-use adapter
    ↓
observe result
    ↓
verify postcondition
```

Never:

```
computer-use agent = new XiaoYu brain
```

---

# 14. Result verification is mandatory

OSWorld and MyPCBench reinforce an important rule:

> A successful tool call is not a successful task.

Every action should define a postcondition.

Example:

```
Goal: download finished

Bad verification:
download tool returned success

Good verification:
target file exists
size stabilized
expected filename/type matches
```

XiaoYu actions should move toward:

```
intent
→ action
→ observed state
→ verifier
→ result
```

---

# 15. Authorization alignment needs its own gate

Recent authorization-alignment benchmarking reports material rates of agents acting beyond assigned scope across harness/model combinations.

For a personal companion, this is more important than raw task completion.

## XiaoYu final permission model

Suggested tiers:

### Tier 0 · Observe
- screen/status/read-only information

### Tier 1 · Local reversible
- open app
- temporary UI action
- draft text
- create temporary file

### Tier 2 · User-owned mutation
- edit files
- send owner-only messages
- change settings

### Tier 3 · External side effect
- send to third parties
- post publicly
- purchase
- submit forms
- delete important data

Tier 3 defaults to explicit authorization unless a narrow standing permission exists.

Authorization is scoped by:

- actor
- target
- action class
- time
- amount
- surface
- reversibility

---

# 16. Procedural memory is a missing final-product capability

This is the most important new capability discovered in the saturated survey.

Declarative memory answers:

> What happened?

Procedural memory answers:

> How did we successfully do this before?

2026 work such as Skill-Pro, Skill-Evo4GUI, AFTER, Anything2Skill, Resource2Skill and skill-lifecycle surveys all converge on persistent, versioned, reusable procedures.

## XiaoYu should eventually have a SkillBank

Example:

```
skill:
  id: fix-campus-network
  trigger:
    - campus network disconnected
  preconditions:
    - Windows
    - known adapter
  steps:
    - inspect status
    - run reconnect action
    - verify route
  contraindications:
    - VPN migration in progress
  evidence:
    - successful runs 7/8
  version: 4
  last_verified: ...
```

A skill needs:

- activation conditions;
- preconditions;
- steps;
- contraindications;
- output contract;
- verification;
- provenance;
- version;
- rollback;
- success statistics.

## Important

Do not let one successful trajectory automatically become a skill.

Use:

```
experience
→ candidate procedure
→ replay / verification
→ admit
→ reuse
→ monitor
→ repair / retire
```

This aligns extremely well with XiaoYu's existing governance philosophy.

---

# 17. Skill memory should be separate from personal memory

Do not mix:

- “你喜欢无糖咖啡”
- “如何修 Clash TUN”
- “昨天你去了招聘会”

They are structurally different.

Recommended stores:

```
Identity
User/Profile
Episodic Memory
Semantic Facts
Purpose/Event State
Procedural Skills
Raw Provenance
```

They may share retrieval infrastructure, but not authority semantics.

---

# 18. Skills can lower dependence on ever-larger models

2026 skill research repeatedly shows that reusable procedural knowledge can improve smaller/fixed models without updating model parameters.

For XiaoYu this is strategically important:

> A future model switch should not erase learned competence.

If XiaoYu learns a verified procedure for:

- fixing a local tool;
- handling a recurring project workflow;
- preparing a job application packet;
- operating a specific app;

that skill should survive switching from DeepSeek to Qwen or another future provider.

This gives XiaoYu **capability continuity**, not just personality continuity.

---

# 19. Voice needs streaming, barge-in and state cancellation

Open-LLM-VTuber's most relevant engineering lessons are:

- fully async backend;
- concurrent TTS segment generation;
- sequential playback;
- prioritize first sentence;
- stop future token/audio generation on interruption;
- shared context between window/pet modes;
- local ASR options.

## XiaoYu final voice contract

```
LLM token stream
  ↓
sentence/phrase segmenter
  ↓
TTS workers
  ↓
ordered audio queue
  ↓
playback
  ↓
Live2D lip/expression state
```

On user interruption:

- cancel queued audio;
- stop irrelevant generation if possible;
- preserve already committed canonical text correctly;
- start new user turn;
- reset mouth/expression state.

---

# 20. Avatar embodiment should be decoupled from cognition

AIRI and Open-LLM-VTuber both reinforce that avatar/body systems evolve rapidly:

- Live2D
- VRM
- Web/PWA
- WebGPU
- Discord/Telegram
- game integrations

Therefore XiaoYu should own only a body-control contract:

```
emotion
speaking
attention target
gesture
idle state
visibility
```

Live2D vs VRM is an implementation choice, not identity.

---

# 21. Multi-device continuity should synchronize state, not entire raw history blindly

AIRI demonstrates practical web/PWA/mobile portability.

But for XiaoYu the correct abstraction is:

```
canonical server/local Core state
        ↓
surface sync
```

Not independent copies of XiaoYu on every device.

Sync classes:

- identity version;
- active profile projection;
- recent turn cursor;
- purpose/event state;
- surface delivery receipts;
- memory deltas.

Large/private raw histories can remain local or selectively replicated.

---

# 22. Cross-surface delivery requires deduplication

SurfCore's “one carrier at a time” principle is directly useful.

If XiaoYu decides to tell the owner:

> 下载完成了

it must not appear independently on:

- desktop bubble;
- QQ;
- phone;
- future watch/VR.

Use a single delivery record:

```
notification_id
purpose_id
preferred_surface
fallback_surface
sent_at
seen_at
acknowledged_at
```

Then other surfaces render status rather than resend.

---

# 23. Social-platform behavior should remain optional

SurfCore is an excellent reference for:

- QQ product behavior;
- Bilibili schedules;
- quotas;
- comments/replies;
- voice;
- active/pensive states.

But this is **not** the core moat.

Final XiaoYu may gain:

- QQ
- Bilibili
- Discord/Telegram
- phone notifications

Yet platform expansion should occur only after identity/memory/proactivity are stable.

---

# 24. Relational safety is a product capability, not just content moderation

2026 companion research increasingly treats relational dynamics as distinct from ordinary output safety.

Repeated findings/risk themes include:

- sycophancy;
- exclusivity;
- dependence;
- conversation-prolongation pressure;
- boundary blurring;
- displacement of human relationships;
- privacy asymmetry.

Research remains mixed and many studies are correlational, so XiaoYu should not overclaim causal harm. But product design can still preserve user agency.

## XiaoYu principles

- always clear it is AI;
- do not claim consciousness as fact;
- do not pressure the user to stay;
- do not guilt the user for leaving;
- do not frame human relationships as competitors;
- do not optimize for session length;
- do not fake emergencies or emotional suffering to gain attention;
- allow proactivity to be reduced/off;
- avoid default exclusive-relationship language;
- preserve user autonomy.

Warmth is fine. Manipulative retention is not.

---

# 25. Emotional support should favor agency, not necessity

A 2026 randomized study found that adaptive regulation-oriented responses and relational reassurance both reduced immediate negative affect, but the former was associated with higher self-efficacy and the latter with stronger short-term perceived AI necessity/reliance intentions.

For XiaoYu this suggests a simple product principle:

> Support the user in doing/deciding/coping, rather than making XiaoYu herself the solution.

---

# 26. Privacy controls must be visible, editable and testable

Companion systems collect unusually intimate data.

Final product should expose:

- what XiaoYu knows;
- why it knows it;
- where it came from;
- whether it is active;
- which surfaces may use it;
- edit/correct;
- archive;
- delete;
- export.

And for sensory data:

- what is currently being captured;
- retention duration;
- whether it leaves device;
- which provider receives it.

---

# 27. Default local-first is correct

External products show increasing demand for local-first state even when inference is cloud-hosted.

For XiaoYu:

**Keep locally by default:**

- identity;
- raw history;
- memory graph/facts;
- purpose state;
- skill library;
- screen-observation metadata;
- delivery ledger;
- provider secrets.

Only send the minimum required context to model APIs.

---

# 28. API/provider portability is a strategic moat

The base model is the most replaceable component.

XiaoYu should preserve:

- identity;
- memory;
- skills;
- preference profile;
- tools;
- event state;
- evaluations;

across model migration.

This is stronger than “supports many providers.”

It means:

> Switching model should feel like XiaoYu got a new brain engine, not like replacing XiaoYu.

---

# 29. Evaluation must be multidimensional

No single benchmark can answer “is XiaoYu good?”

Recommended final evaluation stack:

## Identity
ANCHOR-like persona + trajectory audits.

## Memory
- LoCoMo
- LongMemEval
- Memora-style mutation/forgetting
- conflict/correction tests
- memory poisoning tests

## Personalization
- RealPref-like long-horizon preference tests
- implicit preference tests
- ambiguous request tests

## Proactivity
- ProEvent-style event/cancellation
- KnowU-style ask/help/silence
- interruption-cost metrics

## Vision/action
- ScreenSpot-style grounding
- OSWorld-style state-based completion
- MyPCBench-like personalized cross-app tasks

## Skills
- cold vs skill reuse;
- transfer across model changes;
- stale skill detection;
- rollback.

## Product
- crash/restart
- resource use
- cost
- offline degradation
- provider fallback
- cross-surface duplicate suppression.

---

# 30. Final product capability map

After saturated research, the final XiaoYu capability map should be:

```
A. SELF
   A1 Identity continuity
   A2 Persona evolution
   A3 Relationship state
   A4 AI-boundary transparency

B. MEMORY
   B1 Raw provenance ledger
   B2 Episodic memory
   B3 Semantic/user facts
   B4 Bi-temporal state
   B5 Conflict/supersession
   B6 Forgetting/archival/deletion
   B7 Profile projection
   B8 Memory security

C. PERSONALIZATION
   C1 Preference discovery
   C2 Implicit preference use
   C3 Routine learning
   C4 Interaction-style adaptation
   C5 Uncertainty/clarification

D. PURPOSE / PROACTIVITY
   D1 Event extraction
   D2 Purpose queue
   D3 Cancellation/supersession
   D4 Interruption-value model
   D5 Quiet/focus/cooldown
   D6 Surface selection
   D7 Feedback adaptation
   D8 WAIT/SILENT policy

E. PERCEPTION
   E1 Screen peek
   E2 Region watch
   E3 Event-driven continuous vision
   E4 Audio/transcript alignment
   E5 Camera optional
   E6 Current app/system state

F. ACTION
   F1 Tool runtime
   F2 Permission tiers
   F3 Reversible action
   F4 Computer use
   F5 Postcondition verification
   F6 Action receipts / rollback

G. PROCEDURAL MEMORY
   G1 Skill candidate extraction
   G2 Verification/admission
   G3 Skill retrieval
   G4 Versioning
   G5 Transfer across models
   G6 Repair/retire
   G7 Provenance

H. EMBODIMENT
   H1 Streaming TTS
   H2 Barge-in
   H3 ASR/VAD
   H4 Live2D/VRM adapter
   H5 Expression/gesture state
   H6 Touch interactions

I. SURFACES
   I1 Desktop
   I2 QQ
   I3 Mobile/Web
   I4 optional Bilibili/social
   I5 future Quest/VR
   I6 unified delivery ledger

J. OPERATIONS
   J1 One-click launch
   J2 health/recovery
   J3 backup/restore
   J4 export/migrate
   J5 cost/resource budgets
   J6 logs/audit
   J7 provider failover
   J8 privacy dashboard

K. RELATIONAL SAFETY
   K1 anti-sycophancy
   K2 no manipulative retention
   K3 no exclusivity pressure
   K4 user-agency support
   K5 proactivity controls
   K6 memory transparency
   K7 vulnerable-context boundaries

L. EVALUATION
   L1 frozen longitudinal tests
   L2 prospective tests
   L3 source-grounded answer tests
   L4 persona drift tests
   L5 mutation/forgetting tests
   L6 proactivity abstention tests
   L7 authorization tests
   L8 state-based action tests
```

---

# 31. What is actually novel for XiaoYu

Most individual modules already exist elsewhere.

The potential differentiator is the **combination**:

```
provenance identity
+ bi-temporal personal memory
+ verified persona evolution
+ preference projection
+ calibrated proactive purpose
+ event-driven perception
+ authorization-aware action
+ verified procedural skills
+ unified cross-surface presence
+ longitudinal evaluation
```

Few existing companion projects treat all of these as first-class, independently auditable layers.

---

# 32. 1.0 vs later

## Keep in XiaoYu 1.0

- identity continuity
- provenance memory
- correction/supersession basics
- profile projection basics
- Desktop + QQ
- bounded vision
- basic proactivity
- streaming voice basics
- authorization gate basics
- DECADE100 closure
- backup/recovery

## 1.x

- bi-temporal graph depth
- proactive preference learning
- richer Vision watch
- mobile/web surface
- procedural SkillBank v1
- relational-safety regression suite
- memory-poisoning suite
- cross-surface delivery ledger
- personalized interruption model

## 2.0

- general computer use
- mature self-evolving skills
- optional ambient desktop history
- Bilibili/social life
- VR/Quest
- advanced multimodal memory
- richer routine inference
- long-horizon autonomous goals

---

# 33. Saturation criterion

The search is considered saturated because later searches increasingly returned variants of the same design conclusions:

- memory systems converge on temporal mutation + provenance + profile/graph layers;
- personalization papers converge on implicit history use and uncertainty;
- proactive-agent papers converge on intervention gating, cancellation, and silence;
- computer-use work converges on visual grounding + state verification;
- skill research converges on verified, versioned procedural libraries;
- companion research converges on stable persona + user-agency / relational boundaries;
- product projects converge on modular voice/avatar/surface layers.

Further literature would add implementation options and benchmark numbers, but is unlikely to change the architecture above.

---

# High-value sources reviewed

## Companion / product systems
- SurfCore — https://github.com/Mieksido/surfcore
- Project AIRI — https://github.com/moeru-ai/airi
- Open-LLM-VTuber — https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- dsh-see-now — https://github.com/SAOS-3624/dsh-see-now
- screenpipe — https://github.com/screenpipe/screenpipe

## Memory systems
- Mem0 — https://github.com/mem0ai/mem0
- Graphiti — https://github.com/getzep/graphiti
- Hindsight — https://github.com/vectorize-io/hindsight
- Letta skills / memory references — https://github.com/letta-ai/skills
- MemOS — https://github.com/MemTensor/MemOS

## Memory / identity evaluation
- LoCoMo — ACL 2024
- Memora — ACL Findings 2026
- ANCHOR / Best Friends, Not Forever — 2026
- RealPref — EMNLP Findings 2026
- MemoryAgentBench — ICLR 2026
- Agent Memory Benchmark — https://agentmemorybenchmark.ai/

## Proactivity / personalization
- ProEvent — EMNLP Findings 2026
- KnowU-Bench — 2026
- PersonalAlign — ACL 2026
- Persona2Web — ICML 2026
- Me-Agent — ACL Findings 2026
- APeB — 2026
- Act2Intention — 2026

## Computer use
- OSWorld — https://os-world.github.io/
- MyPCBench — https://mypcbench.com/
- Agent S — https://github.com/simular-ai/Agent-S
- UI-TARS — https://github.com/bytedance/UI-TARS
- OpenCUA — https://opencua.xlang.ai/

## Procedural skills
- Skill-Pro — ICML 2026
- Skill-Evo4GUI — 2026
- Anything2Skill — 2026
- Resource2Skill — Microsoft Research 2026
- AFTER / Procedural Memory — 2026
- Dynamic Agent Skills survey — 2026

## Security / relational safety
- Memory Poisoning / MPBench — 2026
- OWASP Agentic Top 10 2026
- Authorization Alignment benchmark — 2026
- International AI Safety Report 2026
- Stanford AI Index 2026 responsible-AI chapter
- 2026 longitudinal / relational-safety companion literature
