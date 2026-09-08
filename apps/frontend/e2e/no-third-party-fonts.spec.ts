import { expect, test } from '@playwright/test';
import { stubApi, waitForRouteSettled } from './fixtures/api';

/**
 * The UI must not fetch its typeface from a third party.
 *
 * `useAppFont`, `ThemeSettings` and `useOOBEWizard` each used to inject a
 * <link> to fonts.googleapis.com for the selected family. That made the app's
 * typography depend on reaching Google: an air-gapped install — a first-class
 * mode here, `CB_AIRGAP` — silently fell back to system fonts while the
 * weather widget beside it correctly stood down, and every page load disclosed
 * the viewer to a third party on a page they self-host to avoid exactly that.
 *
 * The faces are vendored under `public/fonts` now. This spec is what keeps
 * them there.
 */
const FONT_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];

const SURFACES = ['/map', '/settings', '/hardware'];

for (const path of SURFACES) {
  test(`${path} requests no third-party fonts`, async ({ page }) => {
    const offenders: string[] = [];
    page.on('request', (request) => {
      const url = request.url();
      if (FONT_HOSTS.some((host) => url.includes(host))) offenders.push(url);
    });

    await stubApi(page);
    await page.goto(path);
    await waitForRouteSettled(page);

    expect(offenders, `${path} reached a font CDN`).toEqual([]);
  });
}

test('a self-hosted face is actually served', async ({ page }) => {
  await stubApi(page);
  await page.goto('/map');
  await waitForRouteSettled(page);

  // Guards the other direction: asserting "no CDN request" would also pass if
  // the fonts were simply gone.
  const response = await page.request.get('/fonts/Inter-400-latin.woff2');
  expect(response.status()).toBe(200);
  const magic = (await response.body()).subarray(0, 4).toString('latin1');
  expect(magic, 'served file is not woff2').toBe('wOF2');
});
