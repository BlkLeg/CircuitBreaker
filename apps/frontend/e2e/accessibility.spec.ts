import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi } from './fixtures/api';

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

test('keyboard focus reaches the page and is visibly indicated', async ({ page }) => {
  await stubApi(page);
  await page.goto('/map');
  await expect(page.locator('.page-content')).toBeVisible();

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
