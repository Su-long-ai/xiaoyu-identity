# Product implementation reuse decisions

This directory is intentionally empty unless a product change touches a commodity-capability area listed in `governance/IMPLEMENTATION_REUSE_POLICY.json`.

For such a change, add one JSON file in this directory in the same PR. The CI gate reads only decision files changed by that PR.

Example:

```json
{
  "schema": "xiaoyu-product-reuse-decision-v1",
  "change_id": "pr-memory-retrieval-example",
  "areas": [
    {
      "area": "memory_retrieval",
      "mode": "custom_policy",
      "components": [
        "sqlite_fts5",
        "fastembed_091_bge_small_zh_v15"
      ],
      "gap": "XiaoYu must filter by current authority, audience and erasure state before a commodity ranker may see candidates.",
      "no_new_infrastructure": true,
      "custom_surface": [
        "authority/admissibility filter around external ranking"
      ]
    }
  ]
}
```

Modes:

- `reuse`: direct adapter; `custom_surface` must be empty.
- `extend`: mature component plus bounded XiaoYu-specific glue.
- `custom_policy`: mature substrate plus XiaoYu authority/policy that cannot be delegated.
- `legacy_compat`: compatibility-only custom code while migrating away from an old path.
- `falsification`: bounded experiment intended to prove a retained component insufficient.

The gate rejects unknown, deprecated or held components, unrelated component kinds, implicit new infrastructure, and commodity changes with no decision.
