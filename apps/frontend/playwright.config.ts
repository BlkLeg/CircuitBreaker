import { defineConfig, devices } from '@playwright/test';

// REL-17: E2E must run against production builds, not the dev server. The dev
// server's on-demand transform hides exactly the class of bug this suite exists
// to catch — lazy chunks that only fail to resolve after a real build, which is
// what known_bugs item 1 turned out to be about.
//
// The API is stubbed at the network layer (see e2e/fixtures/api.ts) rather than
// run for real: the app's client uses a relative baseURL of '/api/v1', so
// page.route intercepts everything without a config change. That keeps this
// suite backend-free and fast enough to gate every PR. Full-stack journeys
// (ACC-05 through ACC-08) need a real backend and are deliberately out of scope.

// The preview port. Overridable because 4173 is a common default and a
// developer host may already have something on it — see
// e2e/fixtures/assert-server-is-ours.ts, which refuses to test a stranger.
const PORT = Number(process.env.CB_E2E_PORT || 4173);

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/fixtures/assert-server-is-ours.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [
        ['junit', { outputFile: 'playwright-report/junit.xml' }],
        ['html', { open: 'never' }],
      ]
    : [['list']],
  timeout: 30_000,
  expect: {
    timeout: 10_000,
    // REL-18: baselines are reviewed artifacts. A small ratio absorbs font
    // antialiasing differences without absorbing real layout drift.
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    // Functional projects. They ignore visual.spec.ts so a missing or stale
    // screenshot baseline cannot fail an unrelated PR — visual regression is
    // opt-in through the visual-* projects below.
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: /(visual|nav-wedge)\.spec\.ts/,
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
      testIgnore: /(visual|nav-wedge)\.spec\.ts/,
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
      testIgnore: /(visual|nav-wedge)\.spec\.ts/,
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
      testIgnore: /(visual|nav-wedge)\.spec\.ts/,
    },

    // REL-18 visual regression. Baselines must be generated in the CI
    // Playwright container (see docs/testing-visual-baselines.md); baselines
    // made on a developer host will not match CI's font rendering.
    {
      name: 'visual-desktop',
      testMatch: /visual\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'visual-mobile',
      testMatch: /visual\.spec\.ts/,
      use: { ...devices['Pixel 5'] },
    },
    // Opt-in diagnostic: deliberately slow and statistical, never part of PR shards.
    {
      name: 'nav-wedge',
      testMatch: /nav-wedge\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], trace: 'on', screenshot: 'on', video: 'on' },
      workers: 1,
      retries: 0,
      timeout: 15 * 60_000,
    },
  ],
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    // Outside CI an already-running preview is reused, which saves a rebuild
    // per run. globalSetup checks that what answers is actually this app, so
    // reuse cannot silently point the whole suite at someone else's server.
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
