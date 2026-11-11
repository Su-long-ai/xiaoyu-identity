# R49 real-canary failure root-cause note — 2026-10-29

Status: LEAD POST-SUBMISSION ANALYSIS / NOT AN AUDIT DECISION

This note does not modify submission sub-40659a16213f4bec, the frozen 16-case
canary, any provider receipt, or any E2 claim boundary.

## Evidence boundary

- 16/16 frozen R49 canary receipts exist.
- strict v1 validator accepts 11/16.
- previously independent-ACCEPT_E1 v2 validator replay accepts 13/16.
- all 16 replay request hashes match the original paid requests.
- every v2-rejected case leaves R47 state unchanged.
- no new provider call was used for this analysis.

## Remaining three failures

### 1. hm-l-i-161e74a81851-42-2 — caller intent false positive + unsafe generic assistant extraction

Source 0 is the user question:
`Give me the definition of Machine Learning.`

Source 1 is a 2957-character assistant encyclopedia-style explanation.

The frozen caller heuristic marks source 1 as relation_intent=true only because the
generic prose happens to contain the ordinary words matching:
- `\binstead\b`
- `\bcorrect(?:ed|ion)?\b`

With no prior assistant candidate, caller binding therefore becomes `missing`.
The model then returns seven NEW generic machine-learning facts for that source.

Two distinct problems are exposed:

1. **caller-side false positive**: broad lexical update cues are not context-aware and
   can misclassify ordinary long-form explanatory prose as an update/correction intent;
2. **durability admission gap**: the semantic projector treats generic assistant
   encyclopedic content as durable memory candidates without any bounded
   user-/relationship-relevance criterion.

Do not fix this by merely accepting proposals under `missing`; that would convert a
caller ambiguity into mutation authority.

Candidate remediation direction:
- preserve strict fail-closed binding;
- make relation-intent detection role/context aware and adversarially test common prose;
- explicitly separate generic assistant knowledge from eligible assistant-origin
  conversation evidence;
- keep assistant origin as `conversation_history`, never user_state.

### 2. hm-l-i-161e74a81851-42-4 — non-unique evidence quote

The provider returns otherwise syntactically valid proposals, but at least one
`evidence_quote` occurs more than once in its source. The existing exact-source
validator therefore cannot bind a unique source span.

Do not weaken provenance to “first occurrence wins”.

Candidate remediation direction:
- retain the unique-span validator;
- prompt/validate that the model extends a repeated short quote until the selected
  exact span is unique;
- add frozen repeated-phrase attacks and require deterministic anchoring.

### 3. hm-l-i-1e18c8d18b0f-32-0 — unbounded proposal fan-out + positional/source bleed + truncation

The user source is only:
`Give me a detailed overview of Author Mark Twain.`

The assistant source is a 5135-character Mark-Twain overview.

The provider output reaches the frozen 768 completion-token cap and is invalid JSON.
Before truncation, the first output position already contains many Mark-Twain facts
whose evidence quotes come from the assistant article, not from the short user
question. The second output begins emitting the same generic article facts again.

This exposes more than a cap problem:
- the schema has no `maxItems` bound on `proposals`;
- long generic assistant text can create memory explosion;
- positional source-locality can bleed before the strict validator catches it;
- merely raising max_tokens would increase cost and preserve the unsafe behavior.

Candidate remediation direction:
- keep the current completion cap until the proposal fan-out is bounded;
- add a frozen maximum proposals/source backed by attacks, rather than arbitrary
  post-hoc truncation;
- add explicit “generic encyclopedic assistant exposition is not durable personal
  memory” admission semantics;
- add source-local grounding attacks where two adjacent sources discuss the same topic;
- consider single-source semantic projection only if bounded batching cannot preserve
  source-locality, and freeze any such cost change prospectively.

## Recommended R49 remediation gate after independent audit

A remediation should not be promoted merely by replaying the same 16 exposed receipts.
It should first pass frozen synthetic/pre-frozen attacks covering:
- ordinary prose containing update-cue words such as instead/correct/change/now;
- long assistant encyclopedic passages;
- repeated evidence phrases requiring unique-span extension;
- adjacent user/assistant same-topic source-locality;
- bounded multi-claim fan-out;
- exact JSON validity under the unchanged or explicitly prospectively frozen cap;
- zero mutation on ambiguous/missing bindings;
- assistant-origin authority preservation.

Only after that should a new small prospective pilot canary be considered. Full 647
extraction, QA, and all confirmatory users remain locked.
