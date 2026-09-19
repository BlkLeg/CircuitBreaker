import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

/**
 * Every settings tab renders, and an edit still reaches the server.
 *
 * Written when `SettingsPage` was split from one 1,886-line file into a shell
 * plus one component per tab. The Vitest suite had three tests for the whole
 * page, so nothing there would have caught a tab that renders blank because a
 * prop the extracted component needs was not passed down — a mistake that costs
 * nothing to make and shows up only in a browser.
 *
 * Each tab is asserted on its own heading rather than on any field: the point is
 * that the component mounted at all, and asserting on field labels would make
 * this fail every time a setting is reworded.
 */

const TABS = [
  { id: 'general', heading: 'General' },
  { id: 'appearance', heading: 'Appearance' },
  { id: 'resources', heading: 'Resources' },
  { id: 'device-roles', heading: 'Device Roles' },
  { id: 'connectivity', heading: 'Connectivity' },
  { id: 'integrations', heading: 'Integrations' },
  { id: 'security', heading: 'Security' },
  { id: 'system', heading: 'System' },
];

const SETTINGS = {
  theme: 'dark',
  default_environment: 'prod',
  environments: ['prod', 'staging'],
  categories: ['app'],
  map_default_filters: {},
  show_page_hints: true,
  session_timeout_minutes: 60,
  agent_endpoints: [],
};

/**
 * Endpoints the settings tabs read that the shared fixture's catch-all does not
 * cover. The catch-all answers unknown paths with `[]`, which is right for the
 * collections it was written for and wrong for these two: `HostStatsPanel`
 * reads `stats.mem.used` and `DiscoveryReadinessPanel` calls
 * `readiness.capabilities.some(...)`, so `[]` makes both throw into the
 * ErrorBoundary before any assertion here is reached.
 */
const EXTRA = {
  'system/stats': {
    cpu_pct: 12.5,
    mem: { used: 4 * 1024 ** 3, total: 16 * 1024 ** 3 },
    disk: { used: 100 * 1024 ** 3, total: 500 * 1024 ** 3, percent: 20 },
    net: { bytes_recv: 1024 ** 3, bytes_sent: 1024 ** 3 },
  },
  'discovery/readiness': { helper_installed: true, capabilities: [] },
};

test.describe('settings tabs', () => {
  for (const { id, heading } of TABS) {
    test(`the ${id} tab mounts and renders its own content`, async ({ page }) => {
      await stubApi(page, { settings: SETTINGS, ...EXTRA });
      await page.goto(`/settings?tab=${id}`);
      await waitForRouteSettled(page);

      await expectNoErrorBoundary(page, `settings tab ${id}`);
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
      // A tab whose component failed to receive a prop it dereferences throws
      // into the ErrorBoundary, which the check above catches. A tab that merely
      // rendered nothing does not, so the panel is also required to have put
      // *something* interactive on the page. `.first()` is not used: some tabs
      // open with their first control inside a collapsed section, and a hidden
      // first control is not a blank tab.
      await expect(
        page.locator('main').locator('input, select, button, [role="switch"]')
      ).not.toHaveCount(0);
    });
  }

  test('an edit on the General tab is saved through the action bar', async ({ page }) => {
    const saved: unknown[] = [];
    await stubApi(page, { settings: SETTINGS, ...EXTRA });
    // Registered after stubApi so it wins: Playwright tries the newest route first.
    await page.route('**/api/v1/settings', async (route) => {
      if (route.request().method() === 'PUT' || route.request().method() === 'PATCH') {
        saved.push(route.request().postDataJSON());
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SETTINGS),
      });
    });

    await page.goto('/settings?tab=general');
    await waitForRouteSettled(page);

    // The action bar's own button, by its exact label: several sections render
    // a "Save" of their own, and matching /save/i would let this pass on one of
    // those without the page-level save cycle ever running.
    const save = page.getByRole('button', { name: 'Save Changes' });

    // The map title: a plain text field, so the edit is unambiguous and the
    // assertion below can name the value that has to reach the server.
    const title = page.locator('main input[type="text"]').first();
    await title.fill('Lab topology');

    await expect(save).toBeEnabled();
    await save.click();

    await expect.poll(() => saved.length, { timeout: 5000 }).toBeGreaterThan(0);
    expect(saved[0]).toMatchObject({ map_title: 'Lab topology' });
    await expectNoErrorBoundary(page, 'settings save');
  });
});
