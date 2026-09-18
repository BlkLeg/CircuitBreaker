# Visual Regression Baselines

**Requirement:** REL-18 — reviewed desktop and mobile baselines with deterministic fixtures.

**Status: generated and committed** (2026-08-19, refreshed in full 2026-09-18; 18 baselines:
9 surfaces × desktop/mobile). They were produced in the CI Playwright container, reviewed image
by image, and verified to reproduce on two consecutive runs before being committed. The Browser
E2E job in `.github/workflows/ci.yml` runs them on every PR.

### Refresh all 18, not only the red ones

The 2026-09-18 refresh followed six surfaces going red on the header gaining its `Navigate`
button and several pages gaining a tab strip. The other twelve were stale by the same header
change and stayed green only because a header is about 5.5k pixels — under the 1% `maxDiffPixelRatio`
in `playwright.config.ts`. That is the failure mode to watch for here: tolerance silently absorbing
real drift until the budget is spent, at which point an unrelated one-line change is what finally
turns a surface red and gets blamed for it.

So a refresh uses `--update-snapshots=all`. Plain `--update-snapshots` rewrites only the baselines
that failed, which keeps every under-tolerance baseline stale and leaves the next author with the
same trap.

## Why baselines cannot be made on a developer machine

Font rasterisation differs between hosts. A baseline captured on a laptop will not match what the
CI container renders, so every run would diff on antialiasing rather than on real layout change —
and the usual response to that is to disable the check. Generating them in the CI image is what
makes the gate meaningful.

## What makes the fixtures deterministic

REL-18 says *deterministic* fixtures, and the app has five sources of per-run variance that had to
be neutralised before a baseline was worth committing. The first three were found by generating a
first set and looking at it; the last two by chasing a flake that failed a different subset of
surfaces on each run:

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

- **The web font.** `useAppFont` used to inject a `<link>` to
  `fonts.googleapis.com` on every page load (`lib/fonts.js`), so the app fetched
  its typeface from the public internet and text metrics depended on that
  round-trip finishing before the screenshot. The failure looked like
  character-level horizontal offsets on a different two or three surfaces each
  run, including surfaces nobody had touched. **Fixed at the source rather than
  in the fixture:** the faces are vendored under `apps/frontend/public/fonts`
  and declared in `styles/fonts.css`, so the baselines render the real
  typography and nothing reaches a font CDN. `stubApi` still routes the CDN
  hosts as a backstop, and `e2e/no-third-party-fonts.spec.ts` fails loudly if a
  `<link>` is ever reintroduced.
- **The SSE stream.** `ConnectionStatus` shows a "Reconnecting to live data..." banner five seconds
  after `sseClient` reports disconnected. `stubApi` stubbed WebSockets but not `EventSource`, so
  `/api/v1/events/stream` was answered with JSON, the connection failed, and the banner appeared on
  whichever surfaces took longer than the grace period to settle — shifting the whole page. A quiet
  `EventSource` substitute now opens and stays silent, the SSE counterpart of the WebSocket stub.

Beyond that the fixtures are the empty-state stubs in `e2e/fixtures/api.ts`. A screenshot seeded
from live data is a flake generator, not a baseline.

## Bootstrapping or refreshing the baselines

Run from the repository root, on any machine with Docker:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$(pwd):/work" -w /work/apps/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c "npx playwright test --project=visual-desktop --project=visual-mobile --update-snapshots=all"
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

When a UI change is intentional, re-run with `--update-snapshots=all`, review the diff in the PR, and
commit. Never update baselines in the same commit as the change that altered them without saying so
in the message — the diff is the review.

## Why the functional projects still ignore this spec

`playwright.config.ts` gives the functional projects (`chromium`, `firefox`, `webkit`,
`mobile-chrome`) a `testIgnore` for `visual.spec.ts`. Visual regression runs only under the
dedicated `visual-desktop` and `visual-mobile` projects, so a stale baseline fails the visual gate
and nothing else.

## Running the browser suite locally

```bash
cd apps/frontend && npx playwright test --project=chromium
```

`playwright.config.ts` builds the app and serves it with `vite preview` on **4173**, and outside CI
it reuses a server already listening there. That reuse saves a rebuild per run, but the port is a
common default and the reuse is not fussy about *what* answers on it. If another program owns 4173,
Playwright attaches to it and the whole suite runs against a different website — every spec fails in
`waitForRouteSettled`, which reads exactly like the app being broken.

`e2e/fixtures/assert-server-is-ours.ts` runs as `globalSetup` and refuses that case before any spec
does, naming what actually answered. To run alongside whatever holds the port:

```bash
CB_E2E_PORT=4273 npx playwright test --project=chromium
```

Run `e2e/accessibility.spec.ts` with any change to roles or ARIA attributes. It is an axe gate for
WCAG 2.2 AA, and it is what caught a `listbox` that contained per-row buttons — a `critical`
`aria-required-children` violation that every unit test had passed.
