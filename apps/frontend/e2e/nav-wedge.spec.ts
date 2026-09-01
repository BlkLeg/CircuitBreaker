import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { stubApi } from './fixtures/api';

/**
 * Route §4.3's scripted journey, run under CPU throttle, counting wedges.
 *
 * Three things about this harness are deliberate and were wrong in an earlier
 * revision, so they are worth stating plainly.
 *
 * **Navigation goes through the UI, not through `history.pushState`.** The
 * earlier version pushed a URL and dispatched a synthetic `PopStateEvent`. Its
 * recorded evidence showed why that is not good enough: for both captured
 * wedges the diagnostics buffer held *no nav entry at all* for the target path,
 * meaning React Router never processed the navigation — the URL had moved
 * because `pushState` moved it directly. That is a stuck harness, not a stuck
 * router, and it was written up as "the requested navigation remains pending",
 * which the evidence did not show. Clicking a dock link (MacOSDOCK.jsx) goes
 * through a real `<NavLink>` and so through the router's own `navigate()`,
 * which is the code path react-router v7 wraps in `startTransition` and
 * therefore the one hypothesis H1 is about.
 *
 * **The rendered route is found by `[data-route-path]`, not by position.** The
 * earlier selector was `.page-content > div` first-child, which is the
 * `<UpdateBanner>` when an update is available and the Suspense `LoadingScreen`
 * whenever a chunk is in flight. In either case it has no `data-route-path`, so
 * every navigation in the run would have been counted as a wedge with nothing
 * in the output to indicate the selector had missed.
 *
 * **A missing nav entry is evidence, not an excuse to discard the sample.** Once
 * `navigateByUi` has proven the URL moved, the router was definitely asked to
 * navigate — so a `useLocation` that never updated is the defect, not a bad
 * measurement. A revision that treated it as a harness fault threw away 40% of
 * its own findings, including every instance of the branch the known bug
 * describes. It is now a wedge, sub-classified by `WedgeBranch`.
 *
 * The report separates outcomes rather than collapsing them into pass/fail: a
 * wedge (URL advanced, outgoing page still on screen), a visible loading
 * fallback (slow but behaving correctly — the wedge's whole signature is that no
 * fallback appears), and a UI failure to even deliver the click. Only the first
 * is a wedge, and every wedge names which branch of §4.4 it took.
 */

// Route §4.3's journey. The page is already on /map before the loop, so the
// first step must not be /map: counting /map -> /map as a navigation would
// manufacture one wedge per repeat without a route change ever happening.
// Every path here is in the dock (MacOSDOCK.jsx), which is what the harness
// clicks.
const JOURNEY = ['/monitors', '/map', '/agents', '/settings', '/map'];

const REPEATS = Number.parseInt(process.env.NAV_WEDGE_REPEATS || '30', 10);
const CPU_THROTTLE_RATE = 6;

// Longer than the 150 ms exit fade plus a cold chunk fetch by a wide margin, so
// "slow" and "wedged" are not the same measurement. A navigation still
// unresolved after this is not merely behind.
const WEDGE_TIMEOUT_MS = 5_500;

// Reaching the dock link is UI work, not navigation work; if it will not happen
// under throttle that is a fault to record separately, never a wedge to count.
const CLICK_TIMEOUT_MS = 10_000;

type Outcome = 'ok' | 'wedge' | 'fallback' | 'ui-failure';

/**
 * Which §4.4 branch a wedge took, decided from the recorded evidence.
 *
 * - `router-location-never-updated` — the URL moved but `useLocation` never
 *   did, so no nav entry opened and the lazy import never even started. That is
 *   H1's mechanism: react-router v7 wraps `navigate()` in
 *   `React.startTransition`, and React withholds a transition's location update
 *   from *every* consumer until it can commit without showing a fallback.
 * - `incoming-route-never-mounted` — the router updated and the nav entry is
 *   still `pending`, so the route was being rendered and never committed.
 * - `outgoing-route-never-removed` — the nav entry closed (the incoming route
 *   did mount) yet the outgoing element is still in the DOM: framer-motion's
 *   exit animation did not finish. §4.4 sends this back to the AnimatePresence
 *   question rather than to H1.
 */
type WedgeBranch =
  | 'router-location-never-updated'
  | 'incoming-route-never-mounted'
  | 'outgoing-route-never-removed';

interface NavigationRecord {
  navigation: number;
  target: string;
  outcome: Outcome;
  /** Set only for a wedge; which §4.4 branch the evidence selects. */
  branch: WedgeBranch | null;
  /** Why the click could not be delivered, when that is what went wrong. */
  uiFailure: string | null;
  /** What the first `[data-route-path]` held when the attempt ended. */
  renderedRoute: string | null;
  /** Every route element in the DOM; more than one means an exit never finished. */
  renderedRoutes: string[];
  /** Whether React Router opened a nav entry for the target at all. */
  routerSawNavigation: boolean;
  /** Whether that nav entry closed — i.e. the incoming route actually mounted. */
  targetNavClosed: boolean;
  /** Chunk fetches still in flight at the moment of failure — §4.4's H1 branch. */
  pendingChunks: string[];
  diagnostics: unknown;
}

/** The element that actually carries the route: the keyed framer-motion div. */
function renderedRouteLocator(page: Page): Locator {
  return page.locator('[data-route-path]').first();
}

async function readRenderedRoute(locator: Locator): Promise<string | null> {
  if ((await locator.count()) === 0) return null;
  return locator.getAttribute('data-route-path');
}

/**
 * Every route element currently in the DOM, outgoing first.
 *
 * With `AnimatePresence mode="wait"` there should only ever be one. Two means
 * the outgoing page's exit animation has not completed and framer-motion has
 * not removed it — which is §4.4's third YES branch ("React committed but old
 * tree visible → framer-motion exit never completed"), and a different finding
 * from a chunk that never arrived. Recording only the first element would hide
 * the distinction behind a single value that looks the same either way.
 */
async function readRenderedRoutes(page: Page): Promise<string[]> {
  return page
    .locator('[data-route-path]')
    .evaluateAll((elements) =>
      elements.map((element) => element.getAttribute('data-route-path') ?? '')
    );
}

/**
 * How long to wait for the URL to move after a click before deciding the click
 * was never delivered. A wedge's whole signature is that the URL advances and
 * the render does not, so a URL that never moves is a click that missed — the
 * dock magnifies under the cursor, and under 6x throttle a link can shift
 * between Playwright judging it stable and the click landing.
 */
const URL_SETTLE_TIMEOUT_MS = 2_000;

/** Clicks that missed, retried before giving up. */
const CLICK_ATTEMPTS = 2;

/**
 * Navigate the way a user does: click the route's dock icon.
 *
 * The dock (MacOSDOCK.jsx) is the app's primary navigation and its entries are
 * real `<NavLink>`s, so a click here goes through react-router's own
 * `navigate()` — the code path v7 wraps in `React.startTransition`, and
 * therefore the one hypothesis H1 is about. The header's route menu was the
 * first choice and is not usable: a `HeaderWidgets` element overlaps the menu
 * button at the default viewport and intercepts the click.
 *
 * The shelf auto-hides, so hover it before reaching for a link. Matching on the
 * `href` rather than the label keeps this independent of translation.
 *
 * Returns whether the URL actually moved. A click Playwright reports as
 * delivered is not necessarily a click the link received: the dock magnifies
 * under the cursor, and at 6x throttle a link can shift between being judged
 * stable and the pointer landing. Since a wedge is defined by the URL advancing
 * while the render does not, a URL that never moves is proof the router was
 * never asked — a distinct failure that must not be counted as a wedge.
 */
async function navigateByUi(page: Page, path: string): Promise<boolean> {
  const link = page.locator(`.macos-dock-link[href="${path}"]`);
  for (let attempt = 0; attempt < CLICK_ATTEMPTS; attempt += 1) {
    await page.locator('.macos-dock-shelf').hover({ timeout: CLICK_TIMEOUT_MS });
    // Hover the link itself first and let the magnification settle, rather than
    // clicking into a target that is still moving.
    await link.hover({ timeout: CLICK_TIMEOUT_MS });
    await link.click({ timeout: CLICK_TIMEOUT_MS });
    try {
      await page.waitForURL((url) => url.pathname === path, {
        timeout: URL_SETTLE_TIMEOUT_MS,
      });
      return true;
    } catch {
      // The URL never moved, so this click missed. Try once more before
      // recording it as undeliverable.
    }
  }
  return false;
}

test('records the navigation wedge rate under 6x CPU throttle', async ({
  page,
  browserName,
}, testInfo) => {
  expect(browserName, 'nav-wedge project requires Chromium for CDP throttling').toBe('chromium');
  const cdp = await page.context().newCDPSession(page);
  // This is controlled Chromium pressure, not a claim that it is equivalent
  // to the historical Firefox-under-host-contention reproduction.
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_THROTTLE_RATE });
  await stubApi(page);
  await page.goto('/');
  await expect(renderedRouteLocator(page)).toHaveCount(1, { timeout: 30_000 });

  let navigations = 0;
  const records: NavigationRecord[] = [];

  for (let repeat = 0; repeat < REPEATS; repeat += 1) {
    for (const target of JOURNEY) {
      navigations += 1;

      let uiFailure: string | null = null;
      try {
        const urlAdvanced = await navigateByUi(page, target);
        if (!urlAdvanced) {
          uiFailure = `the dock link for ${target} was clicked but the URL never moved`;
        }
      } catch (err) {
        uiFailure =
          err instanceof Error ? `${err.name}: reaching the dock link for ${target}` : 'Error';
      }

      const rendered = renderedRouteLocator(page);
      let settled = false;
      if (uiFailure === null) {
        try {
          await expect
            .poll(
              async () => {
                if ((await rendered.count()) === 0) return false;
                const routePath = await rendered.getAttribute('data-route-path');
                if (routePath !== target) return false;
                const opacity = Number(
                  await rendered.evaluate((el) => getComputedStyle(el).opacity)
                );
                return opacity > 0.99;
              },
              { timeout: WEDGE_TIMEOUT_MS }
            )
            .toBe(true);
          settled = true;
        } catch {
          settled = false;
        }
      }

      if (settled) continue;

      const diagnostics = await page.evaluate(() => window.__cbDiagnostics?.getEntries?.() ?? []);
      const renderedRoute = await readRenderedRoute(rendered);
      const renderedRoutes = await readRenderedRoutes(page);
      const entries = Array.isArray(diagnostics) ? (diagnostics as Record<string, unknown>[]) : [];

      const targetNavs = entries.filter((entry) => entry.kind === 'nav' && entry.path === target);
      const routerSawNavigation = targetNavs.length > 0;
      const targetNavClosed = targetNavs.some((entry) => entry.pending === false);
      const pendingChunks = entries
        .filter((entry) => entry.kind === 'chunk' && entry.pending === true)
        .map((entry) => String(entry.chunk));

      // `uiFailure` is the *only* harness fault, and `navigateByUi` has already
      // proven the URL moved before this point. A missing nav entry is
      // therefore evidence about the product, not about the click: with a real
      // `<NavLink>` the router was definitely asked to navigate, so a location
      // update that never reached `useLocation` is the defect itself. An
      // earlier revision classified that as a harness fault and discarded 40%
      // of its own findings.
      let outcome: Outcome;
      let branch: WedgeBranch | null = null;
      if (uiFailure !== null) {
        outcome = 'ui-failure';
      } else if (renderedRoute === null) {
        // No route element at all: the shared Suspense fallback is on screen.
        // Slow, but the user can see that something is happening, which is the
        // opposite of the wedge's signature.
        outcome = 'fallback';
      } else {
        outcome = 'wedge';
        if (!routerSawNavigation) {
          branch = 'router-location-never-updated';
        } else if (!targetNavClosed) {
          branch = 'incoming-route-never-mounted';
        } else {
          branch = 'outgoing-route-never-removed';
        }
      }

      records.push({
        navigation: navigations,
        target,
        outcome,
        branch,
        uiFailure,
        renderedRoute,
        renderedRoutes,
        routerSawNavigation,
        targetNavClosed,
        pendingChunks,
        diagnostics,
      });
      await page.screenshot({
        path: testInfo.outputPath(`${outcome}-${navigations}.png`),
        fullPage: true,
      });
      // Reload is the known workaround and lets the statistical run continue.
      await page.reload();
      await expect(renderedRouteLocator(page)).toHaveCount(1, { timeout: 30_000 });
    }
  }

  const wedges = records.filter((record) => record.outcome === 'wedge');
  const report = {
    schema_version: 3,
    repeats: REPEATS,
    navigations,
    wedges: wedges.length,
    wedge_rate: navigations ? wedges.length / navigations : 0,
    // Reported beside the wedge rate rather than folded into it: a run with a
    // high ui_failures count measured the harness, not the product, and the
    // number is worthless without that context.
    fallbacks: records.filter((record) => record.outcome === 'fallback').length,
    ui_failures: records.filter((record) => record.outcome === 'ui-failure').length,
    // The §4.4 branch each wedge took, counted. This is the output the
    // investigation actually consumes — a bare wedge rate says a problem exists
    // without saying which of three different problems it is.
    wedges_by_branch: {
      'router-location-never-updated': wedges.filter(
        (record) => record.branch === 'router-location-never-updated'
      ).length,
      'incoming-route-never-mounted': wedges.filter(
        (record) => record.branch === 'incoming-route-never-mounted'
      ).length,
      'outgoing-route-never-removed': wedges.filter(
        (record) => record.branch === 'outgoing-route-never-removed'
      ).length,
    },
    // A chunk still in flight at wedge time is §4.4's literal H1 condition.
    wedges_with_pending_chunk: wedges.filter((record) => record.pendingChunks.length > 0).length,
    // Two route elements at once means framer-motion never finished the
    // outgoing page's exit.
    wedges_with_two_route_elements: wedges.filter((record) => record.renderedRoutes.length > 1)
      .length,
    evidence: records,
  };

  const body = Buffer.from(`${JSON.stringify(report, null, 2)}\n`);
  const reportPath = testInfo.outputPath('wedge-rate.json');
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- Playwright constructs this path inside the current test's artifact directory; no page/user input contributes to it
  await writeFile(reportPath, body);
  await testInfo.attach('wedge-rate.json', { path: reportPath, contentType: 'application/json' });
  console.log(
    `NAV_WEDGE_RESULT ${JSON.stringify({
      navigations,
      wedges: report.wedges,
      wedge_rate: report.wedge_rate,
      fallbacks: report.fallbacks,
      ui_failures: report.ui_failures,
      wedges_by_branch: report.wedges_by_branch,
      wedges_with_pending_chunk: report.wedges_with_pending_chunk,
      wedges_with_two_route_elements: report.wedges_with_two_route_elements,
    })}`
  );
});
