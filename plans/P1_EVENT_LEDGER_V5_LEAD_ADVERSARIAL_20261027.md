# Event Ledger v5 Independent Lead Adversarial Review — 2026-10-27

## Scope

Read-only review of active Research A candidate:
`governance/workspaces/fish-1b3308bdd1fe4c39`

Lead tests live only under:
`governance/lead_workspaces/v5_independent_adversarial_20261027`

No candidate files, production identity data or private records were modified. No model/API calls were made.

## Result

**No new material source-identity / wrong-state P1 found in this Lead adversarial pass.**

This is not an E1 acceptance. Research A remains responsible for its formal candidate and independent Auditor review remains required.

## Derivation-layer adversarial coverage

### Semantic interpretation drift

Tested explicit CLEAR/SET multi-slot messages plus deictic/value-only sources.

Result:
- explicit wrong semantic slot: invalid with textual-slot mismatch;
- deictic wrong semantic slot: same source_event_id, different payload hash;
- no valid semantic retry obtained a different source_event_id for the same immutable textual source.

PASS.

### Repeated same-slot mentions

Repeated the same textual slot multiple times around the source anchor and changed message_seq.

Result:
- both envelopes valid;
- deterministic nearest textual anchor;
- source_event_id stable across message_seq drift.

PASS at derivation layer; message_seq drift is separately quarantined by SQLite metadata.

### Slot names inside SET values

Examples such as:
- subject=游戏, value contains 音乐;
- subject=饮料, value contains 音乐;
- subject=音乐, value contains 游戏.

The value span is excluded from textual-subject discovery.

Result:
- correct subject remains valid;
- interpreting the value's embedded slot name as semantic subject is rejected.

PASS.

### Repeated SET value occurrence

A quote containing the same SET value multiple times yields `set_anchor_missing_or_ambiguous`.

This is safe fail-closed behavior rather than semantic-dependent anchor selection.

### Punctuation fuzz

500 fixed-seed two-slot messages across:
`； ; 。 ！ ! ? ？ newline ， , 、 space`

With an explicit evidence quote containing its textual slot:
- material divergent valid source IDs: **0/500**
- correct interpretation invalid: **0/500**

PASS.

### Safe availability boundaries

1. Overlapping future slot labels, e.g. `饮料` and `热饮料`, make an explicit longer-slot quote appear to contain multiple known slot names and currently fail closed as `quote_subject_ambiguous`.
2. A *narrow* evidence quote such as only `清空` combined with a Chinese comma separating multiple slot clauses can fail closed as `clause_subject_ambiguous`, because Chinese comma is intentionally not in `CLAUSE_BREAKS`.
3. Repeated value anchors fail closed.

These are usability/schema boundaries. This Lead pass found no silent wrong-state mutation from them.

## SQLite-path adversarial coverage

A second test exercised the actual `stable_event_sqlite_v5` ingest/projection behavior.

### Explicit multi-slot wrong interpretation
- correct CLEAR inserted;
- wrong semantic slot invalid;
- state after bad retry unchanged from correct state.

PASS.

### Deictic semantic drift
- two interpretations share source_event_id;
- payload hashes differ;
- first inserts;
- second => `source_conflict`;
- conflicted source event is removed;
- projection returns to pre-ambiguous state.

PASS.

### Source-text drift under same message identity
- first interpretation inserts;
- changed source text with same conversation/message identity => `message_conflict`;
- all active events from that message are removed;
- projection returns to pre-message state.

PASS.

### message_seq drift
- derivation source_event_id remains stable;
- SQLite immutable message metadata detects seq mismatch;
- => `message_conflict`;
- projection returns to pre-message state.

PASS.

### Narrow-quote Chinese comma case
Both correct and wrong semantic interpretations fail envelope validation; no mutation occurs.

Safe availability loss, PASS for integrity.

## Evidence

- `v5_independent_adversarial.py`
- `v5_independent_adversarial_metrics.json`
- `v5_independent_sqlite_adversarial.py`
- `v5_independent_sqlite_adversarial_metrics.json`

## Lead interpretation

The v5 design appears to remove the previously audited semantic-slot dependency from source identity for the tested in-scope cases.

The remaining boundaries should be recorded explicitly:
- slot schema should avoid overlapping labels or introduce a deterministic longest-match/tokenized subject parser;
- narrow evidence quotes across comma-separated multi-slot clauses may abstain;
- compound multi-subject evidence needs a deterministic splitter rather than envelope guessing.

None of those boundaries justifies weakening fail-closed behavior.

Formal E1 status must still come from the normal Research submission + independent Auditor path.
