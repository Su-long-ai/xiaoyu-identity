# Product Proposal Freshness Remediation — 2026-10-29

Status: **INDEPENDENT RECHECK PASS (72/72)**

This is a product closeout note, not a new governance layer.

## Exact product snapshot

- identity_core.py: 0be0a8bb19824a42630141c9c0ccaa32a88de6f45229b2c022ad39ffcbf69337
- companion.py: c3ce7aef02fb1c359e9b294287781788166df9889dd16c243d76bea4b3074786
- product_memory_bridge.py: 1ef7e2fd63652beef7aafc97a0e01888894f12eb88c9f49366a4510f15c195ff
- test_identity_v2.py: e215855cc269a078280ad89d60d35a5f63be8b9a20ac5689798f66f83d2dfd36
- test_product_memory_bridge.py: ca10e5e893fc35dbb99223228ef5ef4c4df63b546c8aececbb0acffec43e5845

## Reproduced defect

Independent Auditor E0 reproduction on pre-remediation bytes showed:
- newer preference approved first, then older pending proposal promoted: 12/12;
- stale old fact active/retrievable/model-visible: 12/12;
- sampled export/restore preserved both conflicting facts: 4/4.

Root cause: review_proposal() treated a pending proposal as a durable approval capability and validated only status='pending'.

## Remediation

No string-similarity or hidden semantic classifier is used.

1. Review-time exact lineage:
   - later conversation.user with invalidates_source_event or supersedes_source_event makes the older proposal require current reconfirmation;
   - later explicit reaffirms_source_event restores freshness.
2. Conservative natural-flow fallback:
   - an older literal-preference proposal cannot one-click promote after a newer literal-preference proposal has already been accepted.
3. A stale proposal remains recoverable by explicit current user confirmation:
   - UI labels it as requiring reconfirmation;
   - approval explicitly says the content will be confirmed as current;
   - persistence creates a new canonical memory.saved event;
   - resulting long-term memory points to that new current evidence, never the obsolete source event.
4. Rejection remains unchanged.

The fallback can conservatively warn for two unrelated literal preferences. This is intentional fail-closed behavior: it may require an extra explicit current confirmation, but it does not guess semantic supersession.

## Verification

Targeted proposal freshness tests: **4/4 PASS**.

Combined product suite:
`py -3.11 -m unittest -v test_identity test_identity_v2 test_product_memory_bridge`

Result: **36/36 PASS**.

Natural public-API + ProductMemoryBridge reproduction after remediation:
- old one-click approval blocked: true;
- old fact active/recalled before reconfirmation: false/false;
- newer fact active/recalled: true/true;
- explicit stale reconfirmation creates canonical source kind memory.saved, actor=user;
- old fact becomes recallable only after that explicit current reconfirmation;
- export/restore preserves both user-confirmed current facts;
- restored identity integrity: ok;
- overall: PASS.

No provider calls or private identity data were used.

## Remaining boundary

Independent Auditor `xy-auditor-independent-20261026-01` rechecked the exact remediation bytes in workspace `fish-51c58a4af65b43c6` on a 72-case pre-frozen suite: **72/72 PASS**. The old finding remains historically valid only for the earlier bytes; the current proposal-freshness blocker is independently closed at the tested boundary.
