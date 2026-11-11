# XiaoYu / 养鱼 — Next AI Handoff
Generated: 2026-10-29 ~17:10 +08
Project root: D:\dsh-fish

## 0. Read this first

You are taking over the XiaoYu long-term identity/memory system project.

Do NOT assume the state described here is still exact when you start. Your first action must be to re-read live local state because one Research Engineer (R52) is ACTIVE and may submit after this handoff was written.

Do NOT reset/stash/discard the current dirty Git worktree. The branch contains substantial uncommitted E2 confirmatory-pre-freeze work created after the latest pushed commit.

Do NOT launch a second R52 worker while the existing R52 lease is ACTIVE.

Do NOT touch confirmatory LongMemEval cases or the 18 HaluMem confirmatory users until the confirmatory protocol is separately frozen and the final independent re-audit returns READY.

## 1. Project goal

Build a model-independent persistent identity / long-term memory system that preserves:
- source provenance;
- user vs assistant authority;
- correction / supersession / retraction / deletion;
- derived-state lineage;
- conflict / abstention semantics;
- retrieval admissibility;
- identity continuity across models/runtimes/devices.

Scientific correctness and falsifiability matter more than feature count. Reuse existing infrastructure; avoid wheel-rebuilding and governance-for-governance's-sake.

## 2. Current control-plane state

Last live check:
- governance: E0_E1_OPERATIONAL
- current phase: E2_PILOT
- closeout_mode: true
- active agents: 1
- active Research Engineer: 1
- active Auditor: 0
- pending E1 audit: 0
- capacity: 3

ACTIVE:
- agent_id: fish_re_b_20261026_identity
- lease_id: fish-6534847e38ed48b6
- backlog: R52
- family: pipeline.halumem.open_domain_composition
- workspace: D:\dsh-fish\governance\workspaces\fish-6534847e38ed48b6
- state: ACTIVE
- do not duplicate or re-join this task.

Existing identities to preserve:
- Research A: fish_re_a_20261026_t04_9b72
- Research B: fish_re_b_20261026_identity
- Independent Auditor: xy-auditor-independent-20261026-01

## 3. What is already closed / accepted

P1:
- CLOSED + FROZEN
- integration 12/12 READY
- never rewrite p1-freeze-2026-10-28 tag.

P2:
- CLOSED
- integration 7/7 READY.

E2 LongMemEval pilot:
- all 46/46 paid pilot cases completed.
- immutable original paid baseline:
  - normalized exact = 12/46 = 26.09%
  - mean token F1 = 0.3498
  - answer-session hit@7 = 32/46 = 69.57%
  - actual tokens = 63,914
  - cache hit = 0
- no more LongMemEval pilot calls are needed/allowed for remediation.
- R48 retrieval repair: ACCEPT_E1.
- R50 temporal/current-state consumer: ACCEPT_E1.
- R51 semantic binding adapter: ACCEPT_E1.

Important: R48/R50/R51 are implementation evidence only. They do NOT retroactively change the 12/46 paid pilot result.

HaluMem:
- R47 open-domain store/update representation: ACCEPT_E1.
- R49 semantic transition / confirmed destructive boundary: ACCEPT_E1.
- paid R49 semantic-transition canary: 16/16 committed.
- HaluMem full end-to-end composition is now R52 and remains the direct blocker.

## 4. Current E2 paid state

Last live token doctor:
- E2 benchmark calls: 62
- pilot used/reserved: 82,127 / 1,000,000
- pilot remaining: 917,873
- RESERVED: 0
- UNKNOWN: 0
- e2_claim_allowed: false

Scopes:
- LongMemEval answer: 46 committed
- HaluMem semantic-transition canary: 16 committed
- old HaluMem extract / QA tracks remain held.

Cache:
- LongMemEval cache = 0 by structural prompt geometry; do not chase 95% cache hit.
- current policy correctly treats cache target as OBSERVE_NOT_HARD_GATE.
- use cache-miss/raw/output/cost per case instead.
- root-cause note: plans/E2_CACHE_ZERO_ROOT_CAUSE_20261028.md

## 5. R52 live research state — highest priority

Backlog R52:
pipeline.halumem.open_domain_composition

Hypothesis:
Compose exact accepted R47 storage/retrieval + R49 confirmed transition semantics + frozen R49 semantic projector into a full HaluMem pilot pipeline:
raw user+assistant dialogue -> grounded atomic claims/update proposals -> confirmation-bound destructive relations -> provenance-preserving retrieval -> strict QA.

Hard boundaries:
- 2 already-exposed HaluMem pilot users only.
- 18 confirmatory users forbidden.
- no confirmatory calls.
- no new DB/framework.
- preserve exact accepted R47/R49 bytes.
- user-only extraction forbidden; assistant source role must remain represented.
- unconfirmed destructive proposals must never mutate state.
- the 2 unbound R49 strong cases remain non-confirmable.
- QA must answer only from admitted evidence and remain unknown if insufficient.

Latest R52 workspace evidence around 17:08:
- r52_hardening_metrics_v8.json: 128/128 PASS, provider_calls=0, confirmatory_uuid_reads=0.
- r52_normalized_score_v7.json: 50/50 PASS.
- r52_restart_replay_metrics_v7.json: restart/confirm/replay exact, no provider calls, no confirmatory users.
- r52_qa_head_alias_v7_metrics.json: 120/120 PASS.
- r52_qa_prospective_score_v7.json: 48/48 PASS (32 negative + 16 positive).
- r52_qa_ambiguity_score_v7.json: 30/30 PASS.
- r52_qa_sufficiency_v7_metrics.json:
  - safety-required: 344/344 PASS
  - old_structure_diagnostic intentionally 84/120; the failing old heuristic families are diagnostic, not the current safety gate.
- r52_runtime_authority_v8.json includes authority/commitment replication; check the newest file rather than relying only on this handoff.

Latest workspace:
D:\dsh-fish\governance\workspaces\fish-6534847e38ed48b6

When you start, first inspect:
- control status
- R52 workspace newest mtimes/files
- whether result.json / receipt.json / submission now exists
- queue / pending E1.

If R52 is still ACTIVE:
- do not create a duplicate R52 lease;
- inspect progress only;
- let the same agent identity continue;
- if needed, use the exact continuation path rather than a new identity.

If R52 has SUBMITTED:
- do not self-approve.
- activate/resume the existing Independent Auditor identity xy-auditor-independent-20261026-01 for an exact-byte independent audit if queue/policy requires it.
- preserve immutable NEEDS_WORK history if any; remediate with a new submission rather than rewriting old decisions.

## 6. Confirmatory pre-freeze state

Run:
py -3.11 governance\e2_confirmatory_prefreeze_doctor.py

Last live result:
- healthy: true
- freeze_allowed: false
- confirmatory_execution_allowed: false
- e2_claim_allowed: false
- confirmatory paid exposure: LME 0, HaluMem 0
- benchmark RESERVED 0, UNKNOWN 0

Current blockers:
1. R52 must reach independent ACCEPT_E1.
2. Final tracked HaluMem confirmatory runner is missing:
   governance\confirmatory_frozen\HALUMEM_CONFIRMATORY_RUNNER.py
3. Final independent v2 re-audit of exact bytes must return READY.
4. HaluMem judge runtime credential:
   OPENAI_API_KEY is currently absent.
   Do NOT silently substitute DeepSeek/another judge because comparability would change.

The warning about OPENAI_API_KEY is not authorization to request a key early. Freeze all judge/scorer semantics and exact runner bytes first. If execution later truly requires the credential and it is still absent, report the precise blocker instead of substituting a different judge.

Tracked candidate files already exist:
- governance\E2_CONFIRMATORY_PROTOCOL_CANDIDATE_V2.json
- governance\E2_CONFIRMATORY_IMPLEMENTATION_BINDINGS.json
- governance\E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.json
- governance\build_e2_confirmatory_reaudit_manifest.py
- governance\confirmatory_frozen\...

Confirmatory v2 is still BLOCKED_PREFREEZE.

## 7. Confirmatory scientific constraints

LongMemEval confirmatory:
- 454 untouched cases.
- no confirmatory case may be read before freeze.
- primary normalized-exact threshold candidate: >= 0.38.
- basis: one-sided 90% Wilson upper bound of original 12/46 pilot = 0.37849, rounded upward.
- non-regression diagnostics:
  - mean token F1 >= 0.34981
  - answer-session hit@7 >= 0.69565
- zero tolerance for authority/admissibility failures.
- never route using benchmark question_type/gold/answer_session_ids.

HaluMem confirmatory:
- 18 untouched users across Medium + Long.
- official evaluation is LLM-judge-based.
- public repo reference revision: d653749586bfc7d13f5b68e8851f52155b5b1650
- GPT-4o temperature 0.0 is the documented reference config, but final judge/comparability contract must remain frozen exactly before execution.
- external median scores are reference lines only until judge equivalence is established.

## 8. Git state

Branch:
e2-pilot-token-efficiency

Latest pushed commits:
- 2141280 chore: reopen bounded E2 research gaps
- 40dad91 feat: record first E2 pilot and adopt runtime cost metrics
- 8760e8e fix: harden E2 token-efficient execution
- 729e375 feat: freeze token-efficient E2 pilot execution

Worktree is intentionally DIRTY with substantial uncommitted confirmatory/R49/R52-prep work.

Do NOT:
- git reset --hard
- git checkout -- .
- git clean
- stash everything blindly
- overwrite files merely because they are untracked.

First inspect git diff/status and reconcile current local state.

Uncommitted files include (not exhaustive):
- governance/E2_CONFIRMATORY_PROTOCOL_CANDIDATE_V2.json
- governance/E2_CONFIRMATORY_IMPLEMENTATION_BINDINGS.json
- governance/E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.json
- governance/E2_EXECUTION_AMENDMENT_R49_CANARY*.json
- governance/E2_R47_OPEN_DOMAIN_MEMORY_STORE_FROZEN.py
- governance/E2_R49_SEMANTIC_CONTRACT_FROZEN.py
- governance/e2_confirmatory_prefreeze_doctor.py
- governance/e2_finalize_r49.py
- governance/e2_r49_canary_runner.py
- governance/confirmatory_frozen/*
- plans/E2_CONFIRMATORY_PREFREEZE_STATUS_20261029.md
- plans/E2_LME_PILOT_CLOSEOUT_BASELINE_20261029.md
- multiple R49 closeout/finding notes.

Do not commit until the current R52/re-audit boundary is coherent and tests/doctors pass. Never rewrite P1 tag/history.

## 9. First commands for the next AI

Run these before doing any science:

1.
py -3.11 governance\control.py status

2.
py -3.11 governance\control.py queue

3.
py -3.11 governance\e2_token_efficiency_doctor.py

4.
py -3.11 governance\e2_confirmatory_prefreeze_doctor.py

5.
git status --short --branch

6.
Inspect newest files in:
D:\dsh-fish\governance\workspaces\fish-6534847e38ed48b6

Then branch:

A) R52 still ACTIVE:
- do not spawn another R52.
- continue/monitor the exact existing lease/agent.
- verify heartbeat and latest v8+ outputs.
- do not start final Auditor re-audit yet unless R52 has actually submitted exact candidate bytes.

B) R52 SUBMITTED:
- check queue.
- independently audit exact submission with existing Auditor identity.
- if NEEDS_WORK, preserve immutable review and remediate with same RE identity/new submission.
- if ACCEPT_E1, bind exact accepted R52 bytes into confirmatory implementation bindings.

C) R52 ACCEPT_E1:
- create/finalize exact tracked HaluMem confirmatory runner under confirmatory_frozen.
- bind exact scorer/judge semantics.
- rebuild E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.
- run prefreeze doctor.
- open final exact-v2 independent Auditor re-audit.
- only after READY may Lead create a separate confirmatory execution freeze.
- still do not execute confirmatory calls until that freeze exists.

## 10. User preferences / operating style

- Chinese responses.
- User wants real progress, not repeated planning.
- For "继续工作/追上本地进度后继续": re-read live local state and then perform useful work.
- Do not ask needless clarifying questions.
- Do not duplicate active agents.
- Preserve existing agent IDs.
- Prefer narrow falsifiable tasks.
- Avoid wheel-rebuilding.
- Do not burn token merely because budget exists.
- Do not overclaim E2/E3.
- No private identity data in paid benchmark scope.
- Never expose API keys/secrets.
- Do not bypass peak/cost/security guards.
- Confirmatory anti-peeking is strict.

## 11. Current strategic picture

P1 CLOSED/FROZEN
-> P2 CLOSED
-> E2 paid nonpromotional pilot complete enough to identify implementation gaps
-> R47/R48/R49/R50/R51 independently accepted
-> R52 currently active and is the remaining direct HaluMem composition blocker
-> confirmatory v2 pre-freeze is healthy but blocked
-> after R52: HaluMem runner + exact judge/scorer binding + final independent re-audit
-> only then confirmatory execution freeze
-> untouched confirmatory execution
-> independent formal evaluation
-> only then consider E2 claim
-> E3/product remains later.

Do not reopen already-closed tracks without a new reproducible P0/P1 falsifier.


## 12. Product-closure priority added 2026-10-29

Mandatory read: D:\dsh-fish\plans\PRODUCT_CLOSURE_POLICY_20261029.md

After the existing E2 confirmatory closeout, the default next phase is minimum vertical product integration and longitudinal shadow evaluation, not a new broad research wave. New framework/governance research requires a concrete product/longitudinal P0/P1 or a formal-claim need. When the V1 stop conditions are satisfied, freeze the version and stop creating new backlog by default.
