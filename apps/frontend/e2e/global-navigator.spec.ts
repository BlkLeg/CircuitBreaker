import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import {
  collectConsoleErrors,
  expectNoErrorBoundary,
  significantErrors,
  stubApi,
  waitForRouteSettled,
} from './fixtures/api';

/**
 * Plan 01's browser evidence for the unified navigator: one overlay from both
 * open mechanisms, durable entity URLs, settings deep links, role filtering,
 * theme reactivity, and the recovery paths (Retry after a failed asset search,
 * a modal handoff that closes the navigator first).
 *
 * Two fixtures matter throughout:
 *  - waitForRouteSettled before any keyboard interaction: /map is the heavy
 *    route this suite's own wedge history comes from, and pressing Ctrl+K into
 *    a page whose chunk is still loading proves nothing about the product.
 *  - every result row is scoped to the dialog: the map page has its own
 *    Storage/Network filter buttons, and an unscoped row locator resolves to
 *    both — a strict-mode failure at best, the wrong button at worst.
 */

const HARDWARE = {
  id: 42,
  name: 'nas-01',
  role: 'server',
  ip_address: '10.0.0.42',
  tags: [],
};

const NETWORK = {
  id: 5,
  name: 'core-sw',
  cidr: '10.0.0.0/24',
  vlan: 10,
  site_id: null,
  tags: [],
};

function hardwareResult() {
  return {
    id: 'hardware-42',
    type: 'hardware',
    title: HARDWARE.name,
    description: 'Primary storage server',
    action_url: '/hardware',
    entity_type: 'hardware',
    entity_id: 42,
  };
}

function networkResult() {
  return {
    id: 'network-5',
    type: 'network',
    title: NETWORK.name,
    description: 'Core switching subnet',
    action_url: '/networks',
    entity_type: 'network',
    entity_id: 5,
  };
}

/** A /search/page payload that returns the given items whatever the query. */
function searchPageResponse(items: unknown[]) {
  return { items, limit: 25, has_more: false };
}

async function openNavigator(page: Page) {
  await page.getByRole('button', { name: 'Open navigator' }).click();
  await expect(page.getByRole('dialog', { name: 'Navigate' })).toBeVisible();
}

async function openNavigatorViaShortcut(page: Page) {
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog', { name: 'Navigate' })).toBeVisible();
}

/** The panel's value of a CSS token, as the browser reports it. */
async function panelToken(page: Page, token: string): Promise<string> {
  return page
    .locator('.navigator-panel')
    .evaluate((el, name) => getComputedStyle(el).getPropertyValue(name).trim(), token);
}

/** Search a query and return the dialog-scoped result rows. */
async function searchInNavigator(page: Page, query: string) {
  const dialog = page.getByRole('dialog', { name: 'Navigate' });
  await dialog.getByRole('searchbox').fill(query);
  return dialog;
}

test.describe('global navigator', () => {
  test.beforeEach(async ({ page }) => {
    await stubApi(page, {
      hardware: [HARDWARE],
      'hardware/42': HARDWARE,
      networks: [NETWORK],
      'networks/5': NETWORK,
      // The fixture matches stub keys by URL prefix, so without these the
      // single-object 'networks/5' entry would answer the drawer's member
      // lists with an object and crash the page into its ErrorBoundary.
      'networks/5/members': [],
      'networks/5/hardware-members': [],
      'search/page': searchPageResponse([hardwareResult()]),
    });
  });

  test('header and shortcut operate one responsive, accessible overlay', async ({
    page,
  }, testInfo) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);

    const dialogs = page.getByRole('dialog', { name: 'Navigate' });
    await expect(dialogs).toHaveCount(1);
    await expect(page.getByRole('button', { name: /All pages/i })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Recent', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Planned/i })).toHaveCount(0);
    await expect(page.getByRole('searchbox')).toBeFocused();

    const box = await dialogs.boundingBox();
    expect(box).not.toBeNull();
    if (testInfo.project.name === 'mobile-chrome') {
      expect(box?.width).toBe(page.viewportSize()?.width);
      expect(box?.height).toBe(page.viewportSize()?.height);
    } else {
      expect(box?.width).toBeLessThanOrEqual(924);
      expect(box?.x).toBeGreaterThan(0);
    }

    // Approved touch targets: 48px route rows, 40px pin controls, and a
    // results region that scrolls locally rather than growing the dialog.
    if (testInfo.project.name !== 'mobile-chrome') {
      const row = dialogs.locator('.navigator-row-main').first();
      await expect(row).toBeVisible();
      const rowBox = await row.boundingBox();
      expect(rowBox?.height).toBeGreaterThanOrEqual(48);
      const pin = dialogs.locator('.navigator-row-pin').first();
      if (await pin.count()) {
        const pinBox = await pin.boundingBox();
        expect(pinBox?.height).toBeGreaterThanOrEqual(40);
      }
      const overflowY = await dialogs
        .locator('.navigator-results')
        .evaluate((el) => getComputedStyle(el).overflowY);
      expect(['auto', 'scroll']).toContain(overflowY);
    }

    // Focus never leaves the panel while tabbing through it.
    for (let i = 0; i < 25; i += 1) await page.keyboard.press('Tab');
    expect(
      await page.evaluate(() =>
        document.querySelector('.navigator-panel')?.contains(document.activeElement)
      )
    ).toBe(true);

    // Review scaffolding is absent: no prototype modes, no external links.
    await expect(dialogs.locator('a[href^="http"]')).toHaveCount(0);

    const axe = await new AxeBuilder({ page })
      .include('.navigator-panel')
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze();
    expect(
      axe.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))
    ).toEqual([]);

    await page.keyboard.press('Escape');
    await expect(dialogs).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Open navigator' })).toBeFocused();

    await page.keyboard.press('Control+k');
    await expect(dialogs).toHaveCount(1);
    await page.keyboard.press('Control+k');
    await expect(dialogs).toHaveCount(0);
    await expectNoErrorBoundary(page, 'global navigator shell');
    expect(significantErrors(errors)).toEqual([]);
  });

  test('an asset result opens durable detail URL state', async ({ page }) => {
    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);
    await page.getByRole('searchbox').fill('nas-01');
    const asset = page.getByRole('button', { name: /nas-01/i });
    await expect(asset).toBeVisible();
    await asset.click();

    await expect(page).toHaveURL(/\/hardware\?entity=42$/);
    await expect(page.getByText('nas-01').first()).toBeVisible();
    await page.reload();
    await expect(page).toHaveURL(/\/hardware\?entity=42$/);
    await expect(page.getByText('nas-01').first()).toBeVisible();

    await page.goBack();
    await expect(page).toHaveURL(/\/map$/);
    await page.goForward();
    await expect(page).toHaveURL(/\/hardware\?entity=42$/);
  });

  test('page search keeps working while asset search fails, and Retry recovers it', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    // Registered after stubApi so it wins. Two properties of the real app
    // shape this route: the shared axios client auto-retries safe methods on
    // 5xx (max 2 retries, backoff — three attempts before the navigator sees
    // a failure), and the failure must persist across navigator sessions so
    // the Retry click is what actually recovers it.
    let failSearch = true;
    await page.route('**/api/v1/search/page*', (route) => {
      if (failSearch) {
        return route.fulfill({ status: 500, contentType: 'application/json', body: '{}' });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(searchPageResponse([hardwareResult()])),
      });
    });

    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigatorViaShortcut(page);
    await searchInNavigator(page, 'storage');

    // The banner names the failure; the page results are unaffected by it.
    await expect(page.getByText(/assets could not be searched/i)).toBeVisible();
    const storageRow = page
      .getByRole('dialog', { name: 'Navigate' })
      .getByRole('button', { name: /^Storage/ });
    await expect(storageRow).toBeVisible();

    // A local page result still navigates during the failure.
    await storageRow.click();
    await expect(page).toHaveURL(/\/storage$/);
    await waitForRouteSettled(page);

    // Retry goes back to the network and gets the asset this time. Flipping
    // the route after the click models the backend recovering; the retried
    // request leaves at least a debounce later.
    await openNavigatorViaShortcut(page);
    await searchInNavigator(page, 'storage');
    await expect(page.getByText(/assets could not be searched/i)).toBeVisible();
    await page.getByRole('button', { name: 'Retry' }).click();
    failSearch = false;
    await expect(
      page.getByRole('dialog', { name: 'Navigate' }).getByRole('button', { name: /nas-01/i })
    ).toBeVisible();

    await expectNoErrorBoundary(page, 'failed asset search');
    // The 500s here are this test's own route doing its job — the only console
    // noise they may leave is the browser's resource line for them.
    expect(significantErrors(errors).filter((e) => !/status of 500/.test(e))).toEqual([]);
  });

  test('the Profile action closes the navigator and hands focus to the dialog', async ({
    page,
  }) => {
    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);
    await searchInNavigator(page, 'profile');
    await page.getByRole('searchbox').press('Enter');

    const profile = page.getByRole('dialog', { name: 'Profile' });
    await expect(profile).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Navigate' })).toHaveCount(0);
    // Polled, not read once. The dialog takes focus from an effect, and WebKit
    // applies that a tick later than Chromium does — a single `page.evaluate`
    // right after the dialog becomes visible reads `document.body` there and
    // reports a focus trap that is in fact working. Everything else in this
    // test is a web-first assertion that retries; this was the one snapshot.
    await expect
      .poll(
        async () =>
          page.evaluate(
            () => document.querySelector('.modal')?.contains(document.activeElement) ?? false
          ),
        { message: 'the Profile dialog never took focus' }
      )
      .toBe(true);

    // The dialog owns Escape while it is open; the navigator is gone, not
    // merely hidden behind the modal.
    await page.keyboard.press('Escape');
    await expect(profile).toHaveCount(0);
    await expect(page.getByRole('dialog', { name: 'Navigate' })).toHaveCount(0);
  });

  test('a legacy settings link normalizes, and Back/Forward changes the rendered tab', async ({
    page,
  }) => {
    await page.goto('/settings?section=security');
    await waitForRouteSettled(page);
    await expectNoErrorBoundary(page, 'legacy settings link');

    await expect(page.getByRole('heading', { name: 'Security', exact: true })).toBeVisible();
    await expect(page).toHaveURL(/\/settings\?tab=security$/);

    await page.getByRole('button', { name: 'General', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible();

    await page.goBack();
    await expect(page).toHaveURL(/\/settings\?tab=security$/);
    await expect(page.getByRole('heading', { name: 'Security', exact: true })).toBeVisible();

    await page.goForward();
    await expect(page.getByRole('heading', { name: 'General', exact: true })).toBeVisible();
  });

  test('a network result retargets a mounted IPAM page to Networks, and Back restores it', async ({
    page,
  }) => {
    // Registered after the beforeEach stubApi (so networks/5 stays intact and
    // the deep-link loader still reads one object, not the collection list):
    // a network result is what this navigation is about.
    await page.route('**/api/v1/search/page*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(searchPageResponse([networkResult()])),
      })
    );

    // Start on a different IPAM tab than the one the result targets: the
    // activation must switch tabs on the already-mounted page.
    await page.goto('/ipam?tab=addresses');
    await waitForRouteSettled(page);
    await openNavigator(page);
    await searchInNavigator(page, 'core-sw');
    const networkRow = page
      .getByRole('dialog', { name: 'Navigate' })
      .getByRole('button', { name: /core-sw/i });
    await expect(networkRow).toBeVisible();
    await networkRow.click();

    await expect(page).toHaveURL(/\/ipam\?tab=networks&entity=5$/);
    await expect(page.getByText('Network: core-sw')).toBeVisible();
    await expectNoErrorBoundary(page, 'network deep link');

    // The drawer owns the page while open. Escape closes it, and closing
    // removes the entity parameter with `replace` — the back stack holds
    // tabs, not transient selections.
    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(/\/ipam\?tab=networks$/);

    // A fresh tab switch, then Back returns to Networks without resurrecting
    // the closed selection.
    await page.getByRole('button', { name: 'IP Addresses', exact: true }).click();
    await expect(page).toHaveURL(/\/ipam\?tab=addresses$/);
    await page.goBack();
    await expect(page).toHaveURL(/\/ipam\?tab=networks$/);
    await expect(page.getByText('Network: core-sw')).toHaveCount(0);
  });

  test('a viewer is filtered everywhere and never sees a Certificates pin', async ({ page }) => {
    // A pin saved while the user held a stronger role — or edited into storage
    // by hand — must be revalidated against the current authorized index.
    await page.addInitScript(() => {
      localStorage.setItem(
        'cb:nav:v1:u:1:pins',
        JSON.stringify({ v: 1, items: ['page:/certificates'] })
      );
    });
    await stubApi(page, {
      'auth/me': { id: 1, email: 'operator@example.test', role: 'viewer', is_active: true },
    });

    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);

    // Browse: nothing the route guard withholds.
    await expect(
      page.getByRole('dialog', { name: 'Navigate' }).getByRole('button', { name: /^Certificates/ })
    ).toHaveCount(0);

    // The pinned strip revalidates: the stale pin is not rendered.
    await expect(page.locator('.navigator-pinned').getByText('Certificates')).toHaveCount(0);

    // Search: page results stay within the role; settings offer nothing.
    await searchInNavigator(page, 'settings');
    await expect(page.locator('.navigator-row-label', { hasText: /^Settings: / })).toHaveCount(0);

    await searchInNavigator(page, 'certificates');
    await expect(page.getByText(/no results/i)).toBeVisible();
    await expectNoErrorBoundary(page, 'viewer navigator');
  });

  test('an editor reaches Settings but only the tab the page allows', async ({ page }) => {
    await page.route('**/api/v1/auth/me', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 1,
          email: 'editor@example.test',
          role: 'editor',
          is_active: true,
        }),
      })
    );

    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);
    await expect(
      page.getByRole('dialog', { name: 'Navigate' }).getByRole('button', { name: /^Certificates/ })
    ).toHaveCount(0);

    await searchInNavigator(page, 'settings');
    const settingsRows = page.locator('.navigator-row-label', { hasText: /^Settings: / });
    await expect(settingsRows).toHaveCount(1);
    await expect(settingsRows).toHaveText(/Integrations/);

    // The one reachable tab activates to its canonical URL.
    await page
      .getByRole('dialog', { name: 'Navigate' })
      .getByRole('button', { name: /^Settings: Integrations/ })
      .click();
    await expect(page).toHaveURL(/\/settings\?tab=integrations$/);
  });

  test('an admin reaches every settings tab and the admin-only pages', async ({ page }) => {
    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);
    await expect(
      page.getByRole('dialog', { name: 'Navigate' }).getByRole('button', { name: /^Certificates/ })
    ).toBeVisible();

    await searchInNavigator(page, 'settings');
    const settingsRows = page.locator('.navigator-row-label', { hasText: /^Settings: / });
    // All nine tabs, including the admin-only Knowledge Base.
    await expect(settingsRows).toHaveCount(9);
    await expect(settingsRows.filter({ hasText: 'Knowledge Base' })).toHaveCount(1);
  });

  test('the open overlay tracks every theme switch with fresh tokens and kept focus', async ({
    page,
  }) => {
    // The plan's "update while the overlay is open" cannot be driven through
    // the header here by design: the navigator's inset-0 backdrop and U2's
    // focus trap make every header control pointer- and keyboard-unreachable
    // while the dialog is open (an outside click closes the navigator first).
    // The equivalent, honest evidence is below: under each theme change the
    // overlay re-derives its tokens, keeps focus where the user left it, and
    // never shows stale colors from the previous theme.
    const errors = collectConsoleErrors(page);
    // Mutable settings so the app's own save/reload cycle observes the PUTs.
    const settingsState: Record<string, unknown> = {
      theme: 'dark',
      theme_preset: 'gruvbox-dark',
      default_environment: '',
      environments: [],
      map_default_filters: {},
    };
    await page.route('**/api/v1/settings', (route) => {
      const method = route.request().method();
      if (method === 'PUT' || method === 'PATCH') {
        Object.assign(settingsState, route.request().postDataJSON());
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(settingsState),
      });
    });

    // Gruvbox dark.
    await page.goto('/map');
    await waitForRouteSettled(page);
    await openNavigator(page);
    const gruvboxDark = await panelToken(page, '--color-primary');
    expect(gruvboxDark.length).toBeGreaterThan(0);
    await page.keyboard.press('Escape');

    // Gruvbox light, through the header's own toggle.
    await page.getByRole('button', { name: 'Switch to light mode' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await openNavigatorViaShortcut(page);
    const gruvboxLight = await panelToken(page, '--color-primary');
    expect(gruvboxLight).not.toBe(gruvboxDark);
    await expect(page.getByRole('searchbox')).toBeFocused();
    await page.keyboard.press('Escape');

    // A contrasting native preset, through the quick palette popover.
    await page.getByRole('button', { name: 'Quick theme switcher' }).click();
    // Preset buttons are menuitemradio items, not plain buttons.
    await page.getByRole('menuitemradio', { name: 'Nord' }).click();
    await openNavigatorViaShortcut(page);
    const nord = await panelToken(page, '--color-primary');
    expect(nord).not.toBe(gruvboxLight);
    expect(nord).not.toBe(gruvboxDark);
    await page.keyboard.press('Escape');

    // A custom palette. No in-app surface can write one while the overlay is
    // open, so the PUT stands in for a settings saved elsewhere; the full page
    // reload runs the real pre-apply + settings pipeline, and the reopened
    // overlay must resolve the custom token.
    await page.evaluate(() =>
      fetch('/api/v1/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          theme_preset: 'custom',
          theme_colors: {
            primary: '#123456',
            secondary: '#654321',
            accent1: '#00ff00',
            accent2: '#0000ff',
            background: '#000000',
            surface: '#111111',
          },
        }),
      })
    );
    await page.reload();
    await waitForRouteSettled(page);
    await openNavigator(page);
    // getComputedStyle reports a custom property's raw token, not a resolved
    // color, so the custom palette's assertion is against the value itself.
    await expect
      .poll(async () => panelToken(page, '--color-primary'), { timeout: 5000 })
      .toBe('#123456');
    await expectNoErrorBoundary(page, 'theme switches under the navigator');
    expect(significantErrors(errors)).toEqual([]);
  });
});
