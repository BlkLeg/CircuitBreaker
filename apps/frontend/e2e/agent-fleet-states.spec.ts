import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

/**
 * AGT-14 and AGT-17 in a real browser, against a populated fleet.
 *
 * The existing WCAG sweep (accessibility.spec.ts) scans pages with no data, so
 * none of the markup these two requirements add — state chips, drift markers,
 * the filter bar, the summary — is inside any scanned page today. AGT-14's
 * "distinct, unambiguous visual treatment and accessible text" is precisely a
 * claim about that markup, so it is scanned here with real rows rendered.
 *
 * AGT-17's filtering is exercised the same way: through the URL, because a
 * filtered fleet that cannot be reloaded or handed to a colleague is not the
 * "saved URL state" the slice asks for.
 */

const RECENT = new Date(Date.now() - 10_000).toISOString();
const LONG_AGO = new Date(Date.now() - 6 * 3600 * 1000).toISOString();

const GRANT = { host_telemetry: { enabled: true, config: { interval_s: 30 } } };

const ROSTER = [
  {
    id: 1,
    status: 'active',
    hostname: 'edge-01',
    agent_version: '0.9.0',
    fingerprint: 'a'.repeat(32),
    os: 'linux',
    arch: 'amd64',
    last_seen_at: RECENT,
  },
  {
    id: 2,
    status: 'active',
    hostname: 'edge-02',
    agent_version: '0.8.1',
    fingerprint: 'b'.repeat(32),
    os: 'linux',
    arch: 'amd64',
    last_seen_at: RECENT,
  },
  {
    id: 3,
    status: 'active',
    hostname: 'branch-nas',
    agent_version: '0.9.0',
    fingerprint: 'c'.repeat(32),
    os: 'linux',
    arch: 'arm64',
    last_seen_at: LONG_AGO,
  },
  {
    id: 4,
    status: 'active',
    hostname: 'noisy-01',
    agent_version: '0.9.0',
    fingerprint: 'd'.repeat(32),
    os: 'linux',
    arch: 'amd64',
    last_seen_at: RECENT,
  },
];

const PRESENCE = [
  {
    agent_id: 1,
    online: true,
    connected_since: RECENT,
    last_seen_at: RECENT,
    capabilities: GRANT,
    hardware: null,
    latest: { collected_at: RECENT, cpu_pct: 10, mem_pct: 22, root_disk_pct: 40 },
    spool_depth: 0,
  },
  {
    agent_id: 2,
    online: true,
    connected_since: RECENT,
    last_seen_at: RECENT,
    capabilities: GRANT,
    hardware: null,
    latest: { collected_at: RECENT, cpu_pct: 11, mem_pct: 20, root_disk_pct: 41 },
    spool_depth: 0,
  },
  {
    agent_id: 3,
    online: false,
    connected_since: null,
    last_seen_at: LONG_AGO,
    capabilities: GRANT,
    hardware: null,
    latest: null,
    spool_depth: 12,
  },
  {
    agent_id: 4,
    online: true,
    connected_since: RECENT,
    last_seen_at: RECENT,
    capabilities: GRANT,
    hardware: null,
    latest: { collected_at: LONG_AGO, cpu_pct: 9 },
    spool_depth: 4200,
  },
];

const OVERRIDES = { agents: ROSTER, 'agents/presence': PRESENCE, 'agents/metrics/series': [] };

const fleetRow = (page, hostname: string) =>
  page.getByRole('table', { name: 'Fleet' }).getByRole('row', { name: new RegExp(hostname) });

test('a populated fleet states each condition in text, not only in colour', async ({ page }) => {
  await stubApi(page, OVERRIDES);
  await page.goto('/agents');
  await waitForRouteSettled(page);
  await expectNoErrorBoundary(page, 'agents');

  // Offline, and said so in words beside the dot.
  await expect(fleetRow(page, 'branch-nas')).toContainText('offline');

  // Stale telemetry on a machine whose link is still up — the case that read as
  // a healthy green row before AGT-14, because presence and measurement were
  // the same signal.
  const noisy = fleetRow(page, 'noisy-01');
  await expect(noisy).toContainText('online');
  await expect(noisy).toContainText('Stale telemetry');
  // The operator action travels with the state, in the accessible name.
  await expect(noisy).toContainText('What to do:');
  // …and spool pressure alongside it.
  await expect(noisy).toContainText('spool 4200');

  // Version drift, marked on the column an operator is already reading.
  await expect(fleetRow(page, 'edge-02').locator('[data-drift="behind"]')).toContainText('0.8.1');
  await expect(fleetRow(page, 'edge-01').locator('[data-drift]')).toHaveCount(0);
});

test('a filtered fleet can be reloaded straight from its URL', async ({ page }) => {
  await stubApi(page, OVERRIDES);
  await page.goto('/agents');
  await waitForRouteSettled(page);

  await page.getByLabel('Version').selectOption('behind');
  await expect(page).toHaveURL(/drift=behind/);
  await expect(fleetRow(page, 'edge-02')).toBeVisible();
  await expect(fleetRow(page, 'edge-01')).toHaveCount(0);

  // The counts above the table are produced by the same predicate that filtered
  // the rows, so they cannot contradict what is on screen.
  await expect(page.getByText(/1 of 4 agents/)).toBeVisible();

  // Straight from the URL, which is what makes the view shareable.
  await page.goto('/agents?health=attention');
  await waitForRouteSettled(page);
  await expect(fleetRow(page, 'branch-nas')).toBeVisible();
  await expect(fleetRow(page, 'noisy-01')).toBeVisible();
  await expect(fleetRow(page, 'edge-01')).toHaveCount(0);
});

test('the populated fleet has no serious or critical WCAG violations', async ({ page }) => {
  await stubApi(page, OVERRIDES);
  await page.goto('/agents');
  await waitForRouteSettled(page);
  // Same reasoning as accessibility.spec.ts: a colour sampled mid-transition is
  // composited toward the page background and reported as a contrast failure
  // that is not there once the page is still.
  await page.addStyleTag({
    content: `*, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
      transition-delay: 0s !important;
    }`,
  });
  await expectNoErrorBoundary(page, 'a11y scan of a populated /agents');

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  const blocking = results.violations.filter((v) =>
    ['serious', 'critical'].includes(v.impact ?? '')
  );
  const summary = blocking
    .map(
      (v) =>
        `${v.id} (${v.impact}) x${v.nodes.length}: ${v.help}\n    ${v.nodes[0]?.target?.join(' ')}`
    )
    .join('\n');
  expect(blocking, `axe violations on a populated /agents:\n${summary}`).toHaveLength(0);
});
