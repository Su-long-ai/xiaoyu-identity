# ADR-011 — Keep send-generation freshness as supporting P2 E1

Status: Accepted scope decision
Date: 2026-10-28

R31 remains the P1 admissibility gate: forbidden evidence is filtered and atomically serialized before model-visible context. sub-3d041cb84eb8419d is ACCEPT_E1 for the stronger post-pack document-generation freshness boundary through provider send.

Independent audit reproduced the primary stale-document protection, but found two nonblocking P2 gaps: the token does not bind the canonical XiaoYu request principal/conversation/workspace/mode/recipient, and multi-instance initialization transiently drops/recreates generation triggers. No lost generation increments or stale-send bypass was observed in the concurrency probes.

Therefore this E1 is retained as supporting hardening evidence, not promoted into a new P1 release blocker and not described as end-to-end request isolation.
