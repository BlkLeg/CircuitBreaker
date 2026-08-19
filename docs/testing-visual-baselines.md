# Visual Regression Baselines

**Requirement:** REL-18 — reviewed desktop and mobile baselines with deterministic fixtures.

**Status: not yet generated.** The spec (`apps/frontend/e2e/visual.spec.ts`) is in place and
covers the surfaces REL-18 names. The baseline images are not committed yet, because they must be
produced in the same container CI renders in.

## Why baselines cannot be made on a developer machine

Font rasterisation differs between hosts. A baseline captured on a laptop will not match what the
CI container renders, so every run would diff on antialiasing rather than on real layout change —
and the usual response to that is to disable the check. Generating them in the CI image is what
makes the gate meaningful.

## Bootstrapping the baselines

Run once, from the repository root, on any machine with Docker:

```bash
docker run --rm -v "$(pwd):/work" -w /work/apps/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c "npm ci && npx playwright test --project=visual-desktop --project=visual-mobile --update-snapshots"
```

The image tag must match the `@playwright/test` version in
`apps/frontend/package.json` (currently **1.62.1**). A mismatch shows up as
unexplainable screenshot diffs.

## Review before committing

REL-18 calls baselines *reviewed* artifacts. Open every generated PNG under
`apps/frontend/e2e/visual.spec.ts-snapshots/` and confirm each shows the page rendered correctly
in its intended empty state. **A screenshot of a broken page committed as a baseline permanently
blesses the breakage.** The spec already refuses to capture a page showing its ErrorBoundary, but
that does not catch a page that is merely wrong.

Then commit the whole snapshot directory.

## Verifying, and updating later

```bash
# verify against committed baselines
docker run --rm -v "$(pwd):/work" -w /work/apps/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c "npm ci && npx playwright test --project=visual-desktop --project=visual-mobile"
```

When a UI change is intentional, re-run with `--update-snapshots`, review the diff in the PR, and
commit. Never update baselines in the same commit as the change that altered them without saying so
in the message — the diff is the review.

## Why these do not run in the normal browser job

`playwright.config.ts` gives the functional projects a `testIgnore` for `visual.spec.ts`, so a
missing or stale baseline cannot fail an unrelated PR. Once baselines are committed, add
`--project=visual-desktop --project=visual-mobile` to the Browser E2E job in
`.github/workflows/ci.yml`.
