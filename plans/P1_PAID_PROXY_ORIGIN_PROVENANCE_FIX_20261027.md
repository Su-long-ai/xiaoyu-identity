# P1 Paid-Model Proxy Origin Provenance Fix — 2026-10-27

## Incident extension

A second, deeper paid-call provenance gap was found while reconciling R27.

The previous proxy-only rule rejected ordinary direct scopes, but `ResearchApiBudget.chat(..., budget_scope="proxy:...")` still accepted a caller-supplied proxy-shaped string. R27 therefore produced scientifically useful paid results under scopes such as `proxy:xiaoyu:r27_caller_bound_v1` even though the calls were made directly through `ResearchApiBudget`, not through the authenticated local HTTP proxy.

This is **not** treated as fraud by the worker: R27 itself correctly downgraded the result to EVIDENCE_ONLY when the provenance problem was recognized. The historical calls remain immutable and non-promotable.

## Root cause

The usage ledger previously treated `budget_scope` as both:
1. accounting namespace, and
2. evidence that a call traversed the proxy.

Those are different facts. A string beginning with `proxy:` is not proof of gateway traversal.

## Fix

`research_api_usage.sqlite3.calls` now has:

```
gateway_origin = "http_proxy" | "direct" | NULL(historical)
```

`ResearchApiBudget` accepts a `proxy:*` scope under proxy-only policy only when the in-process HTTP proxy handler supplies an opaque internal capability. Direct callers cannot mint proxy provenance by choosing the scope string.

`research_api_proxy.py`:
- supplies the internal proxy capability;
- supports optional `X-XiaoYu-Research-Run` with a strict 1-64 character safe token;
- can therefore create unique scopes such as `proxy:xiaoyu:r30_positional_microbatch_v1`;
- validates the base proxy tag against the existing allowlist.

E1 paid-evidence verification now requires every declared call to be:
- present in the durable usage ledger;
- COMMITTED;
- after the research lease was claimed;
- in the declared phase;
- in the exact declared scope;
- under an allowlisted base proxy tag;
- `gateway_origin=http_proxy`;
- within the declared raw-token cap.

The Auditor rechecks the same ledger again immediately before `ACCEPT_E1`.

## Historical handling

Historical rows are **not backfilled** to `http_proxy` merely because their scope starts with `proxy:`.

- R27 direct rows: `gateway_origin=NULL`; remain EVIDENCE_ONLY/non-promotable.
- R18 legacy direct rows: remain historical semantic evidence only and are not used for P1 integration.
- R29 compliant replay: 18/18 declared calls are COMMITTED + `gateway_origin=http_proxy`, scope `proxy:xiaoyu`, total raw 44,293 <= declared 50,000.

This preserves the distinction between scientific content and governance provenance.

## Regression

Dedicated tests cover:
- direct caller attempting to spoof `proxy:*` -> rejected before reservation;
- authenticated proxy capability -> ledger records `http_proxy`;
- run-suffix validation and base-tag allowlist;
- proxy-named row with direct/non-authenticated origin -> E1 submit rejected;
- unique authenticated run scope -> accepted;
- scope mismatch / UNKNOWN call -> rejected;
- Auditor recheck after usage-ledger status change -> ACCEPT_E1 rejected.

The rule is intentionally narrow: it proves traversal through the governed local proxy path, not OS-level process isolation.
