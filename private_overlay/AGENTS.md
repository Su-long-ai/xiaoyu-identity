# XiaoYu Private Overlay Agent Rules

This is a private customization project. Do not create issues, pull requests, comments, releases, forks, or pushes to Project N.E.K.O or any third-party repository.

Work order:
1. Reuse N.E.K.O native capability when it already meets the wanted behavior.
2. Prefer private configuration.
3. Prefer an external N.E.K.O plugin living in this repository.
4. Prefer mature external components behind a single authority boundary.
5. Add a narrow adapter.
6. Only then add a local N.E.K.O core patch and record it in patches/series.json.

Authority:
- one memory authority per domain;
- one persona-storage authority per domain;
- one task/effect authority per domain;
- never introduce silent dual writes.

Optimization target:
- maximize the user's overall private XiaoYu experience;
- do not add abstraction merely to make code upstream-general;
- evaluate candidates by overall product benefit, not by any isolated small regression.

Remote policy:
- pushing work to the user's own private xiaoyu-identity repository is allowed when part of the project workflow;
- third-party/upstream publication requires explicit user instruction.
