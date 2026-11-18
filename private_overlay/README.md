# XiaoYu Private Overlay

This directory is the permanent private customization layer on top of Project N.E.K.O.

Principles:
- N.E.K.O remains the product chassis and the single runtime authority for memory, persona storage, persona evolution/evidence promotion, tasks, voice/vision and plugin/tool execution.
- QQ is reused through the pinned external N.E.K.O QQ plugin and N.E.K.O OneBot/QQ connectors.
- XiaoYu owns only private identity constraints/content, provider trust policy, conformance tests, one-time legacy migration and narrowly-scoped adapters proven necessary by a failing product test.
- Growth mechanics are not implemented in the overlay. N.E.K.O native evidence/reflection/persona-promotion/correction mechanisms remain authoritative; XiaoYu only declares which identity dimensions may or may not change.
- Do not modify N.E.K.O core unless a wanted feature cannot be expressed as configuration, plugin, adapter or external component.
- Core patches live only in patches/ and are explicitly counted. Initial patch budget is zero.
- Never dual-write memory/identity authorities.
- Private customization is optimized for this user, not for upstream generality.

Development layout:
- N.E.K.O checkout: D:\xiaoyu_external_audit\N.E.K.O
- private overlay checkout: this repository
- optional external XiaoYu plugin project: private_overlay/plugins/xiaoyu_private

The private plugin is an extension seam, not a required second runtime. Keep it thin or empty until a concrete acceptance failure needs private runtime behavior.
