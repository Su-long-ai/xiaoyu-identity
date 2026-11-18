# Private N.E.K.O Overlay Decision — 2026-11-18

Status: ACTIVE DIRECTION

## Decision

XiaoYu will not pursue upstream collaboration as a project goal. Project N.E.K.O is used as the private product chassis and may be locally customized for this user's needs.

The target shape is:

N.E.K.O upstream-compatible checkout
+ private XiaoYu external plugins/configuration/adapters
+ XiaoYu identity/evolution/evaluation assets
+ a small explicit local core-patch queue only when extension seams are insufficient.

## Ownership

N.E.K.O remains the default authority for:
- memory/persona storage;
- companion UI and embodiment;
- voice/vision;
- QQ/OneBot/NapCat;
- plugin/MCP/tool runtime;
- NekoClaw task runtime.

XiaoYu permanently owns:
- XiaoYu identity definition;
- growth/evolution policy;
- private per-user behavior and tools;
- continuity/privacy/erasure/product acceptance cases;
- one-time migration logic;
- any narrow local adapter proven necessary.

## Private customization rule

Optimize for overall benefit to this user's product experience, not upstream generality.

Preferred implementation order:
1. configuration;
2. external N.E.K.O plugin;
3. external mature component behind one authority boundary;
4. adapter;
5. narrow local N.E.K.O core patch.

Do not keep multiple memory/identity/task authorities active for the same domain.

## Upstream updates

Keep N.E.K.O close enough to upstream main to selectively absorb useful changes. Private core patches must be enumerated and independently replayable. An upstream update is accepted only after XiaoYu conformance/acceptance passes.

## Initial implementation

The private overlay lives under private_overlay/.
Initial core patch budget: 0.
Initial memory/persona/task authority: N.E.K.O native.
