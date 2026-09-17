import type { FullConfig } from '@playwright/test';

/**
 * Fail fast when the port is serving somebody else's site.
 *
 * `webServer.reuseExistingServer` is true outside CI, which is a real
 * convenience — an already-running `npm run preview` saves a rebuild per run.
 * It also means Playwright will happily attach to *whatever* answers on the
 * port. On 2026-09-17 an unrelated server held 4173 and every spec ran against
 * it: ten navigator specs and `smoke.spec.ts` failed with `waitForRouteSettled`
 * timeouts, which reads exactly like the app being broken. Nothing in the
 * output said the page under test was a different website.
 *
 * One request, before any spec runs, turns that into a single sentence naming
 * the port and how to move off it.
 */
async function assertServerIsOurs(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use?.baseURL;
  if (!baseURL) return;

  let body: string;
  try {
    const response = await fetch(baseURL, { headers: { accept: 'text/html' } });
    body = await response.text();
  } catch (cause) {
    throw new Error(
      `E2E: could not reach ${baseURL}. The preview server did not start.\n` +
        `If the port is taken by something else, set CB_E2E_PORT to a free one.`,
      { cause }
    );
  }

  // index.html is served for every route by the SPA fallback, so the title is
  // present whatever path we ask for.
  if (!body.includes('<title>Circuit Breaker</title>')) {
    const title = /<title>([^<]*)<\/title>/.exec(body)?.[1] ?? '(no <title>)';
    throw new Error(
      `E2E: ${baseURL} is not serving Circuit Breaker — it answered with "${title}".\n` +
        `Something else already owns that port and reuseExistingServer attached to it.\n` +
        `Free the port, or run against another one: CB_E2E_PORT=4273 npx playwright test`
    );
  }
}

export default assertServerIsOurs;
