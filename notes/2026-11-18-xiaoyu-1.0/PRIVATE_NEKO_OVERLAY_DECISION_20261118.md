# Private N.E.K.O Overlay Decision — 2026-11-18

Status: ACTIVE DIRECTION

## Decision

XiaoYu will not pursue upstream collaboration as a project goal. Project N.E.K.O is used as the private product chassis and may be locally customized for this user's needs.

The target shape is:

N.E.K.O upstream-compatible checkout
+ private XiaoYu identity/policy/configuration
+ pinned external plugins where they already solve the surface
+ XiaoYu conformance/evaluation assets
+ a small explicit local core-patch queue only when extension seams are insufficient.

## Ownership

N.E.K.O remains the default authority for:
- memory/persona storage;
- evidence scoring, reflection, correction and persona evolution/promotion;
- companion UI and embodiment;
- voice/vision;
- OneBot/QQ connectors;
- plugin/MCP/tool runtime;
- NekoClaw task runtime.

Pinned external components may own a surface when they already fit, currently including the QQ auto-reply plugin.

XiaoYu permanently owns:
- XiaoYu identity definition and hard invariants;
- the list of identity dimensions that may or may not change;
- private provider trust policy;
- continuity/privacy/erasure/product acceptance cases;
- one-time migration logic;
- any narrow local adapter proven necessary by a failing product test.

XiaoYu does **not** own a second evolution engine. N.E.K.O native evidence/reflection/persona-promotion/correction is authoritative. The overlay must not add its own scoring, promotion scheduler, persona store or memory engine.

## Private customization rule

Optimize for overall benefit to this user's product experience, not upstream generality.

Preferred implementation order:
1. configuration/data;
2. existing N.E.K.O capability;
3. pinned external mature component;
4. external N.E.K.O plugin;
5. narrow adapter;
6. narrow local N.E.K.O core patch.

Do not keep multiple memory/identity/evolution/task authorities active for the same domain.

## Upstream updates

Keep N.E.K.O close enough to upstream main to selectively absorb useful changes. Private core patches must be enumerated and independently replayable. An upstream update is accepted only after XiaoYu conformance/acceptance passes.

## Initial implementation

The private overlay lives under private_overlay/.
Initial core patch budget: 0.
Initial memory/persona/evolution/task authority: N.E.K.O native.
