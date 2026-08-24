import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

// REL-18: reviewed desktop and mobile baselines with deterministic fixtures.
//
// Baselines MUST be generated inside the CI Playwright container, not on a
// developer host — font rendering differs and locally-made baselines will never
// match CI. See the bootstrap command in docs/testing-visual-baselines.md.
//
// Until baselines exist this file runs only under the dedicated `visual-*`
// projects, which the CI browser job does not run (playwright.config.ts gives
// the regular projects a testIgnore for it). That keeps a missing baseline from
// failing an unrelated PR.
const SURFACES = [
  { name: 'topology', path: '/map' },
  { name: 'hardware-empty', path: '/hardware' },
  { name: 'services-empty', path: '/services' },
  { name: 'ipam-empty', path: '/ipam' },
  { name: 'storage-empty', path: '/storage' },
  { name: 'agents-empty', path: '/agents' },
  { name: 'monitors-empty', path: '/monitors' },
  { name: 'discovery-empty', path: '/discovery' },
  { name: 'settings', path: '/settings' },
];

// The header renders a live clock, date and weather widget (HeaderWidgets.jsx:81-85).
// Left alone they change between every run, so every baseline diffs on the
// second hand rather than on layout — and the usual response to a permanently
// red visual gate is to switch it off. Freezing the clock is what makes the
// fixtures deterministic in the sense REL-18 means.
const FROZEN_CLOCK = new Date('2026-01-01T12:00:00Z');

for (const surface of SURFACES) {
  test(`${surface.name} matches its baseline`, async ({ page }) => {
    await page.clock.setFixedTime(FROZEN_CLOCK);
    await stubApi(page);
    await page.goto(surface.path);
    await expect(page.locator('.page-content')).toBeVisible();
    // The route-enter fade is JS-driven (framer-motion), so the style tag below
    // cannot freeze it. Wait for it to settle or the baseline captures a
    // half-transparent page.
    await waitForRouteSettled(page);
    // A screenshot of a crashed page committed as a baseline permanently
    // blesses the crash.
    await expectNoErrorBoundary(page, `visual baseline for ${surface.path}`);

    // Freeze animation so a mid-transition frame never becomes the baseline.
    await page.addStyleTag({
      content: `*, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        caret-color: transparent !important;
      }`,
    });
    await page.waitForTimeout(250);

    await expect(page).toHaveScreenshot(`${surface.name}.png`, { fullPage: true });
  });
}
