# XiaoYu ChatGPT Cloud E2E Smoke — 2026-11-01

**Status:** E0 engineering smoke (completed); **NOT** E1 reviewed, E2 scientific validation, or E3 product release.

## Question

Can ChatGPT fetch exact source from the private GitHub repository, execute a real project-code test in its own ephemeral Python environment, archive runnable code and test evidence into an isolated GitHub branch, and read back/verifiably identify the archived material without local MCP or Codex?

## Code and environment

- Repository: `Su-long-ai/xiaoyu-identity`.
- Main commit at start: `781394b9d70795f0a289c7c84ca643b141d21416`.
- Tested production source: `send_guard.py`, Git blob SHA-1 `6595e36cfce9d0e7907271164785b062176c5053`.
- Experiment file: `experiments/cloud_e2e_smoke.py`; SHA-256 `7de70e8fa1b95dff6e463411af2e05fc710f8ce69292069874f86fcbddb70706`.
- Runner: ChatGPT ephemeral Linux Python 3.13.5; standard library only; no pip install needed.
- Data: freshly created, ephemeral synthetic SQLite databases; no `identity/` or personal conversation data accessed; zero paid LLM calls.
- Invocation from repository root: `python -m experiments.cloud_e2e_smoke --json-out results.json`. Directly invoking the nested script without a configured `PYTHONPATH` is not the supported entry point.

The source content copied into ChatGPT's Python runtime was checked against the GitHub Git-blob hash before tests. LF/CRLF normalization was taken into account when comparing the repository's original Git blob.

## Observed results

- 12 tests run; **12 passed, 0 failed, 0 skipped**.
- Positive authority/freshness baseline.
- Fail-closed cases: changed memory generation, changed memory text, archived memory, inactive provenance source, assistant-authority inversion, multiple claims per source, active user-user conflict, and stale generation before dispatch.
- Dispatch callback releases DB locks; valid assistant event persists; stale or oversize replies are rejected with expected rollback/no extra event.
- Result JSON: `evidence/cloud_e2e/20261101/results.json`.
- Result JSON SHA-256: `309552ab838f1fb672e85e3acf65eec5b553da7b08185cf2c40f3fcfcbe69701`.

## Decision

**Execution-and-storage path validated at E0:** fetch private GitHub source -> verify exact source -> execute on ChatGPT Python -> save versioned experiment code and JSON evidence to a separate branch -> verify via GitHub read-back.

Because the ChatGPT Python execution succeeded, the fallback GitHub Actions runner was **not used** in this experiment. A distinct prior workflow on branch `experiment/actions-transformers-20261101` demonstrated automated Actions execution and installation of Transformers. It is not evidence of this smoke test.

## Limits / pending gate

- This is synthetic component smoke coverage, **not** a baseline-vs-candidate accuracy study, model evaluation, governance submission, or independent auditor sign-off.
- Runner storage is temporary; durable records are only the committed code, JSON and report.
- GitHub branch is isolated and not merged to `main`.
- No new research lease was claimed; no claim is made that existing `governance/control.py` audit protocol was satisfied.
- Broader product tests, scientific generalization and independent replication remain pending.
