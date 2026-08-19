import { expect, test } from '@playwright/test';
import { collectConsoleErrors, significantErrors, stubApi } from './fixtures/api';

test('the app boots and renders without console errors', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await stubApi(page);

  await page.goto('/');
  // '/' redirects to /map (App.jsx:145).
  await expect(page).toHaveURL(/\/map$/);
  await expect(page.locator('.page-content')).toBeVisible();

  const significant = significantErrors(errors);
  expect(significant, `unexpected console errors:\n${significant.join('\n')}`).toHaveLength(0);
});
