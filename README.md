# XiaoYu on N.E.K.O

XiaoYu 是建立在 [Project N.E.K.O](https://github.com/Project-N-E-K-O/N.E.K.O) 上的长期伴侣产品层。

**N.E.K.O 是唯一 Companion Kernel。** XiaoYu 不重新实现桌面 runtime、插件框架、模型网关、记忆引擎或通用 Agent runtime；它主要提供身份/关系连续性、隐私与 audience policy、interruptibility、provider trust、XiaoYu-specific interaction policy，以及少量经过机器验证的兼容补丁。

> Repository status: public source repository.  
> Product development branch: `private/neko-overlay-v1`.  
> `main` is maintained as the public green mirror of the product branch.  
> Stable release manifest: `private_overlay/release/NEKO_OVERLAY_V1_FINAL.json`.

## Current stable product

The stable XiaoYu/N.E.K.O product currently pins:

- N.E.K.O: `c3fc33ff0d32e4a79fd905d1add22d45725071f5`
- QQ surface: `zhaijiunknow/n.e.k.o_plugin_qq_auto_reply@54acf36`
- Official N.E.K.O desktop host
- 14 ordered managed N.E.K.O patches
- 1 admitted private runtime plugin: `xiaoyu_interaction_policy`
- 25/25 stable acceptance cases closed

Stable product scope includes:

- desktop text + native VRM companion
- physical microphone realtime voice and paired TTS
- Qwen clone voice with CosyVoice fallback
- rapid character/model-switch recovery
- screenshot/vision through N.E.K.O native surfaces
- identity/persona/memory continuity and erasure/no-resurrection checks
- natural-language quiet/resume controls with native execution authority
- ActivityWatch-backed bounded recent-app recall
- final-delivery interruptibility checks for focused work, fullscreen, presentation and gaming
- QQ private/trusted-group continuity
- NekoClaw task execution with effect/outbox/receipt correctness
- no-blind-retry behavior for uncertain plugin effects
- runtime self-heal for admitted autostart plugins

Experimental restart-continuity work remains under `private_overlay/candidates/` until its product promotion gates are satisfied.

## Architecture boundary

The frozen direction is intentionally simple:

```text
N.E.K.O
  ├─ desktop / VRM / voice
  ├─ model & provider runtime
  ├─ Plugin SDK
  ├─ memory/persona storage
  ├─ NekoClaw / MCP / task execution
  └─ native lifecycle / permissions
        │
        ▼
XiaoYu overlay
  ├─ identity / relationship policy
  ├─ privacy / audience policy
  ├─ interruptibility policy
  ├─ provider trust policy
  ├─ interaction-policy plugin
  └─ narrow compatibility patches
```

Forbidden duplicate authorities include a second plugin host, model gateway, vector store, memory runtime, generic Agent runtime, HTTP pool, credential store, permission database, or process daemon.

## Reuse-first development

Every long-lived implementation unit follows the machine-enforced reuse hierarchy:

```text
L0 authority
→ current N.E.K.O pin
→ N.E.K.O upstream / native extension seams
→ existing pinned external components
→ broader mature external ecosystem
→ thin integration
→ private implementation
```

Core patches are the last option and require a reproduced native gap, reuse evidence, acceptance evidence and a retirement condition.

The shared GitHub Actions gate runs for:

- `main`
- `private/neko-overlay-v1`
- `agent/**`
- pull requests targeting `main` or the product branch

The gate includes public-secret scanning, reuse-first enforcement, frozen-architecture enforcement, plugin admission, PowerShell parsing, Companion regressions, native/managed Execution regressions, QQ surface checks and release evidence.

## Repository privacy

This repository is public **source code**, not the user's private XiaoYu state.

Local identity, chat history, runtime state, credentials, exports and private backups are excluded from source control. Provider configuration stores environment-variable names such as `DEEPSEEK_API_KEY`, not secret values.

Public pushes are additionally checked by GitHub secret scanning and the repository's Gitleaks machine gate.

Do not commit:

- `.env*`
- API tokens or passwords
- `identity/` runtime data
- local databases
- exported identity archives
- runtime state directories
- private conversation/evaluation material

## Local product entrypoints

The maintained Windows product entrypoints live under `private_overlay/tools/`:

- `start_xiaoyu_oneclick.ps1` — normal desktop launch path
- `start_xiaoyu.ps1` — N.E.K.O source/runtime launch path
- `run_checks.ps1` — local product verification
- `check_release_readiness.py` — stable release consistency gate

The one-click launcher reuses N.E.K.O's native launcher record and lifecycle authority. It does not own a second backend supervisor.

The repository intentionally does not bundle private runtime state or third-party binaries. A maintainer environment must provide the pinned N.E.K.O checkout, official desktop host, local storage root and any external provider credentials through environment variables.

## Source layout

```text
private_overlay/
  governance/    architecture, reuse and admission policy
  patches/       ordered managed N.E.K.O compatibility patches
  plugins/       admitted XiaoYu-specific runtime plugins
  candidates/    unpromoted experiments / acceptance-gap implementations
  evals/         acceptance and machine evidence
  tools/         launch, health, migration and verification tooling
  tests/         overlay/product contract regressions
  release/       stable release manifest
```

The historical standalone XiaoYu research code remains in this repository for provenance and migration evidence, but it is **not the current Companion runtime authority**.

## Release discipline

A change is not considered product-ready merely because it works locally.

Normal promotion requires:

1. reuse evidence;
2. architecture/admission gates;
3. relevant native and product regressions;
4. public secret-leak gate;
5. a green product-branch run;
6. explicit stable/candidate boundary preservation.

The stable manifest is the release authority for the currently supported XiaoYu/N.E.K.O product state.
