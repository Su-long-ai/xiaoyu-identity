# XiaoYu Private Overlay

This directory is the permanent private customization layer on top of Project N.E.K.O.

Principles:
- N.E.K.O remains the product chassis and the single runtime authority for memory, persona storage, persona evolution/evidence promotion, tasks, voice/vision and plugin/tool execution.
- QQ is reused through the pinned external N.E.K.O QQ plugin and N.E.K.O OneBot/QQ connectors.
- XiaoYu owns only private identity constraints/content, provider trust policy, conformance tests, one-time legacy migration and narrowly-scoped adapters proven necessary by a failing product test.
- Growth mechanics are not implemented in the overlay. N.E.K.O native evidence/reflection/persona-promotion/correction mechanisms remain authoritative; XiaoYu only declares which identity dimensions may or may not change.
- There is currently no private XiaoYu runtime plugin. Add one only when a concrete acceptance failure cannot be solved by N.E.K.O/configuration/a mature external component.
- Do not modify N.E.K.O core unless a wanted feature cannot be expressed as configuration, external component, plugin or adapter.
- Core patches live only in patches/ and are explicitly counted. Initial patch budget is zero.
- Never dual-write memory/identity authorities.
- Private customization is optimized for this user, not for upstream generality.

Development layout:
- N.E.K.O checkout: D:\xiaoyu_external_audit\N.E.K.O
- private overlay checkout: this repository
- isolated private state: D:\xiaoyu_private_overlay_state
- pinned external QQ plugin: private_overlay/QQ_PLUGIN_UPSTREAM.lock.json

Startup:
- Run tools/setup_local.ps1 after changing pinned external components.
- Use tools/start_xiaoyu.ps1 for private XiaoYu use. It verifies local pins, runs the privacy/authority preflight, sets the isolated XiaoYu storage root, then launches N.E.K.O directly.
- Use tools/start_xiaoyu.ps1 -PreflightOnly to validate the launch path without starting the UI.

The desired steady state is data + policy + conformance around N.E.K.O, not a second XiaoYu runtime.