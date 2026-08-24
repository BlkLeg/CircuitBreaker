# Visual Regression Baselines

**Requirement:** REL-18 — reviewed desktop and mobile baselines with deterministic fixtures.

**Status: generated and committed** (2026-08-19, 18 baselines: 9 surfaces × desktop/mobile).
They were produced in the CI Playwright container, reviewed image by image, and verified to
reproduce on two consecutive runs before being committed. The Browser E2E job in
`.github/workflows/ci.yml` runs them on every PR.

## Why baselines cannot be made on a developer machine

Font rasterisation differs between hosts. A baseline captured on a laptop will not match what the
CI container renders, so every run would diff on antialiasing rather than on real layout change —
and the usual response to that is to disable the check. Generating them in the CI image is what
makes the gate meaningful.

## What makes the fixtures deterministic

REL-18 says *deterministic* fixtures, and the app has three sources of per-run variance that had to
be neutralised before a baseline was worth committing. All three were found by generating a first
set and looking at it:

- **The header clock and date** (`HeaderWidgets.jsx:81-85`) tick once a second. `visual.spec.ts`
  freezes them with `page.clock.setFixedTime`. Without this every baseline diffs on the second
  hand, one day after it is committed.
- **The weather widget** calls `open-meteo.com` directly (`HeaderWidgets.jsx:60,103`) — not through
  `/api/v1`, so the API stub never saw it. `stubApi` now intercepts it. Besides baking the live
  temperature into every screenshot, leaving it unstubbed makes the whole suite non-hermetic: it
  reaches the public internet on every page load.
- **The route-enter fade.** `App.jsx:135-141` fades each route in over 150 ms, and framer-motion
  drives it from JS, so a CSS `animation-duration: 0s` override cannot freeze it. Every spec waits
  on `waitForRouteSettled` before it measures anything.

Beyond that the fixtures are the empty-state stubs in `e2e/fixtures/api.ts`. A screenshot seeded
from live data is a flake generator, not a baseline.

## Bootstrapping or refreshing the baselines

Run from the repository root, on any machine with Docker:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$(pwd):/work" -w /work/apps/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c "npx playwright test --project=visual-desktop --project=visual-mobile --update-snapshots"
```

`--user` matters: without it the container writes the PNGs, `dist/` and `test-results/` as root,
and the next run — in the container or on the host — fails on `EACCES` trying to replace them.

The image tag must match the `@playwright/test` version in `apps/frontend/package.json`
(currently **1.62.1**). A mismatch shows up as unexplainable screenshot diffs.

Add `npm ci &&` to the command if `apps/frontend/node_modules` is absent or was installed for a
different platform.

## Review before committing

REL-18 calls baselines *reviewed* artifacts. Open every generated PNG under
`apps/frontend/e2e/visual.spec.ts-snapshots/` and confirm each shows the page rendered correctly
in its intended empty state. **A screenshot of a broken page committed as a baseline permanently
blesses the breakage.** The spec already refuses to capture a page showing its ErrorBoundary, but
that does not catch a page that is merely wrong — the first generated set had `/map` sitting on
"Loading maps…", which the ErrorBoundary check passed happily.

Then verify the set reproduces before committing it:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$(pwd):/work" -w /work/apps/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c "npx playwright test --project=visual-desktop --project=visual-mobile"
```

Run it twice. A baseline that passes once may still be capturing something that varies.

## Updating later

When a UI change is intentional, re-run with `--update-snapshots`, review the diff in the PR, and
commit. Never update baselines in the same commit as the change that altered them without saying so
in the message — the diff is the review.

## Why the functional projects still ignore this spec

`playwright.config.ts` gives the functional projects (`chromium`, `firefox`, `webkit`,
`mobile-chrome`) a `testIgnore` for `visual.spec.ts`. Visual regression runs only under the
dedicated `visual-desktop` and `visual-mobile` projects, so a stale baseline fails the visual gate
and nothing else.
