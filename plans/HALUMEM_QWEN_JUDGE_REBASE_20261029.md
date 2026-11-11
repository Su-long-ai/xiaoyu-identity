# HaluMem Judge Qwen Rebase — 2026-10-29

Status: PREFREEZE REBASE COMPLETE / NEW INDEPENDENT RE-AUDIT REQUIRED

## Decision
The owner cannot use OpenAI API. The HaluMem confirmatory runtime judge is therefore re-based before final freeze from OpenAI GPT-4o to Alibaba Cloud Model Studio Qwen.

Frozen candidate:
- provider: alibaba_model_studio
- model: qwen3.8-max-0902
- API protocol: OpenAI-compatible Chat Completions
- temperature: 0
- max_tokens: 16384
- enable_thinking: false
- credential env: DASHSCOPE_API_KEY
- optional base URL override: DASHSCOPE_BASE_URL
- default base URL: https://dashscope.aliyuncs.com/compatible-mode/v1

## Scientific boundary
- HaluMem official evaluation/eval_tools prompt bytes remain retained as reference.
- The old GPT-4o final-v2 READY re-audit is historical and does not approve the new Qwen bytes.
- External GPT-4o leaderboard/median values are descriptive only and are NOT formal promotion gates under Qwen judging.
- Qwen calibration remains mandatory 12/12 before confirmatory gold scoring.
- No model substitution is allowed after the new Qwen binding is frozen.
- Untouched confirmatory exposure during the rebase remains 0.

## Validation
- judge binding unit tests: 5/5 PASS
- HaluMem confirmatory runner offline tests: 11/11 PASS
- Python compile checks: PASS
- prefreeze doctor: healthy=true
- confirmatory execution allowed: false
- new exact re-audit manifest: governance/E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.json
- current re-audit manifest SHA256: 18ac76f9b3f81ef4f5fcb24aa0bb8ef2fd1fcba1c5ea1f81ada40ed633c84344

## Remaining gates
1. Existing Independent Auditor must re-audit the new exact Qwen package.
2. Lead may create a separate final confirmatory freeze only after that READY decision.
3. DASHSCOPE_API_KEY is required operationally before Qwen calibration/gold scoring.
4. Calibration must pass 12/12 before HaluMem gold scoring.

Do not use the prior GPT-4o READY_FOR_CONFIRMATORY_FREEZE decision to authorize the Qwen package.
