# XiaoYu Private Overlay

This directory is the permanent private customization layer on top of Project N.E.K.O.

Principles:
- N.E.K.O remains the product chassis and the default single authority for memory, persona storage, tasks, QQ/OneBot, voice/vision and plugins.
- XiaoYu owns only private identity/evolution policy, personal tools, conformance tests and narrowly-scoped adapters.
- Do not modify N.E.K.O core unless a wanted feature cannot be expressed as configuration, plugin, adapter or external component.
- Core patches live only in patches/ and are explicitly counted. Initial patch budget is zero.
- Never dual-write memory/identity authorities.
- Private customization is optimized for this user, not for upstream generality.

Development layout:
- N.E.K.O checkout: D:\xiaoyu_external_audit\N.E.K.O
- private overlay checkout: this repository
- external N.E.K.O plugin project: private_overlay/plugins/xiaoyu_private

The plugin can be registered directly through N.E.K.O Plugin Workbench by selecting its plugin.toml; it does not need to be copied into the upstream repository.
