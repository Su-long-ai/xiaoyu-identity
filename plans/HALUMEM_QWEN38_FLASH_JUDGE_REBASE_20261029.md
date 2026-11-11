# HaluMem Judge qwen3.8-flash Rebase ? 2026-10-29

Status: PREFREEZE REBASE COMPLETE / FRESH CALIBRATION + NEW INDEPENDENT RE-AUDIT REQUIRED

## Decision
The Owner selected Alibaba Model Studio qwen3.8-flash as the HaluMem confirmatory judge before final freeze.

Frozen candidate:
- provider: Alibaba Model Studio
- model: qwen3.8-flash
- API protocol: OpenAI-compatible Chat Completions
- temperature: 0
- max_tokens: 16384
- enable_thinking: false
- credential env: DASHSCOPE_API_KEY
- optional base URL override: DASHSCOPE_BASE_URL
- default base URL: https://dashscope.aliyuncs.com/compatible-mode/v1

## Scientific boundary
- Official HaluMem prompt/code bytes remain the scoring reference.
- GPT-4o and qwen3.8-max-0902 judge results/READY scopes are historical only.
- No prior judge calibration receipt may be reused for qwen3.8-flash.
- Fresh Flash calibration must pass 12/12 before any HaluMem confirmatory gold scoring.
- External GPT-4o leaderboard values are descriptive only.
- No runtime judge substitution is allowed after the Flash binding is frozen.
- Untouched confirmatory exposure remains zero during this rebase.

## Operational boundary
No secret is stored in the repository. DASHSCOPE_API_KEY remains absent until the Owner configures it.
No confirmatory call is authorized by this rebase.

## Connectivity verification
- Windows User environment now contains `DASHSCOPE_API_KEY`; secret value was never printed or stored in the project.
- A synthetic non-confirmatory connectivity request to `qwen3.8-flash` returned exactly `OK`.
- Usage: 29 prompt tokens + 1 completion token = 30 total tokens.
- This was connectivity-only, not calibration or scientific evidence, and read no confirmatory record.
- Untouched confirmatory exposure remains LongMemEval=0 / HaluMem=0.
- The current Operator supervisor predates the user-env update, so final execution must either inherit/refetch the user environment or restart before runtime credential checks; this is operational only and does not relax any E2 gate.
