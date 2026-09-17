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

  // Metric alert rules. Full MetricAlertRuleOut shape (schemas/metric_alerts.py):
  // the panel reads assessment and open_incident_id off each row, and an array
  // missing them would render the table but lie about every rule's state. Two
  // rules so the scan sees a firing row with its incident handle and a
  // not-evaluating row with its hint, not one lonely Normal.
  // Two parked rows so the scan sees an actionable row with its buttons and a
  // resolved one with its stamp, rather than an empty state that exercises no
  // table markup at all.
  'failed-messages': [
    {
      id: 1,
      stream: 'CB_MONITOR',
      subject: 'monitor.result',
      consumer: 'monitor-poll',
      error: 'ValueError: expected a dict, got list',
      delivered_count: 5,
      parked_at: '2026-09-17T10:00:00Z',
      requeued_at: null,
      discarded_at: null,
    },
    {
      id: 2,
      stream: 'CB_DISCOVERY',
      subject: 'discovery.enrich',
      consumer: 'discovery-reconciler',
      error: 'TimeoutError: enrichment did not answer in 30s',
      delivered_count: 5,
      parked_at: '2026-09-17T09:00:00Z',
      requeued_at: '2026-09-17T09:30:00Z',
      discarded_at: null,
    },
  ],
  'monitors/alert-rules': [
    {
      id: 1,
      name: 'CPU hot',
      target_type: 'hardware',
      target_id: 30,
      metric_key: 'cpu_pct',
      source: null,
      comparator: '>',
      threshold: 90,
      unit: '%',
      breach_duration_s: 300,
      recovery_threshold: 80,
      recovery_duration_s: 300,
      max_gap_s: 180,
      freshness_s: 180,
      enabled: true,
      severity: 'critical',
      sink_id: 2,
      revision: 1,
      created_at: '2026-09-17T10:00:00Z',
      updated_at: '2026-09-17T10:00:00Z',
      assessment: 'firing',
      open_incident_id: 'inc-e2e-1',
    },
    {
      id: 2,
      name: 'Disk filling',
      target_type: 'hardware',
      target_id: 31,
      metric_key: 'disk_pct',
      source: null,
      comparator: '>=',
      threshold: 85,
      unit: '%',
      breach_duration_s: 300,
      recovery_threshold: 75,
      recovery_duration_s: 300,
      max_gap_s: 300,
      freshness_s: 300,
      enabled: true,
      severity: 'warning',
      sink_id: 2,
      revision: 1,
      created_at: '2026-09-17T10:00:00Z',
      updated_at: '2026-09-17T10:00:00Z',
      assessment: 'unknown',
      open_incident_id: null,
    },
  ],
  // MetricDefinition per metric_catalog.py — five hardware gauges, each with
  // its own unit, comparators and freshness/gap defaults.
  'monitors/alert-rules/catalog': [
    {
      key: 'cpu_pct',
      label: 'CPU utilization',
      unit: '%',
      comparators: ['>', '>=', '<', '<='],
      target_types: ['hardware'],
      default_freshness_s: 180,
      default_max_gap_s: 180,
    },
    {
      key: 'mem_pct',
      label: 'Memory utilization',
      unit: '%',
      comparators: ['>', '>=', '<', '<='],
      target_types: ['hardware'],
      default_freshness_s: 180,
      default_max_gap_s: 180,
    },
    {
      key: 'disk_pct',
      label: 'Disk utilization',
      unit: '%',
      comparators: ['>', '>=', '<', '<='],
      target_types: ['hardware'],
      default_freshness_s: 300,
      default_max_gap_s: 300,
    },
    {
      key: 'temp_c',
      label: 'Temperature',
      unit: '°C',
      comparators: ['>', '>=', '<', '<='],
      target_types: ['hardware'],
      default_freshness_s: 180,
      default_max_gap_s: 180,
    },
    {
      key: 'power_w',
      label: 'Power',
      unit: 'W',
      comparators: ['>', '>=', '<', '<='],
      target_types: ['hardware'],
      default_freshness_s: 180,
      default_max_gap_s: 180,
    },
  ],
  // SinkOut (schemas/notifications.py): the rules panel reads id/name/enabled
  // to decide whether the New rule / Enable flow is possible at all.
  'notifications/sinks': [
    { id: 2, name: 'Slack', provider_type: 'webhook', provider_config: {}, enabled: true },
  ],

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

  // Intelligence. The fleet stub must be the full FleetAssessment shape, not
  // the [] the catch-all would answer an unknown endpoint with: the hook
  // reads data.rows and data.summary off it, and an array would crash the
  // console into its ErrorBoundary before the a11y scan could see the page.
  'cve/fleet': {
    feed: { state: 'ready', reason_code: 'ready', generation: 'gen-e2e', age_seconds: 60 },
    assessed_at: '2026-09-17T10:00:00Z',
    summary: {
      total_entities: 1,
      by_state: { completed: 1 },
      entities_with_findings: 0,
      findings_total: 0,
      by_severity: {},
    },
    rows: [
      {
        entity_type: 'hardware',
        entity_id: 1,
        name: 'nas-01',
        state: 'completed',
        reason_code: 'completed',
        identity: {
          vendor: 'acme',
          product: 'widget',
          version: '1.9',
          provenance: 'inventory',
          revision: 0,
        },
        finding_count: 0,
        max_severity: null,
        max_cvss: null,
        completeness: 'complete',
      },
    ],
    limits: {
      identity_limit: 250,
      identities_total: 1,
      identities_assessed: 1,
      identity_limit_reached: false,
      candidate_limited_products: [],
    },
  },
  'cve/entity': {
    state: 'completed',
    reason_code: 'completed',
    identity: null,
    findings: [],
    limitations: [],
    assessed_at: '2026-09-17T10:00:00Z',
    completeness: 'complete',
    total: 0,
  },
  'cve/status': { enabled: true, total_entries: 1, feed: { state: 'ready' } },
  'intel/flap-incidents': [],
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

  // EventSource is not reachable through page.route either: fulfilling
  // /api/v1/events/stream with JSON makes the browser fail the connection, so
  // `sseClient` reports disconnected and `ConnectionStatus` renders its
  // "Reconnecting to live data..." banner once its 5s grace timer elapses.
  // That banner shifts the whole page, and whether it had appeared by
  // screenshot time depended on how long the page took to settle — which is
  // what made the agents and monitors visual baselines flap. Substituting an
  // EventSource that opens and stays quiet is the SSE equivalent of the
  // WebSocket stub above.
  await page.addInitScript(() => {
    class QuietEventSource extends EventTarget {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readyState = 1;
      onopen: ((this: unknown, ev: Event) => unknown) | null = null;
      onerror: ((this: unknown, ev: Event) => unknown) | null = null;
      onmessage: ((this: unknown, ev: Event) => unknown) | null = null;
      constructor(readonly url: string) {
        super();
        // Asynchronous so the caller can assign onopen first.
        queueMicrotask(() => this.onopen?.call(this, new Event('open')));
      }
      close() {
        this.readyState = 2;
      }
    }
    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      writable: true,
      value: QuietEventSource,
    });
  });

  // The UI's fonts are self-hosted (`public/fonts`, declared in
  // `styles/fonts.css`), so nothing here should reach a font CDN at all. These
  // routes are a backstop, not a workaround: if a regression reintroduces a
  // fonts.googleapis.com <link>, they stop the suite going non-hermetic and
  // flaking on whether the round-trip beat the screenshot — which is exactly
  // what it used to do. `no-third-party-fonts.spec.ts` is the loud half; this
  // is the quiet one.
  //
  // Fulfilled rather than aborted: an aborted request logs
  // "Failed to load resource: net::ERR_FAILED", which the smoke and navigation
  // specs correctly treat as a console error.
  await page.route('https://fonts.googleapis.com/**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  await page.route('https://fonts.gstatic.com/**', (route) =>
    route.fulfill({ status: 200, contentType: 'font/woff2', body: '' })
  );

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
      // eslint-disable-next-line security/detect-object-injection -- key is an Object.keys(responses) entry selected two statements above, so it is always an own key of responses
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
