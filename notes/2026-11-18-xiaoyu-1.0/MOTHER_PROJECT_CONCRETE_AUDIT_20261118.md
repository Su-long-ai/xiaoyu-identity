# XiaoYu mother-project concrete audit — 2026-11-18

Status: **SOURCE + LOCAL-RUNTIME AUDIT / NO CUTOVER AUTHORIZATION**

Base XiaoYu frontier: `feat/reuse-first-credentials` @ `8f4d5d24ba399d30b0c510ad1dd3c3842c497103`.

This document corrects a weakness in the first replacement decision: discovery/README overlap is not enough to select a mother project. Serious candidates are compared using inspected source, exact source revisions, targeted local tests and XiaoYu-specific adversarial cases.

## 1. Audit rule

A claim is labeled as one of:

- **LOCAL PASS / FAIL** — exercised on this Windows machine against the audited revision.
- **SOURCE CONFIRMED** — implementation was inspected directly but not executed locally.
- **ENVIRONMENT BLOCKED** — execution did not reach the product assertion; it is not counted as a product failure.
- **NOT FOUND / GAP** — no equivalent was found after directed source search.

A mother-project candidate must win on whole-product fit. A small regression does not eliminate a candidate when total product benefit is positive, but privacy/erasure/external-effect correctness gaps must remain explicit.

## 2. Audited revisions

| Candidate | Audited revision | Local/source status |
|---|---|---|
| Project N.E.K.O | `402695cd115323440dfd4e6860c25a32c10dda43` | source + targeted local pytest |
| MIRA | `0eb6e7602b9913ce5859dc4648f1a0805c392749` | source; Rust local build environment-blocked |
| Alicization | `42de37fc5d20ba744f71879bcc3bcef8434e8244` | source + targeted local Vitest |
| Psycheros/entity-core | `724987dc072a0bbc9914be58c73efc278154a410` | source + custom local resurrection attack |
| Miru | `cbea20b436a255e3cd26d952aaf952c003990b65` | source + targeted local pytest |
| OpenCharaAgent | `c094c62eabb1c1c1ecb5f41d6684ce3b716105dd` | source + targeted local pytest |
| Cremind | `e6b9d4dd3c1dc3bc20d6bcff32cf916b5011bbe0` | source |
| Cyrene-Agent | `852ec5765183ea62c45eba8a3db0a5aae2b74bbb` | directed source audit |
| AILIS | `361a733e1a613eec7e63d334b48ff18d8c23a6c1` | directed source/benchmark audit |

Audit checkouts are isolated under `D:\xiaoyu_external_audit`; the old dirty `D:\dsh-fish` workspace was not used or modified.

## 3. Project N.E.K.O — current leader

### 3.1 Critical erasure / restore tests

The latest audited N.E.K.O revision was sparse-cloned and a dedicated Python virtual environment was used. Missing test-only/runtime dependencies were installed into that isolated environment, not globally.

The following eight high-value tests were selected because they map directly to XiaoYu replacement criteria 5–7:

1. `test_restore_does_not_revive_snapshots_preceding_scoped_forget`
2. `test_restore_waits_for_subject_forget_transaction`
3. `test_privacy_erasure_clears_cold_rows_and_fails_whole_on_a_broken_shard`
4. `test_forget_while_generation_in_flight_drops_every_item`
5. `test_forget_landing_while_staging_is_written_is_caught_by_the_recheck`
6. `test_malformed_tombstone_fails_closed`
7. `test_story_forget_tombstone_drops_writes_without_its_marker_and_survives_restart`
8. `test_unfinished_forget_log_blocks_the_block_after_restart`

**Result: 8/8 LOCAL PASS.**

The first run was intentionally incremental: four tests passed while four were blocked only by missing sparse-checkout modules; after adding upstream `knowledge` / `services` and the minimal dependencies, the remaining four also passed. No product assertion failed in the final targeted set.

A second directed local set then exercised adjacent acceptance behavior:

- legacy unscoped rows remain private and never become global;
- hybrid recall filters scope **before** rankers;
- persona view exposes only authorized scoped sections;
- scoped synthesis prompts do not name the private master;
- correction facts pair with and replace stale facts;
- private persona snapshots are detached and preserve retained fields;
- kept-promise reports mark commitments done;
- due promises lead proactive memory cues;
- OneBot forward path maps private inbound messages;
- OneBot action replies are echo-correlated;
- Molili external import maps into bounded layers;
- repeated persona import is idempotent without another LLM call.

The selected tests expanded through parametrization. After filling only missing isolated test dependencies / sparse-checkout paths, **14/14 executed cases passed locally**. The proactive-commitment test initially stopped at missing optional runtime imports (`soxr`, `Pillow`, `jmespath`); after installing those in the audit venv it executed and passed. These dependency stops are not counted as product failures.

### 3.2 Source-confirmed mechanism

N.E.K.O implements mechanisms materially stronger than ordinary memory deletion:

- per-subject forget generations / tombstone fences;
- generation captured before asynchronous extraction and rechecked before persistence;
- pending/staged writes cancelled or fenced when forget lands;
- active/archive/cold/index cleanup;
- restore serialized against subject forget;
- restored data preceding a scoped forget is not revived;
- malformed/unreadable erasure state fails closed in relevant paths;
- forget markers survive restart;
- OneBot/NapCat support exists in the same product runtime.

This is the strongest observed fit to XiaoYu's deletion-no-resurrection requirement.

### 3.3 Remaining N.E.K.O gaps

N.E.K.O still does **not** get an unconditional pass.

- **Provider disclosure/privacy eligibility: GAP.** No equivalent was found for XiaoYu's per-request `data_class/privacy_eligible/audience_scope` provider admission rule.
- **External side-effect uncertainty: PARTIAL.** OneBot uses echo-correlated single sends and does not blindly reissue on timeout, but timeout `None` still conflates “not sent” and “sent, ACK lost”. High-risk duplicate-sensitive actions still need UNKNOWN/reconciliation semantics.
- **Exact arbitrary historical truth: NOT REQUIRED YET.** N.E.K.O has temporal/correction mechanisms, but an exact XiaoYu R9 point-in-time authority should survive only if product tests prove value.
- **Generic AOP interception: DO NOT RELY ON IT.** Previous source audit found hook metadata ahead of the inspected runtime consumer. Use the implemented adapter/policy gateway and narrow admission seams instead.

## 4. Psycheros/entity-core — elegant identity model, hard no-resurrection failure

Psycheros is the cleanest inspected implementation of:

> one canonical entity / multiple embodiments

Its `entity-core` owns identity files, hierarchical memory and knowledge graph behind MCP.

However, the snapshot restore path directly writes snapshot identity content back after backing up the current file; no erasure generation/epoch/tombstone fence was found.

A custom external attack script (not an upstream modification) executed:

1. write `SYNTHETIC_SECRET_MUST_STAY_DELETED`;
2. create identity snapshot;
3. delete the identity file;
4. verify it is absent;
5. restore the old snapshot;
6. read current identity.

Observed result:

```json
{
  "deleted": true,
  "absent_after_delete": true,
  "restore_success": true,
  "resurrected": true,
  "restored_content": "SYNTHETIC_SECRET_MUST_STAY_DELETED\n"
}
```

**Verdict: LOCAL FAIL for XiaoYu criterion 6.**

Keep Psycheros as an identity-continuity design reference. Do not adopt `entity-core` unchanged as XiaoYu memory/identity authority.

## 5. Miru — strong lightweight companion, weak cross-backup erasure

Targeted local tests:

- auth/delete;
- attention engine;
- chat archive/consolidation.

**Result: 51/51 LOCAL PASS** (two pytest warnings about tests returning values, no assertion failures).

Source confirms real implementations for:

- per-user AttentionEngine;
- commitments;
- daily journal;
- inspectable file memory;
- current-state user deletion;
- stale background context prevention after deletion;
- multi-device/self-host direction.

The important gap is restore semantics. The self-host restore script replaces the current `data` directory with backup `data`. The deletion audit is itself inside that tree. Restoring a pre-delete backup therefore rolls both user data and deletion state backward; no independent forget epoch/tombstone outside the backup was found.

**Verdict:** excellent lightweight companion reference; not a direct erasure authority.

## 6. Alicization — strong digital-life semantics, but another large bespoke core

After installing workspace dependencies and explicitly building its SQLite native binding, targeted tests produced:

- belief revision: 2/2 PASS;
- commitment ledger: 3/3 PASS;
- continuity closure authority: 4/4 PASS;
- action responsibility: 6/6 PASS;
- memory life-loop restart/recall soak: 1/1 PASS using Vitest thread pool.

**Target total: 16/16 LOCAL PASS.**

The first memory-soak attempt failed before executing tests because the Vitest fork worker did not start on Windows; rerunning with the thread pool executed the test and passed. This is treated as runner friction, not a product failure.

Alicization has serious implementations for SOUL/persona authority, belief revision, commitments, continuity, action responsibility, source withdrawal and long-running digital-life mechanics.

The problem is architectural economics: it is a large bespoke digital-life core. Replacing XiaoYu's bespoke core with another large bespoke core does not deliver the same reuse/maintenance collapse that N.E.K.O can potentially deliver, while N.E.K.O is stronger today on complete companion product surface, QQ/NapCat and the erasure/restore evidence that matters most.

**Verdict:** strongest semantic/reference challenger; do not merge runtimes. Re-evaluate only if the N.E.K.O acceptance spike fails a material digital-life behavior that Alicization already satisfies.

## 7. MIRA — strong personal-agent/runtime platform, memory truth is capability-dependent

MIRA is strong on:

- multi-user accounts;
- Personal/Shared/Guest channel identity;
- guardian/policy/tool layers;
- companion check-ins and quiet hours;
- automations;
- audit;
- sandbox direction;
- backup/restore.

But its memory-provider contract is explicit that capabilities differ by backend. The built-in provider declares:

- `supersede=true`;
- `temporal=false`;
- `graph=false`;
- `citations=false`;
- `can_assert_complete=false`.

Therefore “MIRA has memory” is not equivalent to “MIRA supplies XiaoYu temporal/provenance authority”.

Its restore is engineering-safe in a different sense: staged restore, version checks and a pre-restore safety copy. The final apply still swaps/imports old backed-up data. No independent cross-backup erasure generation comparable to N.E.K.O's forget fence was found.

Local Rust testing was **ENVIRONMENT BLOCKED** before product assertions because `whisper-rs-sys` requires `libclang` on this Windows host. Rust itself was installed under an isolated audit `RUSTUP_HOME/CARGO_HOME`; the system PATH was not modified.

**Verdict:** excellent Agent/security/control-plane reference, not current first-choice companion identity/memory mother project.

## 8. OpenCharaAgent — strong Agent + QQ/sandbox, Windows mismatch

Targeted suites covered memory, aspiration/tasks, provider swap, messaging, gateway boundaries, retry, sandbox and audit.

**Result: 148 LOCAL PASS / 5 LOCAL FAIL.**

The five failures were dominated by Windows/POSIX incompatibilities:

- POSIX `fcntl` / PTY assumptions;
- POSIX permission-mode assertions;
- path-separator expectations.

The project itself documents its strong OS jail path around macOS/Linux mechanisms. This is not the best fit for XiaoYu's Windows-first environment.

Its QQ implementation also treats a missing OneBot echo ACK as delivered after timeout, which is weaker than XiaoYu's desired UNKNOWN distinction for duplicate-sensitive effects.

**Verdict:** reuse/reference for Agent/task/sandbox/QQ ideas, not mother project.

## 9. Cremind — mature personal assistant, deletion is intentionally recoverable

Cremind is real and substantial: profile isolation, long-term memory, MCP, channels, automations and backup/restore are implemented.

However, source comments make its deletion philosophy incompatible with strict XiaoYu erasure:

- deleted profile working directories are kept/moved by default unless explicitly deleted;
- skills/on-disk profile data are intentionally retained in places so the profile can be recovered;
- backup options explicitly include “deleted profiles' kept folders” under the workspaces root;
- file restore semantics are documented as merge/overwrite: the archive overwrites files it carries and **deletes nothing**.

Cremind has tombstones in document indexing and hardware/tag ownership, but directed search found no general profile-memory erasure generation that survives restoring an older backup.

**Verdict:** strong personal-Agent platform/reference, not XiaoYu erasure authority.

## 10. Cyrene-Agent / AILIS / Companion Emergence

These remain useful but do not presently displace the leading set.

### Cyrene-Agent

Source confirms real DMAE, memory conflict/evidence machinery, QQ/NapCat + official QQ adapters, execution policy and Windows-oriented product work. It is a strong product/channel reference.

The downside is the same reuse-economics issue as Alicization: large custom Harness/memory/tool scheduling stacks would replace XiaoYu with another large custom stack, and no stronger cross-backup erasure proof than N.E.K.O was found.

### AILIS

AILIS has real tool contracts/approval and publishes evaluation artifacts. Historical disclosed numbers include:

- LongMemEval-S: 71.60%;
- LoCoMo: 24.69 token-F1;
- PersonaMem Balanced-140: 65.71%;
- Humanlike longitudinal score: 78.46/100, with 16 hard failures.

Its own docs correctly warn that these are historical independent runs, not a current unified-Agent reevaluation. This is useful evidence discipline, but it does not establish a stronger mother-project case than N.E.K.O.

### Companion Emergence

Source contains real Hebbian memory, forgetting/graveyard ordering, dreams, narrative/personality mechanisms and recovery. It remains a mechanism reference for inner-life/personality research, not the strongest complete Windows companion + QQ + Agent product base.

## 11. Same-criteria comparison

Legend:

- **P** = strong evidence/pass for the criterion
- **~** = partial / product-dependent
- **F** = observed fail against XiaoYu requirement
- **?** = not yet proven

| Criterion | N.E.K.O | Alicization | Miru | MIRA | Psycheros | OpenChara | Cremind |
|---|---:|---:|---:|---:|---:|---:|---:|
| Identity continuity | P | P | ~ | ~ | P | P | ~ |
| Private/group isolation | **P** | ~ | ? | P | ? | ~ | P |
| Provider privacy eligibility | F/GAP | ? | ? | ? | ? | ? | ? |
| Correction/current truth | **P** | P | P | ~ | ~ | ~ | ~ |
| Erasure closure | P | ? | ~ | ~ | ~ | ~ | F/~ |
| Old-backup no-resurrection | P | ? | F | F/~ | **F (local attack)** | ? | F/~ |
| In-flight erase race | P | ? | ? | ? | ? | ? | ? |
| QQ/NapCat identity scope | P/~ | ? | ? | ? | ? | P/~ | ? |
| Commitment continuity | **P/~** | P | P/~ | ~ | ~ | P | ~ |
| External ACK-loss semantics | ~ | ~ | ? | ~ | ? | F/~ | ? |
| Import/export + provenance | ~ | ~ | ~ | ~ | ~ | ~ | ~ |
| Complete companion E2E surface | **P** | ~ | ~ | ~ | ~ | ~ | ~ |

The table is deliberately conservative. “?” is not treated as failure; the point is to avoid promoting undocumented assumptions to authority.

## 12. Updated mother-project verdict

The expanded concrete audit **strengthens rather than weakens** the N.E.K.O-first hypothesis.

N.E.K.O is no longer selected because it has the longest feature list. It currently leads because it combines:

1. the broadest actual companion product surface;
2. Windows + QQ/NapCat relevance;
3. mature memory/persona/social/commitment machinery;
4. direct source mechanisms for scoped erase/restore safety;
5. **local passing evidence for the exact no-resurrection and in-flight erasure races that eliminate or weaken several alternatives**;
6. an extension surface that allows a small XiaoYu delta instead of a second full runtime.

This does **not** authorize production cutover. The next step remains a replacement spike against the full 12 acceptance criteria.

The permanent XiaoYu target remains small:

- provider disclosure/freshness admission;
- high-risk Effect UNKNOWN/reconciliation;
- XiaoYu persona/product policy;
- current-state importer;
- upstream pin/conformance gate;
- acceptance/regression tests.

Do not combine N.E.K.O + Alicization + Psycheros + Miru into a new meta-framework. Reuse one primary upstream and import only narrowly proven mechanisms when the primary upstream has a material gap.
