# ADR-008 — Separate memory-state QA evidence from structured event-candidate extraction

Status: Accepted correction
Date: 2026-10-27

## Context

The accepted submission sub-b2146407c7094527 is named model.deepseek.zh_event_parser, but its frozen model interface returns batch items with:

- id
- answer
- evidence_index

Its primary evidence is bounded current/historical memory-state QA plus evidence selection.

The separately accepted strict response validator sub-e73d88bade244116 validates a different interface:

- id
- events[]
- each event has op, slot, value and evidence_quote

The validator's frozen raw inputs come from the p1_anaphora event-generation experiment inside sub-f74d3199bbc347a4. That overall submission was NEEDS_WORK because the source-identity implementation was later falsified. The validator E1 remains valid for its response-boundary property, but it does not independently promote the upstream event generator to E1.

## Considered options

1. Treat the two accepted submissions as parser -> validator because their prose both mentions memory/event extraction.
2. Write an implicit adapter from answer/evidence_index into SET/CLEAR events.
3. Keep the evidence scopes separate and require a focused E1 for the exact model event-candidate interface.

## Decision

Use option 3.

Do not invent an adapter that fabricates op/slot/value semantics from an answer-only interface. The P1 integration contract marks semantic_event_extractor blocked until R16 independently establishes the exact batch event interface consumed by the strict validator.

sub-b214 remains useful accepted evidence for bounded semantic memory-state/evidence selection and may be reused as a model/prompt reference, but it is not counted as the P1 event extractor.

## Consequences

- P1 integration readiness becomes more conservative.
- The strict validator remains ACCEPT_E1 in its tested boundary scope.
- R16 first reuses frozen event raw responses and only spends new model tokens for a pre-frozen focused prospective set if necessary.
- Future catalog entries must distinguish a component's actual wire/schema contract from a broad family name.

## Revisit when

A focused structured-event extractor is independently ACCEPT_E1, or the P1 architecture deliberately abandons the SET/CLEAR event interface and updates all downstream stages together.
