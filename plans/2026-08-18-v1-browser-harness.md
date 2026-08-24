# Browser Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the browser test layer the product has none of, use it to diagnose and close the open high-severity navigation regression, and close the cheap test-strategy gates (coverage thresholds, warning-as-error) that currently let regressions through unnoticed.

**Architecture:** Playwright drives the **production build** (`vite preview`) with the API stubbed at the network layer via `page.route`, so the suite needs no backend and runs in CI in under a minute. This is deliberate scoping: it covers routing, chunk loading, focus, console health, accessibility and visual regression — everything `known_bugs` item 1 lives in — without pulling a database into the loop. Full-stack journeys against a real backend (ACC-05 through ACC-08) remain future work on top of this harness.

**Tech Stack:** Playwright 1.5x, `@axe-core/playwright`, Vite 5 preview server, Vitest v8 coverage.

**Spec:** `specs/1.0.0/06-reliability-quality-capacity.md` (REL-14, REL-15, REL-17, REL-18, REL-19), `specs/1.0.0/05-artifact-acceptance-and-recovery.md` (ACC-09, ACC-10)

## Global Constraints

- Node 20 (matches `.github/workflows/ci.yml`'s `setup-node`).
- The app's API client uses a **relative** `baseURL: '/api/v1'` (`apps/frontend/src/api/client.jsx:52`), so `page.route('**/api/v1/**')` intercepts everything without config changes.
- Build target floor is `chrome100, firefox100, safari15, edge100` (`apps/frontend/vite.config.js`). Do not test below it.
- REL-17 requires E2E to run against **production builds**, not the dev server.
- Browsers under test per `docs/release/1.0.0-support-contract.md:61`: Chrome 111+, Edge 111+, Firefox 113+, Safari 16.4+ → Playwright projects `chromium`, `firefox`, `webkit`.
- Screenshots are committed as versioned baselines; they must be generated in the CI container image, not on a developer laptop, or they will never match.

---

### Task 1: Playwright harness against the production build

**Files:**
- Create: `apps/frontend/playwright.config.ts`
- Create: `apps/frontend/e2e/fixtures/api.ts`
- Create: `apps/frontend/e2e/smoke.spec.ts`
- Modify: `apps/frontend/package.json` (scripts + devDependencies)
- Modify: `.gitignore`

**Interfaces:**
- Produces: `stubApi(page: Page, overrides?: Record<string, unknown>): Promise<void>` — installs a route handler covering every `/api/v1/**` call the app makes on boot, so a test can render any route without a backend. Later tasks call it as their first line.

- [ ] **Step 1: Install Playwright**

Run:
```bash
cd apps/frontend
npm install -D @playwright/test@^1.50.0 @axe-core/playwright@^4.10.0
npx playwright install --with-deps chromium firefox webkit
```
Expected: three browsers install. Record the exact `@playwright/test` version that lands in `package.json` — the CI image must pin the same one.

- [ ] **Step 2: Write the config**

```typescript
// apps/frontend/playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

// REL-17: E2E must run against production builds, not the dev server. The
// dev server's on-demand transform hides exactly the class of bug this suite
// exists to catch — lazy chunks that fail to resolve after a real build.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [['junit', { outputFile: 'playwright-report/junit.xml' }], ['html', { open: 'never' }]]
    : [['list']],
  timeout: 30_000,
  expect: {
    timeout: 10_000,
    // REL-18: baselines are reviewed artifacts. A small threshold absorbs
    // font antialiasing differences without absorbing real layout drift.
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'] } },
  ],
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
```

- [ ] **Step 3: Write the API stub fixture**

```typescript
// apps/frontend/e2e/fixtures/api.ts
import type { Page } from '@playwright/test';

/**
 * Every /api/v1 response the app needs to boot and route, keyed by the tail of
 * the URL. Values are the JSON body. A request with no entry gets an empty
 * object, so a newly added boot call degrades to "empty state" rather than an
 * unhandled rejection that fails an unrelated assertion.
 */
const DEFAULTS: Record<string, unknown> = {
  'auth/me': { id: 1, email: 'operator@example.test', role: 'admin', is_active: true },
  'settings': { default_environment: '', environments: [], map_default_filters: {} },
  'environments': [],
  'hardware': [],
  'compute-units': [],
  'services': [],
  'storage': [],
  'networks': [],
  'misc': [],
  'external-nodes': [],
  'tags': [],
  'categories': [],
  'agents': [],
  'monitors': [],
  'topologies': [],
  'graph': { nodes: [], edges: [] },
  'health': { state: 'ready', ready: true, uptime_s: 1, checks: { db: 'ok', redis: 'ok' } },
};

export async function stubApi(page: Page, overrides: Record<string, unknown> = {}): Promise<void> {
  const responses = { ...DEFAULTS, ...overrides };

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const tail = url.pathname.replace(/^\/api\/v1\//, '').replace(/\/$/, '');

    // Longest-prefix match, so 'hardware/12' falls back to the 'hardware' entry.
    const key = Object.keys(responses)
      .filter((candidate) => tail === candidate || tail.startsWith(`${candidate}/`))
      .sort((a, b) => b.length - a.length)[0];

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(key ? responses[key] : {}),
    });
  });

  // SSE/WebSocket streams: answer with an immediately-closing stream so the
  // client's reconnect logic does not spin during a test.
  await page.route('**/api/v1/**/stream**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
  );
}

/** Collects console errors and page exceptions for ACC-09's "console clean" assertion. */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(String(err)));
  return errors;
}
```

- [ ] **Step 4: Write the smoke test**

```typescript
// apps/frontend/e2e/smoke.spec.ts
import { expect, test } from '@playwright/test';
import { collectConsoleErrors, stubApi } from './fixtures/api';

test('the app boots and renders without console errors', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await stubApi(page);

  await page.goto('/');
  await expect(page.locator('body')).toBeVisible();

  // ACC-09: "console clean". Filter the known-benign noise explicitly rather
  // than asserting a count, so a real error is never absorbed by a threshold.
  const significant = errors.filter((e) => !/favicon|ResizeObserver loop/i.test(e));
  expect(significant, `unexpected console errors:\n${significant.join('\n')}`).toHaveLength(0);
});
```

- [ ] **Step 5: Add the scripts and ignore generated output**

Add to `apps/frontend/package.json` `scripts`:

```json
    "e2e": "playwright test",
    "e2e:ui": "playwright test --ui",
    "e2e:update-snapshots": "playwright test --update-snapshots"
```

Append to the repo-root `.gitignore`:

```gitignore
# Playwright generated output (baselines under e2e/**/*-snapshots/ ARE tracked)
apps/frontend/playwright-report/
apps/frontend/test-results/
```

- [ ] **Step 6: Run the smoke test**

Run: `cd apps/frontend && npx playwright test smoke.spec.ts --project=chromium`
Expected: PASS — 1 passed. The build runs first, so allow ~60s on the first invocation.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/playwright.config.ts apps/frontend/e2e/ \
        apps/frontend/package.json apps/frontend/package-lock.json .gitignore
git commit -m "test(e2e): add Playwright harness against the production build (REL-17)

The product shipped with no browser test layer at all, which is why the
navigation regression in known_bugs item 1 reached rc.2 unnoticed — its own
analysis notes a jsdom test cannot catch that class of bug. Runs against
vite preview with the API stubbed at the network layer, so it needs no
backend and stays fast enough to gate every PR."
```

---

### Task 2: Reproduce the navigation regression

`known_bugs-v1.0.0-rc.1.md` item 1: clicking a nav entry changes the URL but the page content does not respond until a manual reload. Open in rc.2, high severity, and explicitly *"not reproducible in jsdom"*. The file also warns against blind fixes — `8bb0ee25` added the `AnimatePresence` wrapper *as* the fix for this same symptom, so deleting it may reopen the original cause.

**Files:**
- Create: `apps/frontend/e2e/navigation.spec.ts`

**Interfaces:**
- Consumes: `stubApi`, `collectConsoleErrors` from Task 1.

- [ ] **Step 1: Write the failing test**

```typescript
// apps/frontend/e2e/navigation.spec.ts
import { expect, test } from '@playwright/test';
import { collectConsoleErrors, stubApi } from './fixtures/api';

// known_bugs-v1.0.0-rc.1.md item 1: the URL advances but the route never
// renders until a manual reload. The file's own investigation narrowed it to
// two candidates — a wedged framer-motion exit animation (markup present,
// opacity stuck at 0) or a route that never mounts (markup absent). The two
// assertions below separate those, which is exactly the diagnostic the bug
// report says it needs from a running instance.
// Only non-redirecting routes: '/' -> /map and '/networks' -> /ipam are
// <Navigate> redirects (App.jsx:145,150), so asserting their own URL fails.
const ROUTES = [
  { path: '/hardware', label: /hardware/i },
  { path: '/services', label: /services/i },
  { path: '/ipam', label: /ipam|networks/i },
  { path: '/storage', label: /storage/i },
];

test.describe('client-side navigation completes without a reload', () => {
  for (const route of ROUTES) {
    test(`navigating to ${route.path} renders its content`, async ({ page }) => {
      const errors = collectConsoleErrors(page);
      await stubApi(page);
      await page.goto('/');

      await page.evaluate((path) => window.history.pushState({}, '', path), route.path);
      await page.goto(route.path);
      await expect(page).toHaveURL(new RegExp(`${route.path}$`));

      const content = page.locator('.page-content');
      await expect(content, 'route never mounted — the fix is in AnimatePresence/Suspense')
        .toBeVisible({ timeout: 10_000 });

      // The "wedged animation" half of the diagnostic: markup exists but is
      // invisible because the enter animation never ran.
      const opacity = await content.evaluate((el) => getComputedStyle(el).opacity);
      expect(Number(opacity), 'route mounted but stuck at opacity 0 — the fix is in the animation layer')
        .toBeGreaterThan(0.9);

      expect(errors.filter((e) => !/favicon|ResizeObserver loop/i.test(e))).toHaveLength(0);
    });
  }

  test('clicking through the dock advances the rendered page, not just the URL', async ({ page }) => {
    await stubApi(page);
    await page.goto('/');

    const before = await page.locator('.page-content').innerHTML();
    await page.getByRole('link', { name: /hardware/i }).first().click();

    await expect(page).toHaveURL(/\/hardware$/);
    await expect
      .poll(async () => page.locator('.page-content').innerHTML(), { timeout: 10_000 })
      .not.toBe(before);
  });
});
```

- [ ] **Step 2: Run it and record which half of the diagnostic fires**

Run: `cd apps/frontend && npx playwright test navigation.spec.ts --project=chromium --reporter=list`

Three outcomes, and they mean different things — record which one you got:

- **`toBeVisible` fails** → the route never mounted. The fix is in `AnimatePresence`/`Suspense` (`App.jsx:135-144`).
- **`opacity` assertion fails** → the route mounted but the enter animation never ran. The fix is in the animation layer.
- **Everything passes** → the bug does not reproduce against a stubbed API. Do **not** close the bug. Re-run with `--project=firefox --project=webkit`, then with a slowed network (`page.route` with a delay) to mimic the real first-visit chunk timing the report describes. If it still will not reproduce, record that in `known_bugs-v1.0.0-rc.1.md` with what was tried — the harness is still the deliverable.

- [ ] **Step 3: Fix the cause the diagnostic identified**

Apply the narrowest fix for whichever branch fired. Do **not** delete the `AnimatePresence` wrapper as a first move — `8bb0ee25` added it *as* the fix for this symptom, and removing it may reopen the original cause. If the wrapper genuinely is the cause, replace `mode="wait"` with a mode that does not hold the incoming route on an unresolved exit, and keep the wrapper:

```jsx
// apps/frontend/src/App.jsx — only if the diagnostic pointed here.
// mode="wait" holds the incoming route until the outgoing exit animation
// resolves. A lazy chunk that suspends during exit never resolves it, so the
// URL advances and the render does not — the symptom 8bb0ee25 fixed once and
// this reintroduced. "sync" renders the incoming route immediately and keeps
// the wrapper 8bb0ee25 added.
<AnimatePresence mode="sync">
```

- [ ] **Step 4: Verify across all three engines**

Run: `cd apps/frontend && npx playwright test navigation.spec.ts`
Expected: PASS on chromium, firefox and webkit.

- [ ] **Step 5: Update the bug record**

Move item 1 in `known_bugs-v1.0.0-rc.1.md` from open to fixed, recording the diagnostic result, the cause, and the test that now guards it. If Step 2 did not reproduce, record that instead — an honest "not reproduced under these conditions" is a valid state; "fixed" is not.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/e2e/navigation.spec.ts apps/frontend/src/App.jsx known_bugs-v1.0.0-rc.1.md
git commit -m "fix(routing): close the sticky-navigation regression, guarded by Playwright

known_bugs item 1: the URL advanced but the route never rendered until a
manual reload. Open since rc.1 and explicitly not reproducible in jsdom.
The test asserts both halves of the diagnostic the bug report asked for —
whether the route mounted at all, and whether it mounted invisible — so a
recurrence names its own cause instead of needing a live instance again."
```

---

### Task 3: Accessibility gate

ACC-10 requires WCAG 2.2 AA automation plus manual keyboard/focus/semantics checks. Nothing automated exists.

**Files:**
- Create: `apps/frontend/e2e/accessibility.spec.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// apps/frontend/e2e/accessibility.spec.ts
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { stubApi } from './fixtures/api';

// NB: '/' redirects to /map and '/networks' redirects to /ipam (App.jsx:145,150),
// so those two paths are named by their real destinations here.
const PAGES = ['/map', '/hardware', '/services', '/ipam', '/storage', '/settings'];

test.describe('WCAG 2.2 AA', () => {
  for (const path of PAGES) {
    test(`${path} has no serious or critical violations`, async ({ page }) => {
      await stubApi(page);
      await page.goto(path);
      await expect(page.locator('.page-content')).toBeVisible();

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();

      const blocking = results.violations.filter((v) => ['serious', 'critical'].includes(v.impact ?? ''));
      const summary = blocking
        .map((v) => `${v.id} (${v.impact}) × ${v.nodes.length}: ${v.help}`)
        .join('\n');
      expect(blocking, `axe violations on ${path}:\n${summary}`).toHaveLength(0);
    });
  }
});

test('keyboard focus reaches the primary navigation and is visible', async ({ page }) => {
  await stubApi(page);
  await page.goto('/');

  await page.keyboard.press('Tab');
  const focused = page.locator(':focus');
  await expect(focused).toBeVisible();

  // ACC-10 names focus visibility explicitly: a focused element with no
  // outline and no ring is a keyboard user with no cursor.
  const ring = await focused.evaluate((el) => {
    const s = getComputedStyle(el);
    return { outlineWidth: s.outlineWidth, outlineStyle: s.outlineStyle, boxShadow: s.boxShadow };
  });
  const hasIndicator =
    (ring.outlineStyle !== 'none' && ring.outlineWidth !== '0px') || ring.boxShadow !== 'none';
  expect(hasIndicator, `focused element has no visible focus indicator: ${JSON.stringify(ring)}`).toBe(true);
});
```

- [ ] **Step 2: Run it and triage**

Run: `cd apps/frontend && npx playwright test accessibility.spec.ts --project=chromium --reporter=list`
Expected: FAIL on first run is normal — an app with no prior a11y gate almost always has violations.

- [ ] **Step 3: Fix the serious and critical violations**

Work the list the failure output prints. The common first-run set is missing form labels, insufficient contrast, and missing landmark roles. Fix them in the components; do **not** add axe rule exclusions to make the gate pass. If a violation is genuinely a false positive, disable that single rule at that single node with a comment explaining why.

- [ ] **Step 4: Verify**

Run: `cd apps/frontend && npx playwright test accessibility.spec.ts`
Expected: PASS across chromium, firefox and webkit.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/e2e/accessibility.spec.ts apps/frontend/src
git commit -m "test(a11y): add WCAG 2.2 AA gate across the primary pages (ACC-10)

Automated axe coverage on six routes plus a focus-visibility assertion.
Violations were fixed in the components rather than suppressed in the rules."
```

---

### Task 4: Visual regression baselines

REL-18 requires reviewed desktop and mobile baselines with deterministic fixtures for topology, discovery, agents, monitors, settings, auth/OOBE, and empty/error states.

**Files:**
- Create: `apps/frontend/e2e/visual.spec.ts`
- Create: `apps/frontend/e2e/visual.spec.ts-snapshots/` (generated, tracked)

- [ ] **Step 1: Write the spec**

```typescript
// apps/frontend/e2e/visual.spec.ts
import { expect, test } from '@playwright/test';
import { stubApi } from './fixtures/api';

// REL-18 names these surfaces. Fixtures are the empty-state stubs from
// fixtures/api.ts, which is what makes the baselines deterministic — a
// screenshot seeded from live data is a flake generator, not a baseline.
const SURFACES = [
  { name: 'dashboard', path: '/' },
  { name: 'hardware-empty', path: '/hardware' },
  { name: 'services-empty', path: '/services' },
  { name: 'ipam-empty', path: '/ipam' },
  { name: 'agents-empty', path: '/agents' },
  { name: 'monitors-empty', path: '/monitors' },
  { name: 'settings', path: '/settings' },
  { name: 'topology-empty', path: '/map' },
];

for (const surface of SURFACES) {
  test(`${surface.name} matches its baseline`, async ({ page }) => {
    await stubApi(page);
    await page.goto(surface.path);
    await expect(page.locator('.page-content')).toBeVisible();

    // Freeze animation so a mid-transition frame never becomes the baseline.
    await page.addStyleTag({
      content: `*, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
      }`,
    });
    await page.waitForTimeout(200);

    await expect(page).toHaveScreenshot(`${surface.name}.png`, { fullPage: true });
  });
}
```

- [ ] **Step 2: Generate baselines in the CI container, not locally**

Baselines generated on a developer machine will never match CI's fonts. Generate them inside the same image CI uses:

Run:
```bash
cd apps/frontend
PW_VERSION=$(node -p "require('./package.json').devDependencies['@playwright/test'].replace(/[^0-9.]/g,'')")
docker run --rm -v "$(pwd)/../..:/work" -w /work/apps/frontend \
  "mcr.microsoft.com/playwright:v${PW_VERSION}-jammy" \
  sh -c "npm ci && npx playwright test visual.spec.ts --update-snapshots"
```
Expected: PNG files appear under `apps/frontend/e2e/visual.spec.ts-snapshots/`.

- [ ] **Step 3: Review every baseline by eye before committing**

Run: `ls -la apps/frontend/e2e/visual.spec.ts-snapshots/`

Open each PNG. REL-18 says baselines are **reviewed** artifacts — a screenshot of a broken page committed as the baseline permanently blesses the breakage. Confirm each shows the page rendered correctly with its intended empty state.

- [ ] **Step 4: Verify they now pass in the same container**

Run:
```bash
cd apps/frontend
PW_VERSION=$(node -p "require('./package.json').devDependencies['@playwright/test'].replace(/[^0-9.]/g,'')")
docker run --rm -v "$(pwd)/../..:/work" -w /work/apps/frontend \
  "mcr.microsoft.com/playwright:v${PW_VERSION}-jammy" \
  sh -c "npm ci && npx playwright test visual.spec.ts"
```
Expected: PASS — all surfaces match.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/e2e/visual.spec.ts apps/frontend/e2e/visual.spec.ts-snapshots/
git commit -m "test(visual): add reviewed desktop and mobile baselines (REL-18)

Covers the surfaces REL-18 names, seeded from deterministic empty-state
fixtures. Baselines are generated in the CI Playwright container so they
match what CI renders, and each was reviewed before being committed."
```

---

### Task 5: Frontend coverage thresholds

REL-15 requires published frontend line/branch coverage with critical thresholds that fail CI on regression. `vitest.config.ts:12-15` sets only `provider` and `reporter` — no `thresholds` — and CI runs `npm test`, not `test:coverage`, with `--passWithNoTests`.

**Files:**
- Modify: `apps/frontend/vitest.config.ts`
- Modify: `.github/workflows/ci.yml` (the `test` job)

- [ ] **Step 1: Measure the real baseline before choosing a number**

Run: `cd apps/frontend && npx vitest run --coverage 2>&1 | tail -25`
Expected: a coverage table. **Record the actual `% Lines`, `% Branch`, `% Funcs` and `% Stmts` totals** — the thresholds in Step 2 must be set to these measured numbers, not to the placeholders shown.

- [ ] **Step 2: Add thresholds at the measured baseline**

```typescript
// apps/frontend/vitest.config.ts — replace the `coverage` block
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      reportsDirectory: './coverage',
      // REL-15: a ratchet, not an aspiration. These are the numbers measured
      // on the full suite — replace each with the real value from Step 1.
      // Raise them deliberately as coverage improves; never lower them to make
      // a red build green.
      thresholds: {
        lines: 0,      // <- replace with the measured % Lines, rounded DOWN to the integer
        branches: 0,   // <- replace with the measured % Branch, rounded DOWN
        functions: 0,  // <- replace with the measured % Funcs, rounded DOWN
        statements: 0, // <- replace with the measured % Stmts, rounded DOWN
      },
      exclude: [
        'node_modules/**',
        'dist/**',
        'e2e/**',
        'src/__tests__/**',
        '**/*.config.{js,ts}',
        '**/*.d.ts',
      ],
    },
```

- [ ] **Step 3: Verify the gate holds and would catch a regression**

Run:
```bash
cd apps/frontend
npx vitest run --coverage
```
Expected: PASS. Then prove the gate is live by temporarily raising `lines` by 20 and re-running — it must FAIL. Restore the measured value afterwards.

- [ ] **Step 4: Run coverage in CI and retain the report**

Replace the `Frontend tests` step in the `test` job of `.github/workflows/ci.yml`:

```yaml
      # REL-15: coverage is published and enforced, not just produced. The
      # threshold lives in vitest.config.ts so a local run fails identically.
      - name: Frontend tests with coverage
        run: cd apps/frontend && npm run test:coverage

      - name: Upload frontend coverage
        if: always()
        uses: actions/upload-artifact@v5
        with:
          name: frontend-coverage
          path: apps/frontend/coverage/
          retention-days: 14
```

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/vitest.config.ts .github/workflows/ci.yml
git commit -m "test(frontend): enforce and publish coverage thresholds (REL-15)

vitest declared a coverage provider but no thresholds, and CI ran npm test
with --passWithNoTests, so frontend coverage was neither enforced nor
retained. Thresholds are set to the measured baseline and ratchet upward."
```

---

### Task 6: Treat warnings as defects and raise the backend ratchet

REL-08 requires no unexplained async/deprecation warnings in an RC run; nothing in `apps/backend/pyproject.toml` configures `filterwarnings`, so warnings are invisible. REL-14 requires a ratchet **above** the measured 55.42% baseline; `pyproject.toml:224` sets `--cov-fail-under=55`, which rounds *down* — the gate is slacker than the measurement.

**Files:**
- Modify: `apps/backend/pyproject.toml` (the `[tool.pytest.ini_options]` block)

- [ ] **Step 1: See what warnings the suite currently emits**

Run: `cd apps/backend && python -m pytest -W error::DeprecationWarning -W error::RuntimeWarning -q 2>&1 | tail -40`
Expected: a list of failures caused by warnings, or a clean run. **Record the distinct warning types** — each becomes either a fix or an explicit, dated ignore.

- [ ] **Step 2: Add the filterwarnings block**

Add to `[tool.pytest.ini_options]` in `apps/backend/pyproject.toml`:

```toml
# REL-08: un-awaited coroutine warnings and deprecations are tracked defects,
# not noise. Errors by default; every ignore below needs an owner and a
# removal condition, and RC-08 requires the list to be empty or explained at
# sign-off.
filterwarnings = [
    "error::RuntimeWarning",
    "error::DeprecationWarning",
    # Add one ignore per finding from Step 1, in this shape:
    # "ignore:<message regex>:DeprecationWarning:<module>",  # owner, why, removal condition
]
```

- [ ] **Step 3: Do NOT raise the ratchet to 56 — the number is wrong**

**Corrected during execution on 2026-08-18.** The measured baseline is **55.42%**
(`pyproject.toml:218-223`, 31717 statements, 14141 missed, on the full 2146-test run).
`--cov-fail-under=56` is therefore *above* the measured coverage and would fail every run
immediately — the exact failure mode the existing comment records for the previous aspirational
`60`, which is why no CI job could run pytest at all.

`--cov-fail-under=55` against a real 55.42% is a ratchet with 0.42% of slack, which is normal
hygiene, not a defect. REL-14 asks for a threshold "based on a full supported suite" that
"increases intentionally" — the existing value already is that, and raising it requires *adding
coverage first*, not editing the number.

Leave the ratchet at 55. Raise it only in a change that also adds the tests to clear the new
figure.

- [ ] **Step 4: Verify the suite is green under the filterwarnings change**

Run: `cd apps/backend && python -m pytest -q 2>&1 | tail -20`
Expected: PASS with coverage at or above 55%.

**This step requires Docker.** `tests/conftest.py:32-38` starts a
`timescale/timescaledb:2.14.2-pg16` testcontainer and sets `CB_DB_URL` from it before any app
module is imported — vanilla PostgreSQL is not a substitute, because `rollup_worker`'s
`calculate_daily_rollups` uses the TimescaleDB-only `time_bucket()`.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/pyproject.toml
git commit -m "test(backend): fail on warnings and raise the ratchet to the real baseline

REL-08: no filterwarnings config meant async and deprecation warnings were
invisible. REL-14: --cov-fail-under=55 sat below the measured 55.42%, so the
gate was slacker than the number it was pinning."
```

---

### Task 7: Run the browser and composed agent suites in CI

AGT-01 requires the composed Docker journey to run against every RC and on a schedule as a **required** workflow, with logs, traces, timing and seed retained. Today `ci.yml:104` and `dev-ci.yml:77` both declare it *"deliberately NOT run here"*, and it is absent from `release.yml`.

**Files:**
- Create: `.github/workflows/e2e.yml`
- Modify: `.github/workflows/ci.yml` (add the browser job)

- [ ] **Step 1: Add the browser E2E job to CI**

Append to `.github/workflows/ci.yml` `jobs:`:

```yaml
  browser-e2e:
    name: Browser E2E
    runs-on: ubuntu-22.04
    # Pinning to the Playwright image keeps rendering identical to the
    # container the visual baselines were generated in. A version skew here
    # shows up as unexplainable screenshot diffs.
    container:
      image: mcr.microsoft.com/playwright:v1.50.0-jammy
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-node@v5
        with:
          node-version: "20"

      - name: Install frontend deps
        run: cd apps/frontend && npm ci

      - name: Run Playwright suite
        run: cd apps/frontend && npx playwright test

      # REL-20: a failed release job must be diagnosable from retained
      # artifacts alone — traces, videos, screenshots and JUnit XML.
      - name: Upload Playwright report
        if: always()
        uses: actions/upload-artifact@v5
        with:
          name: playwright-report
          path: |
            apps/frontend/playwright-report/
            apps/frontend/test-results/
          retention-days: 14
```

Keep the image tag in sync with the `@playwright/test` version installed in Task 1.

- [ ] **Step 2: Add the scheduled composed agent journey**

```yaml
# .github/workflows/e2e.yml
name: Composed Agent E2E

# AGT-01: the composed Docker journey must run against every RC and on a
# schedule, not as a local-only manual gate. It takes 35+ minutes, which is
# why it is not on the PR path — but "too slow for PRs" is not a reason for
# it to never run at all, which is where it had ended up.
on:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:
  workflow_call:

permissions:
  contents: read

jobs:
  composed-journey:
    name: Composed agent journey
    runs-on: ubuntu-22.04
    timeout-minutes: 75
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install test deps
        run: |
          python -m pip install --upgrade pip
          pip install pytest pytest-timeout requests

      - name: Run the composed journey
        env:
          # REL-20: a recorded seed is what makes a failed run reproducible.
          CB_E2E_SEED: ${{ github.run_id }}
        run: |
          cd apps/agent/e2e
          python -m pytest test_agent_e2e.py -v \
            --junitxml=junit-agent-e2e.xml \
            --timeout=3600

      - name: Collect container diagnostics
        if: always()
        run: |
          mkdir -p diagnostics
          docker ps -a > diagnostics/containers.txt 2>&1 || true
          for c in $(docker ps -aq); do
            docker logs "$c" > "diagnostics/${c}.log" 2>&1 || true
          done

      - name: Upload diagnostics
        if: always()
        uses: actions/upload-artifact@v5
        with:
          name: composed-agent-e2e
          path: |
            apps/agent/e2e/junit-agent-e2e.xml
            diagnostics/
          retention-days: 30
```

- [ ] **Step 3: Require the composed journey before a release**

In `.github/workflows/release.yml`, add it alongside the artifact-smoke gate from Plan 1 Task 4:

```yaml
  composed-e2e:
    name: Composed Agent E2E
    uses: ./.github/workflows/e2e.yml
```

and add `composed-e2e` to the `release` job's `needs:` list.

- [ ] **Step 4: Verify both workflows parse and the wiring is right**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python3 - <<'PY'
import yaml
e2e = yaml.safe_load(open('.github/workflows/e2e.yml'))
assert 'schedule' in e2e[True], "composed journey must be scheduled (AGT-01)"
ci = yaml.safe_load(open('.github/workflows/ci.yml'))
assert 'browser-e2e' in ci['jobs'], "browser E2E job missing from CI"
rel = yaml.safe_load(open('.github/workflows/release.yml'))
assert 'composed-e2e' in rel['jobs']['release']['needs'], rel['jobs']['release']['needs']
print("ok: browser-e2e in CI, composed journey scheduled and gating release")
PY
grep -n "deliberately NOT run" .github/workflows/ci.yml .github/workflows/dev-ci.yml
```
Expected: the assertion script prints ok. Update the two stale "deliberately NOT run" comments to say the suite now runs nightly and gates releases, rather than leaving them contradicting the new jobs.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/e2e.yml .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "ci: run the browser suite on PRs and the composed agent journey nightly

AGT-01 requires the composed Docker journey against every RC and on a
schedule; ci.yml and dev-ci.yml both declared it deliberately unrun and
release.yml never invoked it, so it ran nowhere. Retains traces, videos,
JUnit XML, container logs and the run seed per REL-20."
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| REL-17 (E2E from production builds, all browsers) | 1, 2 |
| ACC-09 (browsers, desktop/mobile, console clean) | 1, 2, 4 |
| ACC-10 (WCAG 2.2 AA + keyboard/focus) | 3 |
| REL-18 (reviewed visual baselines) | 4 |
| REL-15 (frontend coverage published + enforced) | 5 |
| REL-08 / REL-19 (warnings as defects) | 6 |
| REL-14 (ratchet above baseline) | 6 |
| AGT-01 (composed journey on every RC + schedule) | 7 |
| REL-20 (retained JUnit, traces, logs, seeds) | 7 |
| `known_bugs` item 1 | 2 |

**Known gaps left open deliberately:** ACC-09's "error/loading/stale states" and REL-18's auth/OOBE surfaces need fixtures that drive the app into those states; the harness supports it (pass `overrides` to `stubApi`) but the specs are not written here. ACC-05 through ACC-08 need a real backend and are explicitly out of scope for this harness.

**Type consistency:** `stubApi(page, overrides?)` and `collectConsoleErrors(page)` are defined in Task 1 and consumed by name in Tasks 2, 3 and 4. The Playwright container image tag in Task 7 must match the `@playwright/test` version installed in Task 1 Step 1 and used in Task 4's baseline generation — all three reference the same version deliberately.
