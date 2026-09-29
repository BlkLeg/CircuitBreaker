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

const PROXMOX_HYPERVISORS = Array.from({ length: 8 }, (_, index) => ({
  id: `hardware-${index + 1}`,
  type: 'hardware',
  label: `pve-${index + 1}`,
  role: 'hypervisor',
  data: { entity_id: index + 1 },
}));

const PROXMOX_GUESTS = Array.from({ length: 16 }, (_, index) => ({
  id: `compute-${index + 1}`,
  type: 'compute',
  label: `guest-${index + 1}`,
  data: { entity_id: index + 1 },
}));

const WIDE_PROXMOX_GRAPH = {
  nodes: [...PROXMOX_HYPERVISORS, ...PROXMOX_GUESTS],
  edges: PROXMOX_GUESTS.map((guest, index) => ({
    id: `proxmox-edge-${index + 1}`,
    source: PROXMOX_HYPERVISORS[index % PROXMOX_HYPERVISORS.length].id,
    target: guest.id,
    type: 'smart',
  })),
};

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

  test('fits a wide Proxmox cluster and still pans horizontally', async ({ page }) => {
    await stubApi(page, {
      graph: WIDE_PROXMOX_GRAPH,
      'graph/topology': WIDE_PROXMOX_GRAPH,
    });
    await page.goto('/map');
    await waitForRouteSettled(page);

    const canvas = page.locator('.react-flow');
    const nodes = page.locator('.react-flow__node');
    await expect(canvas).toBeVisible();
    await expect(nodes).toHaveCount(WIDE_PROXMOX_GRAPH.nodes.length);

    const canvasBox = await canvas.boundingBox();
    expect(canvasBox).not.toBeNull();
    const nodeBoxes = await nodes.evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
      })
    );
    for (const box of nodeBoxes) {
      expect(box.left).toBeGreaterThanOrEqual(canvasBox!.x - 1);
      expect(box.right).toBeLessThanOrEqual(canvasBox!.x + canvasBox!.width + 1);
      expect(box.top).toBeGreaterThanOrEqual(canvasBox!.y - 1);
      expect(box.bottom).toBeLessThanOrEqual(canvasBox!.y + canvasBox!.height + 1);
    }

    const viewport = page.locator('.react-flow__viewport');
    const transformBeforePan = await viewport.getAttribute('style');
    await page.mouse.move(
      canvasBox!.x + canvasBox!.width / 2,
      canvasBox!.y + canvasBox!.height / 2
    );
    await page.mouse.wheel(300, 0);
    await expect.poll(() => viewport.getAttribute('style')).not.toBe(transformBeforePan);
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

  test('the Sigma renderer draws the same document', async ({ page }, testInfo) => {
    // Sigma is WebGL. Headless firefox and webkit in the CI image provide no
    // GL context, so the canvas never mounts there. The behaviour under test —
    // that the renderer draws the document it is handed and issues no request
    // of its own — is not browser-specific.
    test.skip(testInfo.project.name !== 'chromium', 'Sigma needs a WebGL context');

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
