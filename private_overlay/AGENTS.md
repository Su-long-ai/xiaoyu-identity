# XiaoYu Private Overlay Agent Rules

This is a private customization project. Do not create issues, pull requests, comments, releases, forks, or pushes to Project N.E.K.O or any third-party repository.

## Product-main freshness

Long-lived `agent/**` work must stay on the current XiaoYu product lineage.

- Fetch `origin/private/neko-overlay-v1` before starting a new implementation unit.
- The machine workflow checks product-main ancestry at the agent HEAD commit boundary. A commit that was already current when it was created is not retroactively invalidated by a later concurrent product-main push, but the next agent push must resync.
- Do not stack long-lived implementation on an obsolete product/gate baseline.
- Preserve the product-main reuse, architecture, plugin-admission and release-readiness gates when synchronizing.

## Hierarchical reuse order

Before long-lived implementation, classify the gap and search in this order:

1. **L0 authority/product layer** — decide which existing authority should own the behavior.
2. **L1 current pinned N.E.K.O** — reuse the current product kernel if it already satisfies the requirement.
3. **L2 latest N.E.K.O upstream and native seams** — Plugin SDK, PluginStore, NekoClaw, MCP, native delivery, native model/permission/runtime surfaces.
4. **L3 already-pinned external components** — current QQ/voice/provider/activity components before adding another dependency.
5. **L4 broader mature ecosystem** — mature OSS, provider-native or OS-native capability where it can stay replaceable behind the existing authority boundary.
6. **L5 thin integration** — configuration, adapter, bridge or CI wiring only for the residual gap.
7. **L6 private implementation / managed patch** — last resort after a reproduced, machine-verifiable gap.

Every new reuse review must record all seven layers as `checked` or `not_applicable`, with evidence/outcome or a concrete rationale. A custom adapter or implementation must not stay entirely inside the local component search space.

## Implementation admission

Before writing a long-lived implementation unit, satisfy one of:

- an existing approved reuse review explicitly covers the gap;
- add a formal reuse review with evidence first;
- keep the work candidate/probe-only behind a machine-verifiable native acceptance gap, with direct product promotion forbidden until a separate promotion decision closes the gap.

Candidate/probe work is not product implementation. Do not silently move candidate patches or blocked output classes into the stable product inventory.

## Authority

- one memory authority per domain;
- one persona-storage authority per domain;
- one persona-evolution/evidence-promotion authority per domain;
- one task/effect authority per domain;
- N.E.K.O native is the default authority for all four above;
- N.E.K.O remains the Companion Kernel and publication authority;
- N.E.K.O Plugin SDK is the default extension plane;
- one-step execution stays on native plugin dispatch;
- multi-step execution stays on NekoClaw;
- external capabilities stay behind existing MCP/Plugin SDK/native seams;
- never introduce silent dual writes or a second evolution, plugin, model, memory, permission, delivery or agent runtime.

## Optimization target

- maximize the user's overall private XiaoYu experience;
- keep XiaoYu-specific runtime code as small and replaceable as possible;
- prefer removing private code when native/external equivalence becomes available;
- do not add abstraction merely to make code upstream-general;
- evaluate candidates by overall product benefit, not by any isolated small regression;
- use existing product tests/evidence instead of creating parallel test/runtime authorities.

## Machine gates

Ordinary `agent/**` pushes and product-main pushes execute repository machine gates.

- `tools/check_reuse_first.py`
- `tools/check_architecture_freeze.py`
- plugin admission / capability-floor checks
- overlay contracts
- release readiness and stable-release-manifest consistency
- pinned N.E.K.O / QQ / product-state regressions

When a gate fails, fix the implementation, synchronization, or evidence. Do not delete, skip, weaken or special-case the gate merely to make a candidate green.

## Remote policy

- pushing work to the user's own private `xiaoyu-identity` repository is allowed when part of the project workflow;
- third-party/upstream publication requires explicit user instruction;
- no upstream N.E.K.O or third-party PR/Issue is part of this private product workflow.
