# REL-5 — Browser and Test Infrastructure

**Requirements:** REL-17, REL-18, REL-19, REL-20
**Depends on:** ACC-1 evidence contract

## Build sequence

1. Add Playwright as an explicit frontend/E2E dependency and define production web/API startup with
   unique ports, isolated database, deterministic clock/data, and clean teardown.
2. Configure supported Chromium/Firefox/WebKit and desktop/mobile projects. Record browser version,
   seed, server/agent artifact identity, and environment in reports.
3. Build fixtures through supported APIs where possible; reserve direct DB seeding for stable setup
   helpers with schema checks. Avoid shared mutable accounts and order-dependent tests.
4. Add trace, screenshot, video, console/network log, backend/worker log, and container diagnostics on
   failure. Shard by stable test IDs without sharing Compose project or database state.
5. Add deterministic visual baselines with fonts/animations/time/network controlled and explicit
   reviewer workflow.
6. Require issue, owner, reason, and expiry for skips/xfails; fail new warnings and unexpected passes.

## Verification and done

Run the suite twice with different shard layouts and the same seed, reproduce a seeded failure locally,
and diagnose it using retained artifacts alone. Done means browser tests exercise real cookies,
CSRF, routing, WebSockets, responsiveness, focus, and production bundles across all supported engines.
