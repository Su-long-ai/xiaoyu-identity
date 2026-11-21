# XiaoYu Private Overlay

This directory is the permanent private customization layer on top of Project N.E.K.O.

Principles:
- N.E.K.O remains the product chassis and the single runtime authority for memory, persona storage, persona evolution/evidence promotion, tasks, voice/vision and plugin/tool execution.
- QQ is reused through the pinned external N.E.K.O QQ plugin and N.E.K.O OneBot/QQ connectors.
- XiaoYu owns only private identity constraints/content, provider trust policy, conformance tests, one-time legacy migration and narrowly-scoped adapters proven necessary by a failing product test.
- Growth mechanics are not implemented in the overlay. N.E.K.O native evidence/reflection/persona-promotion/correction mechanisms remain authoritative; XiaoYu only declares which identity dimensions may or may not change.
- Private runtime plugins are exception-only. The current xiaoyu_interaction_policy adapter exists because a live object-less quiet request was obeyed only conversationally while native proactive delivery stayed enabled; it performs semantic intent mediation only and delegates hard execution to N.E.K.O's built-in proactive_controller.
- Do not modify N.E.K.O core unless a wanted feature cannot be expressed as configuration, external component, plugin or adapter.
- Core patches live only in patches/ and are explicitly counted. The current budget is eight narrow patches, each admitted only after a reproduced live product gap and tied to acceptance evidence.
- Never dual-write memory/identity authorities.
- Private customization is optimized for this user, not for upstream generality.

Development layout:
- N.E.K.O checkout: D:\xiaoyu_external_audit\N.E.K.O
- private overlay checkout: this repository
- isolated private state: D:\xiaoyu_private_overlay_state
- pinned external QQ plugin: private_overlay/QQ_PLUGIN_UPSTREAM.lock.json
- pinned official desktop host: private_overlay/DESKTOP_SHELL.lock.json

Startup:
- Run tools/setup_local.ps1 after changing pinned external components.
- Use tools/start_xiaoyu.ps1 for backend-only/private-runtime startup. It verifies local pins, completes N.E.K.O's native first-run storage selection when needed, verifies or upgrades the private interaction plugin through N.E.K.O's own package/install transaction, runs the privacy/authority preflight, sets the isolated XiaoYu storage root, then launches N.E.K.O directly. `-PreflightOnly` never upgrades the plugin and fails closed if the installed executable copy is stale.
- Use tools/start_xiaoyu_oneclick.ps1 for normal daily use. It waits until the XiaoYu main/memory/agent services are healthy, then launches the pinned official N.E.K.O desktop host so the existing XiaoYu backend is shown as a desktop pet instead of opening a browser.
- Use tools/start_xiaoyu.ps1 -PreflightOnly to validate the backend launch path without starting the UI.
- Run `tools/install_xiaoyu_shortcuts.ps1` after moving or re-cloning the overlay. It recreates the `小鱼 XiaoYu` one-click launcher, the debug shortcut for `http://127.0.0.1:48911/`, and the local API-cost shortcut from the current checkout path instead of preserving stale workspace paths.

The desired steady state is data + policy + conformance around N.E.K.O, not a second XiaoYu runtime.

## Private interaction-policy adapter

plugins/xiaoyu_interaction_policy is a narrow private plugin, not a second agent/runtime authority. It consumes the N.E.K.O user-message bus, asks the configured Qwen classifier for structured proactive quiet/resume, reply-output quiet/resume and autonomous-vision intent, and delegates hard proactive state changes to the built-in proactive_controller. XiaoYu v0.6 has one durable reply-output authority: quiet. When quiet is active, the opt-in N.E.K.O gate suppresses the whole assistant reply before the UI/TTS split; when a reply is admitted, the same reply path keeps text paired with TTS. The legacy speech_muted field is compatibility-only and normalized to false, so policy can no longer create a "text visible but voice muted" state. Outside quiet mode the plugin uses a cheap lexical candidate prefilter to avoid an extra model call on ordinary chat; while the hard quiet latch is active every non-empty owner message is semantically checked so novel natural-language resume wording is not trapped behind a finite keyword list. The proactive latch changes only N.E.K.O's proactiveChatEnabled master switch, preserving the owner's custom per-source proactive settings and user-owned privacy switches. Exact short commands such as 别说话 / 可以说话了 have a synchronous current-turn fast path solely to close classifier latency; the plugin remains the persistent semantic authority. Its persisted state contains only control state, timestamps and user-event IDs for deduplication; it does not persist user message text. Recent desktop-activity recall delegates to ActivityWatch as the external local authority. ActivityWatch window-title collection is disabled (exclude_title=true), and XiaoYu uses only a read-only local REST/query adapter that returns application names, AFK-filtered durations and explicit coverage; it does not maintain a second activity timeline or return titles/URLs/screenshots to the model. Missing coverage remains UNKNOWN rather than being narrated as inactivity. N.E.K.O's User Plugin relay is enabled while the Agent master/analyzer, Computer Use and Browser Use remain disabled.


## Managed core patches

Eight narrow N.E.K.O patches are currently managed. The first fixes the proactive auto-start idle gate: an internally started text session must not impersonate fresh user activity and block its own proactive delivery. The second exposes the already-native microphone runtime through the active Full Chat toolbar because the compatibility mic control is hidden and the avatar floating control was absent in the live XiaoYu surface. The third keeps Qwen3.8 realtime voice on the provider's reliable server VAD path after live E2E evidence showed semantic VAD could accept audio without emitting speech/transcription events. The fourth publishes the existing native realtime loud-PCM activity signal before the bounded ingress queue so proactive delivery yields to a speaking user even when the worker is backpressured; it does not change provider audio, VAD, DSP, transcripts or queue limits. The fifth preserves the latest requested character during an in-flight avatar switch and force-replays it after completion/failure, preventing rapid A→B→A switching from leaving the backend on A while the frontend avatar was torn down. The sixth is an opt-in whole-reply output gate: it reuses the isolated XiaoYu quiet state and admits or rejects the reply before N.E.K.O splits it into UI text and TTS, making policy-induced "text without voice" impossible while leaving the native text and TTS pipelines intact after admission. The seventh is a generic opt-in first-round provider-native tool-routing bridge: after repeated product probes prove auto-selection unreliable, the private launcher supplies one registered tool name, a conservative regex, and an optional first-round reasoning override. N.E.K.O forwards the provider's normal tool_choice (Qwen3.8 uses reasoning_effort=none for that first forced round) and immediately restores the prior tool/reasoning settings afterward; it does not pre-execute the tool locally and contains no XiaoYu-specific wording. The eighth exposes Alibaba Qwen as a first-class paired clone provider while reusing N.E.K.O's existing voice storage/picker and native Qwen3.8 Omni transport; ordinary TTS/preview use the provider-native Qwen-Audio path and realtime uses the paired Omni clone. None introduces a parallel runtime. All are replayed by tools/setup_local.ps1, covered by regression evidence, and should be removed when a future pinned N.E.K.O version includes equivalent behavior.

## Release readiness

tools/run_checks.ps1 ends with a fail-closed release gate. Every case in evals/acceptance_matrix.json must be in a PASS state and point to an existing evidence file. Any case that regresses to pending/deferred/partial/blocked/not-yet-ready blocks the release check.


## Local API cost dashboard

`tools/open_api_cost.cmd` refreshes and opens a local read-only cost report from N.E.K.O's native `config/token_usage.json`. It does not add another usage tracker or call an API. Reference prices and optional daily/monthly warning thresholds live in `tools/api_prices.json`; `null` leaves a threshold disabled.

The bundled rates were rechecked against Alibaba Cloud Model Studio's public pricing pages on 2026-11-20 for the Beijing endpoint used by XiaoYu. They are reference rates rather than an account invoice. The report keeps genuinely unpriced calls separate and uses conservative ranges where N.E.K.O stores less billing detail than the provider: tiered historical aggregates, mixed-modality Realtime input/output tokens, and TTS character counts (N.E.K.O stores Python character length while Bailian bills CJK ideographs as two characters). Provider billing remains authoritative. Budget warnings are informational and never stop requests.

## Reuse-first gate

Every new private runtime plugin or managed N.E.K.O core patch must first have an approved entry in `governance/reuse_reviews.json`. The review records the N.E.K.O native/upstream and mature external candidates considered, supporting evidence, and why reuse alone is insufficient when a thin adapter or private implementation remains. `tools/check_reuse_first.py` is fail-closed and runs inside `tools/run_checks.ps1`; an unreviewed managed patch/plugin or an unmanaged patch file blocks the checks. If a reusable solution later becomes viable, the policy prefers replacing/deleting private code rather than keeping it because it already exists.
