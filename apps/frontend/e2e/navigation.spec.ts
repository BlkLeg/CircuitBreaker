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
  /**
   * The regression test for known_bugs item 1, and the one that would have
   * caught it.
   *
   * Everything above this navigates a cheap page under no load, and every
   * assertion in it passed for the whole eight months item 1 was open. Three
   * conditions have to hold at once before the wedge appears, and the suite
   * recreated none of them:
   *
   * 1. **Navigate away from `/map`, with the topology actually rendered.**
   *    Every wedge ever recorded — 16/40 under throttle here, 15/40 against a
   *    real backend — was a navigation leaving `/map`. The 2026-08-18 attempt
   *    that "could not reproduce" was leaving a `/map` still showing "Loading
   *    maps…", which is why `stubApi` seeds a real `maps` row.
   * 2. **Real router navigation.** `history.pushState` + a synthetic
   *    `popstate` moves the URL without going through `navigate()`, which is
   *    the code path that wraps the update in `React.startTransition` — the
   *    thing that actually breaks. A dock `<NavLink>` click goes through it.
   * 3. **CPU contention.** The transition has to be interrupted to be lost.
   *
   * Held at 6x throttle the wedge rate is ~40% per navigation, so the run
   * below misses a full regression with probability 0.6^12 — about 0.2%. It
   * is not statistical in the way `nav-wedge.spec.ts` is: that spec measures a
   * rate, this one asserts a rate of zero, and any single wedge fails it.
   *
   * Desktop Chromium only, and gated on the project name rather than on
   * `browserName`: the CPU throttle needs CDP, which rules out firefox and
   * webkit, and the `mobile-chrome` project reports `browserName: 'chromium'`
   * while rendering a viewport with no desktop dock to click. That is not a
   * coverage gap — the defect is in React's scheduler, not in any browser's,
   * and it reproduces on every engine once the CPU is contended.
   */
  test('navigating away from the topology does not wedge under CPU load', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'needs CDP throttling and the desktop dock');

    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 6 });
    await stubApi(page);
    await page.goto('/');

    const routeEls = page.locator('[data-route-path]');
    await expect(routeEls).toHaveCount(1, { timeout: 30_000 });
    const renderedRoute = async () => routeEls.first().getAttribute('data-route-path');

    // `/` redirects to `/map`, and under 6x throttle the route element exists
    // while still carrying `/`. Condition (1) is *leaving a rendered topology*,
    // so wait for the redirect to land before the first hop; starting early
    // spends the first navigation leaving a page that was never `/map`.
    await expect.poll(renderedRoute, { timeout: 30_000 }).toBe('/map');

    // Alternates so that every other hop leaves a fully rendered `/map`.
    const JOURNEY = ['/monitors', '/map', '/agents', '/map', '/settings', '/map'];
    const wedged: string[] = [];

    for (let i = 0; i < 12; i += 1) {
      const target = JOURNEY[i % JOURNEY.length];
      const from = await renderedRoute();
      if (from === target) continue;

      // Through the dock, not through pushState — see (2) above. The shelf
      // auto-hides and its icons magnify, so hover the shelf, then the link,
      // and only then click into a target that has stopped moving.
      const link = page.locator(`.macos-dock-link[href="${target}"]`);
      await page.locator('.macos-dock-shelf').hover({ timeout: 20_000 });
      await link.hover({ timeout: 20_000 });
      await link.click({ timeout: 20_000 });

      // A URL that never moved is a click that missed the magnifying icon, not
      // a wedge. The wedge's whole signature is that the URL *does* advance.
      const urlMoved = await page
        .waitForURL((url) => url.pathname === target, { timeout: 4_000 })
        .then(() => true)
        .catch(() => false);
      if (!urlMoved) continue;

      try {
        // Generous: this must separate "wedged" from "slow under 6x throttle",
        // and a cold chunk fetch plus the 150ms exit fade fits many times over.
        await expect.poll(renderedRoute, { timeout: 8_000 }).toBe(target);
      } catch {
        wedged.push(`${from} -> ${target} (URL is ${new URL(page.url()).pathname})`);
        // Stop at the first one. The wedge is permanent — no later navigation
        // recovers from it, so continuing would only append hops made from an
        // already-broken page. Reloading to carry on is what `nav-wedge.spec.ts`
        // does, because it is measuring a rate; this test asserts that the rate
        // is zero, and one is enough to say so.
        break;
      }
    }

    expect(
      wedged,
      'the URL advanced but the rendered route did not, and stayed that way — ' +
        'known_bugs item 1 has ' +
        'reopened. Check that <BrowserRouter> in src/App.jsx still passes ' +
        'useTransitions={false}; the comment there has the measurements. ' +
        `Wedged navigations:\n${wedged.join('\n')}`
    ).toEqual([]);
  });
});
