# XiaoYu Long-Term Hardening & Operations

**Date:** 2026-11-18  
**Scope:** secrets, local encryption, backups, migrations, updates, dependency/plugin trust, crash consistency, resource budgets, recovery and release hygiene.

---

# 1. Secret storage

## Recommendation

Do not store provider keys in:

- provider.json
- identity DB
- memory
- export bundles
- logs

For Windows product deployment, prefer:

1. Windows Credential Manager
2. DPAPI-protected local storage
3. environment variable only as compatibility fallback

Microsoft's current guidance recommends Windows Credential Manager for credentials and DPAPI for secrets that must be persisted locally.

## 1.0

Keep current environment-variable support, but add a credential-store adapter.

## 1.x

Make Credential Manager the default UX:

```
Provider settings
→ paste key once
→ write to OS vault
→ config stores only credential reference
```

---

# 2. Database encryption

SQLCipher is a mature BSD-licensed SQLite fork with AES encryption, tamper detection and key derivation.

However, changing the authoritative identity DB engine is a migration-risk event.

## Decision

**Do not make SQLCipher a 1.0 blocker.**

Reasons:

- current SQLite authority already works
- DB format migration needs recovery testing
- key loss can make identity unrecoverable
- encrypted backup/export semantics must be designed first
- Python packaging adds another native component

## 1.x option

Offer encrypted-at-rest identity as a migration:

```
plain SQLite
→ verified backup
→ SQLCipher export
→ integrity check
→ reopen check
→ rollback path
```

Store the DB key in Windows Credential Manager/DPAPI, never next to the database.

---

# 3. Backup correctness

Never back up a live SQLite DB using a blind file copy.

Use SQLite's Online Backup API or another SQLite-consistent snapshot method.

The Online Backup API creates a transactionally consistent snapshot while allowing the source database to continue operating.

## Backup package

```
identity.sqlite3 snapshot
manifest.json
identity metadata
schema version
checksums
optional memory export
optional encrypted archive
```

## Required restore test

Every release must test:

```
create identity
→ write representative state
→ online backup
→ restore to empty directory
→ reopen
→ verify identity id
→ verify memory/provenance
→ verify purpose state
```

---

# 4. Backup policy

Suggested product defaults:

- automatic rolling local backups
- before schema migration
- before identity import
- before destructive memory operation
- manual export on demand

Retention should be bounded and visible.

A deletion request must clearly disclose whether old backups still contain the deleted information.

---

# 5. Schema migrations

Identity schema migration is part of product correctness.

Each migration needs:

```
from_version
to_version
preconditions
backup_required
forward migration
verification
rollback/recovery instructions
```

Rules:

- never silently rewrite original provenance
- never infer new historical facts during a storage migration
- derived projections may be rebuilt
- migrations must be idempotent or version-guarded
- crash midway must leave a recoverable state

---

# 6. Derived-data rebuildability

The following should be rebuildable from authority whenever possible:

- semantic embeddings
- FTS index
- profile projection
- temporal current-state projection
- memory summaries
- graph projection
- skill search index

The authoritative ledger should not depend on a particular embedding model.

This reduces migration risk and makes provider/model replacement practical.

---

# 7. Software update trust

If XiaoYu eventually self-updates, update authenticity must be verified before execution.

Useful mature building blocks:

- Sigstore for artifact signing/verification
- TUF for secure update metadata, rollback/freeze protection and repository trust

## Decision

### 1.0 private project
Manual/git-controlled updates are sufficient.

### 1.x distributed product
Sign release artifacts and verify them before install.

### 2.0 public auto-update
Adopt TUF-style update metadata or a mature updater that provides equivalent rollback/freeze protections.

Do not invent a custom updater signature protocol.

---

# 8. Plugin / MCP supply chain

Every installed external capability must be treated as software supply-chain input.

Track:

```
plugin_id
source_repo
version
artifact_hash
license
permissions
installed_at
last_verified
update_policy
```

Rules:

- no unpinned auto-updates for high-privilege plugins
- verify source/version before privilege elevation
- re-evaluate permissions when a plugin changes
- a plugin update cannot silently inherit old trust if its capabilities expand
- keep third-party license inventory

---

# 9. Model artifact trust

Local ASR/TTS/vision models are also dependencies.

Maintain:

```
model_id
source
revision/hash
license
size
runtime
verified_at
```

Prefer:

- safetensors where available
- pinned revisions
- known model cards
- explicit license record

Treat arbitrary pickle-based checkpoints with more caution.

---

# 10. Crash consistency for external effects

External effects require a write-ahead intent/receipt pattern.

Example:

```
persist intent
→ execute external action
→ persist external receipt
→ verify state
→ mark complete
```

Recovery logic:

- if no execution attempt: execute
- if attempt but no receipt: query target state before retry
- if receipt exists: verify
- never blindly replay a non-idempotent effect

---

# 11. Idempotency

Generate one logical idempotency key per external effect.

Reuse it across retries.

Examples:

- QQ send
- social post
- file mutation
- cloud API mutation
- booking/submission

Where the upstream API has no idempotency support, use local receipts plus target-state inspection.

---

# 12. Process supervision

Long-lived XiaoYu components should have explicit ownership:

```
Core
Live2D
Vision sidecar
Voice sidecar
QQ/NapCat
optional durable worker
```

For each process:

- startup dependency
- health check
- restart policy
- shutdown order
- resource budget
- log location

Avoid orphaned browser/node/GPU workers.

---

# 13. Resource budgets

Define budgets as product SLOs, not one-off observations.

Track:

- idle RAM
- active turn peak RAM
- VRAM
- CPU idle
- CPU watch mode
- first response latency
- hot response latency
- vision calls/hour
- TTS latency
- API spend/day

Provide modes:

```
ECO
BALANCED
FULL
```

Possible controls:

- retriever idle TTL
- vision FPS
- watch sensitivity
- local model residency
- ASR/TTS model
- proactive heartbeat
- background consolidation frequency

---

# 14. Graceful degradation

XiaoYu should expose capability state, not fail mysteriously.

Example:

```
Text API unavailable
→ memory/UI/reminders still work

Vision provider unavailable
→ text companion still works

GPU unavailable
→ CPU/lightweight path or feature disabled

QQ unavailable
→ desktop remains usable
```

Every optional capability has:

- READY
- DEGRADED
- OFF
- ERROR

with a human-readable reason.

---

# 15. Offline behavior

Offline does not have to mean a full local LLM.

Minimum offline product:

- open identity
- browse/edit memory
- reminders/purpose engine
- backup/export
- local tools that do not need network
- desktop pet
- status

Optional small local model can be added later.

Do not make an inferior local model mandatory just to claim “offline AI.”

---

# 16. Release health

Before release:

- schema migration tests
- backup/restore
- clean install
- upgrade from previous release
- no secret scan findings
- dependency/license inventory
- external-effect recovery tests
- permission negative tests
- crash during DB write
- crash after external action
- provider fallback
- GPU worker cleanup
- visibility of capture/mic state

---

# 17. Privacy controls

Final settings need explicit controls for:

## Memory
- inspect
- correct
- archive
- delete
- source

## Perception
- screen capture status
- microphone status
- camera status
- retention

## Provider disclosure
- what data class may leave device
- which provider receives it

## Export
- what is included
- whether secrets are excluded
- encryption choice

---

# 18. Logging hygiene

Logs must not contain by default:

- API keys
- access tokens
- full private memory contents
- raw microphone audio
- raw screen images
- unnecessary user message bodies

Prefer IDs/hashes and bounded diagnostic excerpts.

Allow a temporary explicit debug mode when full payload logging is truly needed.

---

# 19. Release signing

For future packaged releases:

- build reproducibly where practical
- sign release artifacts
- verify before install/update
- publish checksums
- preserve dependency lockfiles

Sigstore is a strong candidate because its Python tooling supports Python 3.11+ and artifact verification.

---

# 20. Hardening priority

## 1.0

- secret exclusion
- consistent SQLite backup
- restore test
- schema migration discipline
- external effect receipts
- process cleanup
- health status
- resource measurement
- privacy indicators

## 1.x

- Windows Credential Manager integration
- optional SQLCipher migration
- signed releases
- plugin/model inventory
- structured operational telemetry
- automatic rolling backup
- provider disclosure UI

## 2.0

- secure auto-update framework
- encrypted cross-device replication
- remote recovery
- household/multi-user key model

---

# Final principle

> The identity database is more valuable than any single model installation.

XiaoYu must be engineered so that models, embeddings, voices, vision systems, plugins and devices can all be replaced without losing the identity, provenance, memory history or verified skills that make XiaoYu XiaoYu.
