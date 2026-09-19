import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { stubApi } from './fixtures/api';

/**
 * The shared `expectNoErrorBoundary` reads `.page-content`, which the wizard
 * does not render — it lays out under `.login-root`, outside the app shell.
 * Same assertion, read off the body.
 */
async function expectNoErrorBoundary(page: Page, context: string): Promise<void> {
  const text = await page.locator('body').innerText();
  if (/Something went wrong|An unexpected error occurred/i.test(text)) {
    throw new Error(`${context}: rendered its ErrorBoundary:\n${text.slice(0, 400)}`);
  }
}

/**
 * The first-run wizard, step by step, in a real browser.
 *
 * Written when `OOBEWizardPage` was split from one 2,215-line file into seven
 * step components, a context and a state hook. Each step reads the wizard
 * context, so a value the hook stops returning does not fail a build or a lint
 * — the step renders `undefined` and, the moment it dereferences it, throws
 * into the ErrorBoundary. Only opening the steps catches that, and nothing did.
 *
 * `bootstrap/status` reporting `needs_setup` is what routes the whole app to
 * the wizard (App.jsx's catch-all route), so no navigation is needed beyond
 * loading the site.
 */

/**
 * `needs_bootstrap`, not `needs_setup`: App.jsx reads the former
 * (`res.data?.needs_bootstrap`) and routes everything to the wizard when it is
 * true. The shared fixture's default says false, which is why every other spec
 * gets the application instead of this.
 */
const NEEDS_SETUP = {
  'bootstrap/status': { needs_bootstrap: true, has_admin: false },
  'bootstrap/onboarding': { current_step: 'start' },
};

/** Step number to the name `GET /bootstrap/onboarding` resumes from. */
const STEPS: Array<[number, string]> = [
  [4, 'theme'],
  [5, 'regional'],
  [6, 'email'],
  [7, 'summary'],
];

test.describe('OOBE first run', () => {
  test('the wizard opens on step 1 and advances through the account step', async ({ page }) => {
    await stubApi(page, NEEDS_SETUP);
    await page.goto('/');

    await expect(page.getByText('First-run setup')).toBeVisible();
    await expect(page.getByText('Step 1/7')).toBeVisible();
    await expectNoErrorBoundary(page, 'OOBE step 1');

    // Step 1 -> 2. The welcome step's only control is its forward button.
    await page.locator('.oobe-card button').last().click();
    await expect(page.getByText('Step 2/7')).toBeVisible();
    await expectNoErrorBoundary(page, 'OOBE step 2');

    // Step 2 is skippable — the public domain is optional.
    await page.getByRole('button', { name: /skip/i }).click();
    await expect(page.getByText('Step 3/7')).toBeVisible();
    await expectNoErrorBoundary(page, 'OOBE step 3');

    // Step 3 is the account step, the largest of the seven and the one with the
    // most context values. Its password-rule list rendering at all is the proof
    // that the step received the wizard state.
    await expect(page.getByText('At least 8 characters')).toBeVisible();
  });

  test('every step renders once the wizard is walked to it', async ({ page }) => {
    await stubApi(page, NEEDS_SETUP);

    // The wizard resumes from the server: `GET /bootstrap/onboarding` names the
    // step it stopped on. Stubbing that opens any step directly, instead of
    // driving six forms to reach the seventh.
    for (const [step, name] of STEPS) {
      await page.route('**/api/v1/bootstrap/onboarding', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ current_step: name }),
        })
      );
      await page.goto('/');
      await expectNoErrorBoundary(page, `OOBE step ${step}`);
      await expect(page.getByText(`Step ${step}/7`)).toBeVisible();
      // A step that mounted but rendered nothing is the other failure mode.
      await expect(page.locator('.oobe-card').locator('input, select, button')).not.toHaveCount(0);
    }
  });
});
