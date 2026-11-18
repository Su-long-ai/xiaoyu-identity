# Legacy XiaoYu -> N.E.K.O migration policy

The migration is intentionally narrow.

Current observed legacy canonical state:
- one persona version;
- four memories, all marked bootstrap/bootstrap;
- fifteen events, including twelve conversation events and three migration/system events;
- the later product-memory bridge and retrieval index contain no product claims/memories.

Policy:
- migrate the current canonical XiaoYu persona through N.E.K.O's supported external-memory preview/commit path;
- do not import bootstrap memories as user facts;
- do not transform raw legacy conversation history into long-term facts automatically;
- preserve the old database read-only as provenance/history during cutover;
- generated SOUL.md/MEMORY.md and manifests live only under the local state directory, outside Git;
- preview must pass before any commit is enabled;
- actual commit must target an isolated/test N.E.K.O storage root first, then the private product root after acceptance.

The exporter accepts only memory statuses active/confirmed. Unknown or bootstrap lifecycle states fail closed into the excluded list.

## Isolated commit and continuity proof

The isolated storage root is `D:\xiaoyu_private_overlay_state\neko-sandbox`.

`commit_neko_import.py` exercises N.E.K.O's real external-import parser, persona fusion persistence, fingerprint/idempotency logic and PersonaManager storage. For the isolated privacy-first migration proof only, the fusion model transport is replaced with a deterministic local preserve function. This prevents private `SOUL.md` content from being sent to an unclassified model provider before the provider-privacy acceptance case is complete.

Useful commands, run with the audited N.E.K.O virtualenv:

```powershell
& D:\xiaoyu_external_audit\N.E.K.O\.venv\Scripts\python.exe private_overlay\migration\commit_neko_import.py
& D:\xiaoyu_external_audit\N.E.K.O\.venv\Scripts\python.exe private_overlay\migration\commit_neko_import.py --verify-only
& D:\xiaoyu_external_audit\N.E.K.O\.venv\Scripts\python.exe private_overlay\evals\verify_identity_model_swap.py
```

The first isolated commit is not the production cutover. Production import remains blocked on live-model/provider privacy admission and final product E2E.
