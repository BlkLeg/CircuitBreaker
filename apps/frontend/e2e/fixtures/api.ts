import type { Page } from '@playwright/test';

/**
 * Every /api/v1 response the app needs to boot and route, keyed by the tail of
 * the URL. A request with no entry gets an empty object, so a newly added boot
 * call degrades to "empty state" rather than an unhandled rejection that fails
 * an unrelated assertion.
 */
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
  'monitors/overview': { total: 0, up: 0, down: 0, paused: 0, monitors: [] },
  'discovery/status': { running: false, jobs: [] },
  notifications: [],
  certificates: [],

  // Topology
  topologies: [],
  maps: [],
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
