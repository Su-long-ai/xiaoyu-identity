# XiaoYu — ChatGPT-first research execution and storage (E0 draft)

This file documents the tested workflow, **not** an E1/E2 governance-policy override. No change to the production identity, release process, existing roles, lease ownership, or auditor authority is implied.

## Execution tiers

1. Prefer the current ChatGPT Python sandbox for short, privacy-safe, deterministic CPU experiments, using installed dependencies.
2. When necessary, attempt safe dependency installation or compatible import locally in that sandbox. Verify import and runtime, not just pip exit status.
3. If execution remains impossible due to dependencies, network, Python version, workload size or time limits, run an isolated, bounded GitHub Actions job. Use a separate branch, scoped permissions, fixed max duration and no uncontrolled triggers.
4. No local MCP or Codex. No unapproved paid model API, secrets, real private identity data or production writes.

## Durable research evidence

- Commit reproducible scripts, configuration, fixed seeds, code provenance, concise JSON/CSV metrics, failure examples and reports to an isolated GitHub branch.
- Record source commit and file hash, exact runner and Python/dependency versions, data origin, command, success/failure, limitations, and evidence tier.
- Keep large/temporary outputs in GitHub Actions Artifacts **only if needed**; these expire and are not the sole source of scientific evidence. Avoid storing credentials and private user data.
- Failed and inconclusive runs remain valid evidence. Do not silently promote E0 to E1/E2/E3.
- Before declaring success, fetch committed files and verify their integrity. A GitHub write alone is not enough.

## Tested example

```bash
python -m experiments.cloud_e2e_smoke --json-out results.json
```

- Code: `experiments/cloud_e2e_smoke.py`
- Result: `evidence/cloud_e2e/20261101/results.json`
- Report: `evidence/cloud_e2e/20261101/report.md`

The test ran on ChatGPT Python using the real `send_guard.py` source and synthetic SQLite data. Actions fallback was not needed for this case.
