import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

// ACC-10: WCAG 2.2 AA automation plus keyboard/focus checks. NB: '/' redirects
// to /map and '/networks' to /ipam (App.jsx:145,150), so both are named by
// their real destinations.
const PAGES = ['/map', '/hardware', '/services', '/ipam', '/storage', '/settings'];

test.describe('WCAG 2.2 AA', () => {
  for (const path of PAGES) {
    test(`${path} has no serious or critical violations`, async ({ page }) => {
      await stubApi(page);
      await page.goto(path);
      await expect(page.locator('.page-content')).toBeVisible();
      // Scan the settled page. Mid-fade every colour is composited toward the
      // background, which axe reports as a contrast violation that is not
      // there once the transition ends. See waitForRouteSettled.
      await waitForRouteSettled(page);
      // Belt and braces with the settle wait above. That one covers the
      // framer-motion route fade; this covers per-component CSS transitions
      // that start later, when a table or panel mounts on its own data. Either
      // one in flight makes axe sample a colour composited toward the page
      // background and report a contrast violation that is not there once the
      // page is still.
      await page.addStyleTag({
        content: `*, *::before, *::after {
          animation-duration: 0s !important;
          animation-delay: 0s !important;
          transition-duration: 0s !important;
          transition-delay: 0s !important;
        }`,
      });
      await expectNoErrorBoundary(page, `a11y scan of ${path}`);

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
      expect(blocking, `axe violations on ${path}:\n${summary}`).toHaveLength(0);
    });
  }
});

// The navigator is the densest secondary-text surface in the app -- group
// labels, per-row descriptions, category filters, footer hints -- and none of it
// was ever scanned, because every page above is captured with the overlay shut.
// A palette whose muted colour could not be read on its own panel therefore
// passed this suite while the overlay was, in a user's words, hard to see.
//
// These three presets measured worst before applyTheme floored text to AA:
// monokai/dark at 1.74:1, nord/dark at 2.22:1, solarized-dark at 2.31:1.
const CONTRAST_HOSTILE_PRESETS = ['monokai', 'nord', 'solarized-dark'];

test.describe('the navigator is readable in every theme', () => {
  for (const preset of CONTRAST_HOSTILE_PRESETS) {
    test(`${preset} keeps the open navigator at AA`, async ({ page }) => {
      await stubApi(page, {
        settings: {
          theme: 'dark',
          theme_preset: preset,
          default_environment: '',
          environments: [],
          map_default_filters: {},
        },
      });
      await page.goto('/map');
      await expect(page.locator('.page-content')).toBeVisible();
      await waitForRouteSettled(page);

      await page.getByRole('button', { name: 'Open navigator' }).click();
      await expect(page.getByRole('dialog', { name: 'Navigate' })).toBeVisible();
      // Rows carry the descriptions this is really about, so do not scan an
      // empty overlay and call it evidence.
      await expect(page.locator('.navigator-row-desc').first()).toBeVisible();

      const results = await new AxeBuilder({ page })
        .include('.navigator-panel')
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
      expect(blocking, `axe violations in the ${preset} navigator:\n${summary}`).toHaveLength(0);
      await expectNoErrorBoundary(page, `navigator a11y scan under ${preset}`);
    });
  }
});

test('keyboard focus reaches the page and is visibly indicated', async ({ page }) => {
  await stubApi(page);
  await page.goto('/map');
  await expect(page.locator('.page-content')).toBeVisible();
  await waitForRouteSettled(page);

  await page.keyboard.press('Tab');
  const focused = page.locator(':focus');
  await expect(focused).toBeVisible();

  // ACC-10 names focus visibility explicitly: a focused element with no outline
  // and no ring leaves a keyboard user with no cursor.
  const ring = await focused.evaluate((el) => {
    const s = getComputedStyle(el);
    return { outlineWidth: s.outlineWidth, outlineStyle: s.outlineStyle, boxShadow: s.boxShadow };
  });
  const hasIndicator =
    (ring.outlineStyle !== 'none' && ring.outlineWidth !== '0px') || ring.boxShadow !== 'none';
  expect(
    hasIndicator,
    `focused element has no visible focus indicator: ${JSON.stringify(ring)}`
  ).toBe(true);
});
