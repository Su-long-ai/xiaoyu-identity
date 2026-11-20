# XiaoYu Private Overlay Agent Rules

This is a private customization project. Do not create issues, pull requests, comments, releases, forks, or pushes to Project N.E.K.O or any third-party repository.

Work order:
1. Reuse N.E.K.O native capability when it already meets the wanted behavior.
2. Prefer private configuration/data.
3. Prefer a mature external component or pinned external N.E.K.O plugin when it already solves the surface.
4. Add code to the private XiaoYu plugin only for behavior that is actually private to XiaoYu and cannot stay as data/configuration.
5. Add a narrow adapter only when a concrete product test proves one is needed.
6. Only then add a local N.E.K.O core patch and record it in patches/series.json.

Authority:
- one memory authority per domain;
- one persona-storage authority per domain;
- one persona-evolution/evidence-promotion authority per domain;
- one task/effect authority per domain;
- N.E.K.O native is the default authority for all four above;
- never introduce silent dual writes or a second evolution engine.

Optimization target:
- maximize the user's overall private XiaoYu experience;
- keep XiaoYu-specific runtime code as small as possible;
- do not add abstraction merely to make code upstream-general;
- evaluate candidates by overall product benefit, not by any isolated small regression.

Remote policy:
- pushing work to the user's own private xiaoyu-identity repository is allowed when part of the project workflow;
- third-party/upstream publication requires explicit user instruction.
Reuse-first machine gate:
- Before adding a private runtime plugin, a managed N.E.K.O core patch, or an equivalent new runtime subsystem, first create and approve a review entry in governance/reuse_reviews.json.
- The review must inspect N.E.K.O native/upstream capability and mature external components, record concrete candidates/evidence, and explain why reuse is insufficient when any custom adapter or implementation remains.
- tools/check_reuse_first.py is fail-closed and is part of tools/run_checks.ps1. A new runtime patch/plugin without an approved review blocks release checks.
- When a reusable candidate becomes viable later, prefer replacing/deleting private implementation rather than preserving sunk-cost code.
