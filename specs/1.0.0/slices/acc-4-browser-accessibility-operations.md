# ACC-4 — Browser, Accessibility, Visual, and Operations Acceptance

**Requirements:** ACC-09, ACC-10, ACC-11
**Depends on:** ACC-2, REL-5

## Build sequence

1. Create Playwright projects for supported Chromium, Firefox, and WebKit versions, desktop/mobile
   viewports, reduced motion, and production frontend/backend builds.
2. Seed deterministic personas/data and cover OOBE/auth, inventory/topology, discovery, agents,
   monitors, settings, backup/restore, empty/error/loading/stale, and destructive confirmations.
3. Fail on uncaught page error, unexpected console error/warning, failed request, mixed content,
   WebSocket failure, hydration/runtime error, or leaked secret.
4. Add automated accessibility scanning, then manual keyboard order, visible focus, modal trapping,
   semantics/names, zoom/reflow, contrast, reduced motion, and screen-reader smoke.
5. Add deterministic screenshot baselines at named viewports and define reviewer/update policy.
6. Exercise operations surfaces: metrics, structured logs, alert firing/recovery, config validation,
   backup timer, log rotation, and support bundle generation during a controlled fault.

## Verification

```bash
cd apps/frontend && npm test -- --run && npm run lint && npm run build
npx playwright test
```

The Playwright command becomes authoritative only after its config starts production artifacts and
all claimed browsers. Retain traces/screenshots/video on failure and manual accessibility records.

## Done

All supported browsers/viewports pass with a clean console, WCAG 2.2 AA evidence has automated and
manual components, visual changes are reviewed, and operational tooling diagnoses an injected fault.
