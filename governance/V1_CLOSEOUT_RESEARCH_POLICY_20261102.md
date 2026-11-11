## Owner override (2026-11-03): cloud API only for Qwen

This supersedes older local-model proposals: no Ollama `qwen3:4b`, `qwen3:8b`, local inference, model download, or silent fallback in XiaoYu cross-model work. The owner-selected model is Alibaba Cloud `qwen3.8-flash` via DashScope API with `DASHSCOPE_API_KEY`; the paired cloud DeepSeek Flash remains the comparator. See `governance/V1_CLOUD_QWEN_OWNER_DIRECTIVE_20261103.json`. Previously frozen local failure results remain immutable history and cannot be promoted. Final cross-model promotion requires fresh prospective cases, caller-side ID allowlisting, deterministic canonical rendering, the same numerical PASS gate, and a paid-scope hard cap strictly below 10 CNY. The frozen product is not silently rewritten by this directive.

# XiaoYu v1 closeout research policy ? 2026-11-02

This policy is authoritative for new work until XiaoYu v1 is released.

## Objective
Finish one defensible product, not an indefinitely expanding research portfolio.

## Active lanes
1. FAST retrieval: one slot. Consume the existing Local Candidate pool through External Dev; mint at most 1?2 E0 v4 candidates. Do not keep generating Local Candidates while viable unconsumed candidates remain.
2. State / Identity: one slot. Unify semantic ingress and state transition; cover correction, retraction, conflict, derived state, persona and relationship continuity.
3. Consolidation / Scale: one slot. Decide what remains active, episodic, consolidated or forgotten; prove 10k+ memory behavior.
4. Product Integration / Reliability: one slot. Integrate accepted bytes and close restart/replay/concurrency/atomicity/RC behavior.
5. Independent Auditor: one slot, milestone only.
Lead routes work and does not take a worker lease. Lead must not start or use Codex.

## Admission rule
Every new task must name exactly one gate in V1_RELEASE_CRITERIA_20261102.json. If it cannot, do not start it.

## 48-hour stop
Every research task must terminate within 48 hours as PASS, FAIL, or INCONCLUSIVE. An unresolved task may continue only when it directly blocks a v1 release gate and Lead records the narrower next falsifier.

## Divergence
Open-ended divergent research is disabled by default. Lead may open one emergency divergent slot only after a release gate is blocked by an unresolved mechanism gap. Close it after one bounded pass.

## Auditing
Do not audit every micro experiment. Audit only: E0/freeze candidates that consume frozen-test budget, material state-architecture candidates, integrated RC/current-root candidates, and final release evidence.

## FAST stopping rule
External Dev is the research gate. Once 1?2 retrieval mechanisms pass and one clears frozen-test promotion, stop retrieval search and integrate. New retrieval research requires a concrete external/frozen failure, not a desire for a higher local score.

## Product-first rule
Prefer deleting/merging mechanisms over adding parallel modules. Pure governance, documentation, naming and micro-performance work is nonblocking unless it is a demonstrated release blocker.
