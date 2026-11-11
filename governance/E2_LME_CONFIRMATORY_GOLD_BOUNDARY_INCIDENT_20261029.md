# E2 LongMemEval Confirmatory Gold-Boundary Incident — 2026-10-29

Status: **FAIL-CLOSED / LME CONFIRMATORY SCIENTIFIC VALIDITY SUSPENDED**

## Incident

Before any LongMemEval confirmatory prediction seal existed, a temporary local inspection command was launched to inspect the structure of an already-exposed pilot record. The command was incorrectly written as:

`json.loads(p.read_text("utf-8"))[0]`

against the full 500-record LongMemEval-S JSON file.

Because `json.loads` first deserializes the entire top-level dataset before indexing element 0, the local process necessarily materialized all records, including confirmatory-only evaluator/gold fields, in process memory.

Operator task:
- task_id: `20261029-211956-7e56f0b9`
- exit_code reported by cancel probe: 0 (task had already exited)

The task stdout was **not retrieved after recognizing the mistake**, and no confirmatory answer/outcome was intentionally inspected, copied into project artifacts, or used to tune a model/prompt/threshold. Nevertheless, the frozen anti-peeking contract is defined at the read/materialization boundary, not merely at whether the human/model saw the values.

## Immediate containment

- No LongMemEval confirmatory `execute` call was started.
- No LongMemEval confirmatory provider call was started by this workflow.
- No LongMemEval prediction seal exists from this workflow.
- No HaluMem confirmatory prediction/gold/judge stage was started by this workflow.
- The invalid full-dataset inspection output will not be retrieved or used.
- Further LME confirmatory execution is suspended until the project applies an explicit contamination/recovery decision.

## Scientific interpretation

The frozen rule requires LongMemEval prediction to be generated and sealed before gold/evaluator fields are read. The local full-file deserialization violated that rule even though the command only intended to print pilot-record structural keys and no confirmatory outcome was subsequently retrieved.

Therefore the current frozen LongMemEval confirmatory holdout must not be represented as untouched/valid on the basis of this execution session.

## Required next action

Use existing project contamination/invalidation/recovery policy if one exists. Do not silently substitute holdout cases and do not continue LME confirmatory as if the boundary remained intact.

HaluMem must be evaluated separately: its holdout files were not touched by this incident, but whether its confirmatory track can continue independently must be decided by the frozen protocol/governance rather than assumed here.
