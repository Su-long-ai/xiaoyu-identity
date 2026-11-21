# Capability Layer v1

This is a deliberately thin routing primitive for XiaoYu/N.E.K.O experiments.

It is **not** a second plugin host, task runtime, memory authority, persona authority,
or lifecycle manager. N.E.K.O remains responsible for plugin/native lifecycle,
storage, permissions, and execution. The registry only answers one question:
which already-owned implementation should serve a versioned capability call?

The first target is `interruptibility.v1`. A later N.E.K.O integration can map
providers to native implementations or plugin entries while keeping this routing
contract:

- explicit versioned capability IDs;
- deterministic priority;
- health-based skip;
- failure fallback;
- shadow providers that are observed but cannot take control;
- no implicit global singleton and no persistence.

The intended migration path is to retire narrow core patches when a stable
N.E.K.O extension point exists. Do not move memory/persona/task authority into
this package.
