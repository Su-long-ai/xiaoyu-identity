# Product Send Fail-Closed Secondary Read-Only Review — 2026-10-29

Status: NON-AUTHORIZING SECONDARY EVIDENCE

This note does not close governance finding P1 and does not replace the required independent exact-byte recheck by `xy-auditor-independent-20261026-01`.

A read-only Codex review was run from `D:\dsh-fish` against the current exact product path and the handoff `governance/PRODUCT_SEND_FAILCLOSED_REMEDIATION_REAUDIT_HANDOFF_20261029.json`.

Observed current path:
- `companion.send` calls `safe_product_recall`.
- Any recall/reconciliation error other than `quarantined_memories:*` is classified as a hard memory failure.
- On hard memory failure, `project_history(..., fail_closed_current_event_id=<current user event>)` withholds all earlier dialogue and retains only the current user turn.
- `safe_product_recall` returns an explicit empty memory set on bridge/reconciliation exceptions, so `identity_context(..., memories_override=[])` cannot silently fall back to legacy memory.
- Current regression includes a direct tombstone-write failure test and a direct project-history fail-closed test.

Lead-local evidence re-run in this continuation:
- exact tombstone fault recheck: 16/16; deleted_visible=0; current_event_only=16; long_term_failclosed=16; current_query_visible=16; provider_calls=0; private_identity_reads=0.
- full product regression: 38/38 PASS.

Secondary reviewer conclusion:
- No counterexample was found for the specified P1 recent-dialog leak on current source bytes.
- Healthy path remains unchanged when `fail_closed_current_event_id=None`.
- Existing frozen reference evidence reports healthy payload exact equality 16/16 and retry recovery preserving the valid sibling 16/16.
- The separate cold-start / legacy-index physical-delete P2 remains outside this P1 closure.

Boundary:
- Secondary reviewer could inspect current source and existing evidence but its read-only execution policy prevented re-running write-producing governance scripts and independent SHA recomputation.
- Formal closure still requires the registered independent exact-byte recheck.
