import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

/**
 * Every /api/v1 response the app makes on boot, keyed by the tail of the URL.
 * The list was not guessed — e2e/_probe captured the actual calls across the
 * primary routes. Shapes matter: a page handed `{}` where it expects an array
 * renders its ErrorBoundary ("a.map is not a function") instead of the page,
 * which silently weakens every assertion made against it.
 */
const DEFAULTS: Record<string, unknown> = {
  // Identity and app state
  'auth/me': { id: 1, email: 'operator@example.test', role: 'admin', is_active: true },
  'bootstrap/status': { needs_setup: false, has_admin: true },
  health: { state: 'ready', ready: true, uptime_s: 1, checks: { db: 'ok', redis: 'ok' } },
  capabilities: {},
  settings: { default_environment: '', environments: [], map_default_filters: {} },
  'settings/roles': [],
  timezones: [],

  // Inventory collections
  hardware: [],
  'compute-units': [],
  services: [],
  storage: [],
  networks: [],
  misc: [],
  'external-nodes': [],
  clusters: [],
  docs: [],
  sites: [],
  vlans: [],
  ipam: [],
  environments: [],
  tags: [],
  categories: [],

  // Agents
  agents: [],
  'agents/presence': [],
  'agents/metrics/series': [],
  'agents/install-command': { command: 'curl -fsSL https://example.test/install.sh | sh' },

  // Monitoring and discovery
  monitors: [],
  // GET /monitors/overview returns a LIST (api/monitor.py returns
  // filter_readable_monitors(...)), not a summary object.
  'monitors/overview': [],
  'discovery/status': { running: false, jobs: [] },
  notifications: [],
  certificates: [],

  // Topology
  topologies: [],
  // NOT []: useMapTabs (hooks/useMapTabs.js:15-22) reacts to an empty list by
  // POSTing mapsApi.create('Main') and reading `.id` off the response. The
  // catch-all answers that POST with [], so activeMapId becomes undefined and
  // MapPage.jsx:2997 sits on "Loading maps…" forever. Every /map assertion —
  // the a11y scan included — was then measuring a loading placeholder rather
  // than the topology page.
  maps: [{ id: 1, name: 'Main', is_default: true }],
  graph: { nodes: [], edges: [] },
  'graph/topology': { nodes: [], edges: [] },
};

export async function stubApi(page: Page, overrides: Record<string, unknown> = {}): Promise<void> {
  const responses = { ...DEFAULTS, ...overrides };

  // WebSockets are not reachable through page.route — five hooks open them
  // (useDiscoveryStream, useAgentLive, useTelemetryStream, useMonitorStream,
  // useTopologyStream). Accepting and holding them keeps the client's reconnect
  // loop quiet; without this the console fills with handshake failures.
  await page.routeWebSocket('**/api/v1/**', () => {
    /* accept the connection and send nothing */
  });

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
      // Unknown endpoints default to an empty collection, not {}: nearly
      // every unstubbed call is a list, and {} makes pages throw
      // "a.map is not a function" and render their ErrorBoundary.
      body: JSON.stringify(key ? responses[key] : []),
    });
  });

  // HeaderWidgets.jsx:60,103 calls open-meteo.com directly — not through
  // /api/v1, so the handler above never sees it. Left unstubbed the suite
  // reaches the public internet on every page load: non-hermetic (it hangs or
  // fails on a network-restricted runner), and it bakes the live temperature
  // into every screenshot baseline.
  await page.route('**://*.open-meteo.com/**', (route) => {
    const isGeocoding = route.request().url().includes('geocoding-api');
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        isGeocoding
          ? { results: [{ latitude: 33.4484, longitude: -112.074, name: 'Phoenix' }] }
          : { current: { temperature_2m: 72, weather_code: 0 } }
      ),
    });
  });

  // Registered AFTER the general handler on purpose: Playwright tries the most
  // recently added route first, so this is what actually catches SSE. An
  // EventSource served application/json aborts with a console error.
  await page.route('**/api/v1/**/stream**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
  );
}

/** Console errors and page exceptions, for ACC-09's "console clean" assertion. */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(String(err)));
  return errors;
}

/**
 * Noise that is not a product defect: a missing favicon in the preview server,
 * and the benign ResizeObserver loop notice browsers emit for legitimate
 * observer-driven layout. Filtered by name rather than by count, so a real
 * error is never absorbed by a threshold.
 */
export function significantErrors(errors: string[]): string[] {
  return errors.filter((e) => !/favicon|ResizeObserver loop|Failed to load resource.*404/i.test(e));
}

/**
 * Assert the page is not showing its ErrorBoundary.
 *
 * Worth its own helper because the boundary renders INSIDE `.page-content`: a
 * test that only checks `.page-content` is visible passes just as happily on a
 * crashed page as on a working one. That is how the first version of
 * navigation.spec.ts passed while /hardware was actually throwing
 * "a.map is not a function".
 */
export async function expectNoErrorBoundary(page: Page, context: string): Promise<void> {
  const text = await page.locator('.page-content').innerText();
  if (/Something went wrong|An unexpected error occurred/i.test(text)) {
    throw new Error(`${context}: page rendered its ErrorBoundary:\n${text.slice(0, 400)}`);
  }
}

/**
 * Wait for the route-enter animation to finish before measuring anything.
 *
 * `.page-content` (App.jsx:127) is a static wrapper and is always opacity 1.
 * The element that actually animates is the `motion.div` inside it, which
 * fades 0 -> 1 over 150ms on every route change (App.jsx:135-141). Anything
 * that samples colour during that window sees every pixel composited toward
 * the page background: an axe scan 27ms in measured `.entity-table th` as
 * #454341 on #2f2e2d (1.37:1) when the settled values are #c8bfb0 on #504945
 * (4.85:1, passing). That is a spurious violation, and with CI retries it
 * shows up as an unexplained flake rather than a failure.
 *
 * Returns the settled wrapper so callers can assert against it directly.
 */
export function routeWrapper(page: Page) {
  return page.locator('.page-content > div').first();
}

/**
 * 15s, not the 150ms the fade actually takes. The animation is rAF-driven, so
 * it does not advance while the browser is starved — and with six projects
 * running two workers each, alongside full-page screenshot capture, WebKit was
 * observed sitting at opacity 0 for more than five seconds on /map, the
 * heaviest route. A wedged AnimatePresence never resolves at all, so a longer
 * ceiling still catches the known_bugs #1 symptom this assertion exists for;
 * it only stops a slow machine from being reported as a wedge.
 */
const ROUTE_SETTLE_TIMEOUT_MS = 15_000;

export async function waitForRouteSettled(page: Page): Promise<void> {
  const wrapper = routeWrapper(page);
  await wrapper.waitFor({ state: 'visible' });
  await expect
    .poll(async () => Number(await wrapper.evaluate((el) => getComputedStyle(el).opacity)), {
      timeout: ROUTE_SETTLE_TIMEOUT_MS,
      message: 'route wrapper never reached opacity 1 — see known_bugs item 1',
    })
    .toBeGreaterThan(0.99);
}
