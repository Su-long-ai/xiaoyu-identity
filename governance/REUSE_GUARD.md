# XiaoYu Build-vs-Reuse Guard — 2026-10-27

## Purpose

Prevent research from silently turning a project requirement into a new database, search engine, vector store, graph store, archive format, provenance platform, benchmark harness, or framework collection when a retained mechanism already exists.

The guard is enforced in `governance/control.py`, not only by prose instructions.

## Two-phase enforcement

### 1. Before a new research lease

Every new `research_engineer` lease created after the policy epoch must pass `reuse_check()`.

A self-directed claim must provide a machine-readable reuse plan:

```json
{
  "mode": "reuse | extend | custom_policy | legacy_compat | falsification",
  "components": ["known_component_id"],
  "gap": "Concrete description of the XiaoYu requirement the retained mechanism does not satisfy.",
  "no_new_infrastructure": true,
  "new_dependencies": []
}
```

The component IDs come only from `REUSE_CATALOG.json`. Unknown components and nonempty `new_dependencies` are rejected. Adding a framework/dependency therefore requires Lead to update the catalog first.

Static backlog tasks already carry Lead-vetted `reuse_plan` entries. `continuation.py` passes them automatically. The caller cannot substitute a different plan for a backlog ID.

The resulting decision is stored twice:
- canonical fields in `registry.sqlite3`;
- `REUSE_DECISION.json` in the lease workspace, with SHA256 stored in the registry.

Tampering with or deleting that file blocks submission.

### 2. At submission

Guarded leases must include:

```json
"reuse_compliance": {
  "components_considered": ["same IDs as the lease plan"],
  "new_dependencies": [],
  "new_infrastructure": false,
  "deviation": "none"
}
```

The component list must exactly match the lease decision. Any new dependency or new infrastructure is rejected. A deviation from the approved plan is rejected unless the original lease was explicitly `falsification` or `legacy_compat`; otherwise the worker must obtain a new Lead-reviewed claim.

The reuse-decision SHA is also embedded in the evidence receipt and checked by `verify`.

## Current machine-enforced reuse classes

- lexical posting/inverted-index work must name `sqlite_fts5`;
- ZIP/JSON future archive patch families are legacy/falsification only and must anchor to `sqlite_backup`;
- provenance work must anchor to Cognee/Graphiti provenance/temporal mechanisms;
- explicit custom vector DB / ANN / graph DB construction is falsification-only;
- broad external-memory framework collection is frozen to Mem0/Hindsight/Cognee/Graphiti + OmniMemEval;
- CI work stays on the existing minimal hash/gate trust root;
- each capability additionally has an allowed retained-mechanism baseline.

## Recovery

Existing leases created before the guard are not interrupted.

If such a lease later becomes STALE/TTL_EXPIRED, only an **exact same family + lineage + capability + hypothesis** recovery may receive `grandfathered_recovery`. This bypasses only the new capability-baseline declaration; duplicate-wheel rules still apply. A changed scope cannot ride an old lease.

## Dry run

For a self-directed hypothesis, run `reuse-check` before `join`:

```powershell
py -3.11 governance\control.py reuse-check ^
  --role research_engineer ^
  --family retrieval.example ^
  --lineage retrieval.example ^
  --capability memory_retrieval ^
  --lane main_bottleneck ^
  --hypothesis "..." ^
  --reuse-plan-json "{...}"
```

Only a PASS should proceed to `join` with the identical reuse plan.

For a vetted backlog task, `next --agent-id ...` supplies the plan automatically.

## What this guard does not claim

This is not a semantic theorem prover. A worker could still lie in prose or write unlisted code. The guard prevents the easy structural failure modes: silent new dependencies, unregistered frameworks, known duplicate infrastructure classes, plan substitution, scope-changing recovery, and post-claim decision tampering. E1 independent audit remains responsible for checking whether the submitted evidence actually follows the declared architecture.

The rule for future expansion is intentionally asymmetric: **adding a standard/reused component is cheap; authorizing a new custom infrastructure class requires an explicit Lead catalog change and falsifiable evidence that the retained mechanisms are insufficient.**


## Operational coverage / deployment-gap handling

Use:

```powershell
py -3.11 governance\control.py reuse-audit
```

The report distinguishes:
- `active_unguarded`: post-epoch research leases that must not continue;
- `pending_unguarded_e1`: unguarded candidates that must never be ACCEPT_E1;
- `unguarded_submission_details`: historical evidence retained for audit;
- `enforcement_clean`: true only when there is no active unguarded lease and no pending unguarded E1.

A post-epoch unguarded ACTIVE lease:
- cannot be resumed by `next`;
- cannot heartbeat/extend its lifetime;
- cannot submit;
- may be repaired only by an explicit Lead `reuse-retrofit` while still ACTIVE, using a valid current reuse plan and concrete reason.

A submission that already committed before the deployment-gap detector existed is never retroactively edited. If it is LEAD_READY/PENDING, `review ACCEPT_E1` rejects it and the experiment must be repeated under a guarded lease. Historical EVIDENCE_ONLY can remain as non-promotable evidence.

The 2026-10-27 deployment itself exposed one short race between policy activation and code rollout. One Research B lease entered that gap and committed only EVIDENCE_ONLY. It is preserved unchanged for audit, is not active/pending E1, and current `reuse-audit` reports `enforcement_clean=true`.


# Build-vs-Reuse Guard V2 — external-research saturation update

Date: 2026-10-27

V2 extends the original infrastructure-duplication guard with three additional failure classes discovered by external survey:

1. **stale/unsafe reuse** — a component name is not enough; lifecycle, owner, exact source/version/license/health and review date matter;
2. **experiment duplication** — a new family name can still repeat an old scientific hypothesis;
3. **decision drift** — a component or policy can change after a lease was approved.

## New commands

```powershell
py -3.11 governance\control.py prior-work --family <family> --lineage <lineage> --capability <capability> --hypothesis "<hypothesis>"
py -3.11 governance\control.py reuse-doctor
```

For a self-directed V2 task, run `prior-work` before `reuse-check`. The reuse plan must include:

```json
"prior_work": {
  "reviewed": ["fish-..."],
  "novelty": "Concrete material difference from the closest previous work (>=50 chars).",
  "replication_of": null
}
```

The gate requires review of up to the closest material prior leases when the hypothesis is exact/high-similarity or the stable family/lineage matches. An exact already-submitted hypothesis is blocked unless the new work explicitly declares falsification or replication.

This does not ban scientific replication; it makes replication intentional rather than accidental.

## Component lifecycle

`REUSE_CATALOG.json` V2 records lifecycle: `adopt / trial / reference / hold / deprecated`.

New normal use of `hold` or `deprecated` components fails closed. Generic aliases such as `existing_vector_backend` are deprecated; concrete implementation/version IDs are required.

`reuse-doctor` checks catalog metadata, stale review dates, blocked components in backlog/active decisions, catalog revision drift, reuse coverage, and near-duplicate historical work. Catalog drift is advisory for an already-running lease; a newly claimed lease uses the current catalog.

## Scope control

No Backstage/OPA/Cedar/MLflow/DVC service was added. The project borrows their catalog, decision-log, lifecycle and searchable-run ideas inside the existing stdlib/SQLite control plane. This is deliberate: the anti-reinvention mechanism must not itself become another platform.
