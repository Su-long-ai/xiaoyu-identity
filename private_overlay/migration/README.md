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
