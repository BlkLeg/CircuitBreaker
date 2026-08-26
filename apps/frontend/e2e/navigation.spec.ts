import { expect, test } from '@playwright/test';
import {
  collectConsoleErrors,
  expectNoErrorBoundary,
  routeWrapper,
  significantErrors,
  stubApi,
} from './fixtures/api';

// known_bugs-v1.0.0-rc.1.md item 1: the URL advances but the route never
// renders until a manual reload. Open since rc.1, high severity, and explicitly
// "not reproducible in jsdom".
//
// The bug report narrowed it to two candidates and asked for one piece of data
// from a running instance: is the new page's markup in the DOM but invisible
// (a wedged framer-motion exit animation), or absent entirely (a route that
// never mounted)? The two assertions below are exactly that diagnostic, so a
// recurrence names its own cause instead of needing a live instance again.
//
// Only non-redirecting routes: '/' -> /map and '/networks' -> /ipam are
// <Navigate> redirects (App.jsx:145,150), so asserting their own URL fails.
const ROUTES = [
  { path: '/hardware' },
  { path: '/services' },
  { path: '/ipam' },
  { path: '/storage' },
  { path: '/agents' },
  { path: '/monitors' },
];

test.describe('client-side navigation completes without a reload', () => {
  for (const route of ROUTES) {
    test(`navigating to ${route.path} renders its content`, async ({ page }) => {
      const errors = collectConsoleErrors(page);
      await stubApi(page);
      await page.goto('/');
      await expect(page.locator('.page-content')).toBeVisible();

      // Client-side navigation, not a fresh document load — a reload is the
      // workaround the bug report describes, so it must not be what makes this
      // pass.
      await page.evaluate((path) => {
        window.history.pushState({}, '', path);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }, route.path);

      // eslint-disable-next-line security/detect-non-literal-regexp -- route.path comes from the literal ROUTES list above, which holds plain slugs with no regex metacharacters
      await expect(page).toHaveURL(new RegExp(`${route.path}$`));

      const content = page.locator('.page-content');
      await expect(
        content,
        'route never mounted — the fix is in AnimatePresence/Suspense'
      ).toBeVisible({ timeout: 10_000 });

      // Measure the element that actually animates. `.page-content` is a
      // static wrapper and is always opacity 1 (App.jsx:127), so asserting on
      // it can never detect a wedged transition — the framer-motion div inside
      // it is what fades 0 -> 1 (App.jsx:135-141). Polled, because the fade
      // takes 150ms and a single read right after mount legitimately sees a
      // value below 0.9.
      await expect
        .poll(
          async () =>
            Number(await routeWrapper(page).evaluate((el) => getComputedStyle(el).opacity)),
          {
            // Same ceiling as waitForRouteSettled, and for the same reason.
            timeout: 15_000,
            message: 'route mounted but stuck at opacity 0 — the fix is in the animation layer',
          }
        )
        .toBeGreaterThan(0.9);

      // The ErrorBoundary renders inside .page-content, so "visible" alone is
      // satisfied by a crashed page. Without this the test passes on a failure.
      await expectNoErrorBoundary(page, `navigating to ${route.path}`);

      const significant = significantErrors(errors);
      expect(significant, `console errors:\n${significant.join('\n')}`).toHaveLength(0);
    });
  }

  test('clicking a nav link advances the rendered page, not just the URL', async ({ page }) => {
    await stubApi(page);
    await page.goto('/');
    await expect(page.locator('.page-content')).toBeVisible();

    const before = await page.locator('.page-content').innerHTML();
    await page
      .getByRole('link', { name: /hardware/i })
      .first()
      .click();

    await expect(page).toHaveURL(/\/hardware$/);
    await expect
      .poll(async () => page.locator('.page-content').innerHTML(), { timeout: 10_000 })
      .not.toBe(before);
    await expectNoErrorBoundary(page, 'after clicking the hardware nav link');
  });
});
