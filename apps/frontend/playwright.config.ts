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
export default defineConfig({
  testDir: './e2e',
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
    baseURL: 'http://127.0.0.1:4173',
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
      testIgnore: /visual\.spec\.ts/,
    },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] }, testIgnore: /visual\.spec\.ts/ },
    { name: 'webkit', use: { ...devices['Desktop Safari'] }, testIgnore: /visual\.spec\.ts/ },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
      testIgnore: /visual\.spec\.ts/,
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
  ],
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
