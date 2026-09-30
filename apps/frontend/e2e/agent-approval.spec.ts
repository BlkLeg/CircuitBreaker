import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

/**
 * Approving an agent from the add-agent flow.
 *
 * Step 3 and the approval dialog had no stylesheet rules at all, so they
 * rendered with browser defaults: white inputs, radios and checkboxes, grey
 * buttons, and a "dialog" with no panel or backdrop. This pins the themed
 * dialog the step now opens.
 */

const PENDING = {
  id: 9,
  status: 'pending',
  hostname: 'pve-node-02',
  fingerprint: 'SHA256:9f3c7b1e4a20d6c855e1b9f02c7d3e16a8b4f90271c5d3e0bb61a71e',
  os: 'linux',
  arch: 'amd64',
};
const DETAIL = {
  ...PENDING,
  duplicate_machine_id: true,
  proposed_hardware_id: 3,
  proposed_hardware_name: 'pve-node-02 (192.168.1.12)',
};
const DEFAULTS = {
  host_telemetry: { enabled: true, config: { interval_s: 30 } },
  local_discovery: { enabled: true, config: {} },
  remote_probe: { enabled: false, config: {} },
};
const OVERRIDES = {
  agents: [PENDING],
  'agents/9': DETAIL,
  'agents/capability-defaults': DEFAULTS,
  'agents/presence': [],
  'agents/metrics/series': [],
};

test('step 3 opens a themed approval dialog above the page', async ({ page }, testInfo) => {
  await stubApi(page, OVERRIDES);
  await page.goto('/agents');
  await waitForRouteSettled(page);

  // With a pending agent the wizard starts collapsed behind "Add agent".
  await page.getByRole('button', { name: 'Add agent' }).click();
  // The card flags the duplicate before the dialog is opened.
  await expect(page.getByText(/same machine ID as an enrolled agent/i).first()).toBeVisible();
  await page.getByRole('button', { name: 'Review & approve' }).click();

  const dialog = page.getByRole('dialog', { name: 'Approve agent' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Approve agent' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Reject' })).toBeVisible();
  await expect(dialog.getByRole('alert')).toContainText(/same machine ID/i);
  await expectNoErrorBoundary(page, 'approval dialog');

  const box = (await dialog.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  // Topmost at its header, i.e. not under the app's top bar.
  expect(
    await page.evaluate(
      ([x, y]) => !!document.elementFromPoint(x, y)?.closest('[role="dialog"]'),
      [box.x + box.width / 2, box.y + 12]
    )
  ).toBe(true);

  const styles = await dialog.evaluate((el) => {
    const radio = el.querySelector('input[type="radio"]') as HTMLElement;
    const toggle = el.querySelector('input[type="checkbox"]') as HTMLElement;
    const panel = getComputedStyle(el);
    return {
      panelBorder: panel.borderTopStyle,
      panelRadius: parseFloat(panel.borderTopLeftRadius),
      radioAppearance: getComputedStyle(radio).appearance,
      toggleAppearance: getComputedStyle(toggle).appearance,
      toggleBg: getComputedStyle(toggle).backgroundColor,
    };
  });
  expect(styles.panelBorder).toBe('solid');
  expect(styles.panelRadius).toBeGreaterThan(0);
  expect(styles.radioAppearance).toBe('none');
  expect(styles.toggleAppearance).toBe('none');
  expect(styles.toggleBg).not.toBe('rgb(255, 255, 255)');

  await page.screenshot({ path: testInfo.outputPath('approval-dialog.png') });

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('Review on the pending fleet row opens the same dialog', async ({ page }) => {
  await stubApi(page, OVERRIDES);
  await page.goto('/agents');
  await waitForRouteSettled(page);

  await page.getByRole('button', { name: 'Review' }).first().click();
  const dialog = page.getByRole('dialog', { name: 'Approve agent' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Reject' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Close' }).click();
  await expect(dialog).toBeHidden();
});
