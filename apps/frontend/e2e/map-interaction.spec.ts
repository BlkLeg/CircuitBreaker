import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { expectNoErrorBoundary, stubApi, waitForRouteSettled } from './fixtures/api';

/**
 * The topology map with real nodes on the canvas.
 *
 * The map has six Vitest tests against 3,025 lines, and every one of them
 * renders the page with an empty graph — so the canvas, the node components and
 * the sidebar have no coverage at all with data in them. The existing WCAG
 * sweep scans `/map` for the same reason and hits the same empty page.
 *
 * That gap is why `MapPage` was left whole when `SettingsPage` and
 * `OOBEWizardPage` were split: there was nothing to refactor against. This is
 * the start of the safety net that a later split needs.
 */

const HARDWARE = [
  { id: 1, name: 'edge-router', type: 'hardware', vendor: 'MikroTik', status: 'active' },
  { id: 2, name: 'nas-01', type: 'hardware', vendor: 'Synology', status: 'active' },
];

const GRAPH = {
  nodes: [
    { id: 'hardware-1', type: 'hardware', label: 'edge-router', data: { entity_id: 1 } },
    { id: 'hardware-2', type: 'hardware', label: 'nas-01', data: { entity_id: 2 } },
  ],
  edges: [{ id: 'e1', source: 'hardware-1', target: 'hardware-2', type: 'smart' }],
};

const POPULATED = { hardware: HARDWARE, graph: GRAPH, 'graph/topology': GRAPH };

test.describe('topology map', () => {
  test('renders a populated graph and mounts its lazy canvas', async ({ page }) => {
    await stubApi(page, POPULATED);
    await page.goto('/map');
    await waitForRouteSettled(page);

    await expectNoErrorBoundary(page, 'map with nodes');
    // `SigmaMap` is behind `lazyRoute`, so this also covers the chunk resolving
    // against a real build — the failure class this suite was built for.
    await expect(page.locator('.map-page')).toBeVisible();
  });

  test('has no serious or critical WCAG violations with nodes on the canvas', async ({ page }) => {
    await stubApi(page, POPULATED);
    await page.goto('/map');
    await waitForRouteSettled(page);
    await expect(page.locator('.map-page')).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const serious = results.violations.filter((v) =>
      ['serious', 'critical'].includes(v.impact ?? '')
    );
    expect(
      serious.map((v) => `${v.id}: ${v.nodes.length} node(s) — ${v.help}`),
      'serious/critical WCAG violations on the populated map'
    ).toEqual([]);
  });

  test('Escape dismisses the node context menu', async ({ page }) => {
    await stubApi(page, POPULATED);
    await page.goto('/map');
    await waitForRouteSettled(page);
    await expect(page.locator('.map-page')).toBeVisible();

    const node = page.locator('.react-flow__node').first();
    await expect(node).toBeVisible();
    await node.click({ button: 'right' });

    const menu = page.locator('.context-menu');
    await expect(menu).toBeVisible();

    // The Escape handler cancels every transient editor tool in one action
    // (useMapEditorUi.cancelActiveTool) alongside closing the menus.
    await page.keyboard.press('Escape');

    await expect(menu).toBeHidden();
    await expectNoErrorBoundary(page, 'map after Escape');
  });

  test('Escape cancels an open editor dialog', async ({ page }) => {
    await stubApi(page, POPULATED);
    await page.goto('/map');
    await waitForRouteSettled(page);
    await expect(page.locator('.map-page')).toBeVisible();

    await page.locator('.react-flow__node').first().click({ button: 'right' });
    await page.getByRole('button', { name: 'Edit Icon' }).click();

    // `iconPickerOpen` is owned by useMapEditorUi, so unlike the context menu
    // this asserts cancelActiveTool actually ran.
    const picker = page.getByPlaceholder('Search icons');
    await expect(picker).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(picker).toBeHidden();
    await expectNoErrorBoundary(page, 'map after cancelling the icon picker');
  });

  test('the Sigma renderer draws the same document', async ({ page }) => {
    const topologyCalls: string[] = [];
    page.on('request', (r) => {
      if (r.url().includes('/graph/topology')) topologyCalls.push(r.url());
    });

    await stubApi(page, POPULATED);
    await page.goto('/map');
    await waitForRouteSettled(page);
    await expect(page.locator('.map-page')).toBeVisible();
    const beforeToggle = topologyCalls.length;

    await page.getByRole('button', { name: /WebGL/ }).click();

    // Sigma draws onto its own canvas. Before this renderer took the document
    // as props it fetched `format: 'sigma'` — a format the backend never
    // implemented — so Graph.import threw and the canvas stayed empty.
    await expect(page.locator('canvas').first()).toBeVisible();
    await expectNoErrorBoundary(page, 'sigma renderer');

    // A renderer draws; it does not fetch.
    expect(topologyCalls.length).toBe(beforeToggle);
  });
});
