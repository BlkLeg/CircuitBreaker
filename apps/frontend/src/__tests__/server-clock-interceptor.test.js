import { beforeEach, describe, expect, it } from 'vitest';
import client from '../api/client.jsx';
import { __resetServerClock, serverClockOffsetMs, serverNow } from '../utils/serverClock';

/**
 * AGT-14 / slice AGT-6 §3: "avoid client-clock-only truth."
 *
 * utils/serverClock is unit-tested in agent-state.test.js. What that cannot
 * show is that the offset is ever actually measured in the running app — the
 * whole mechanism is inert unless the API client feeds it. This asserts the
 * wiring: the shared axios instance records the server's `Date` off both a
 * successful response and a failed one.
 *
 * Driven through the registered interceptor handlers rather than a live
 * request, because the point under test is the registration itself.
 */

const NOW = Date.parse('2026-08-26T12:00:00Z');

const responseHandlers = () => client.interceptors.response.handlers.filter(Boolean);

beforeEach(() => {
  __resetServerClock();
});

describe('the shared API client', () => {
  it('registers a response interceptor that observes the server clock', async () => {
    const handlers = responseHandlers();
    expect(handlers.length).toBeGreaterThan(0);

    const response = { headers: { date: new Date(NOW).toUTCString() }, data: {} };
    handlers.forEach((handler) => handler.fulfilled?.(response));

    expect(serverClockOffsetMs()).not.toBeNull();
    // The interceptor stamps the sample with the real client clock, so the
    // offset it measured is "this machine minus 2026-08-26T12:00Z". Feeding
    // the real clock back through serverNow must therefore recover the
    // server's instant — which is the whole contract.
    expect(Math.abs(serverNow(Date.now()) - NOW)).toBeLessThan(2000);
  });

  it('observes it on an error response too, so a failing deployment still has a reference', async () => {
    const handlers = responseHandlers();
    const error = {
      response: { status: 503, headers: { date: new Date(NOW).toUTCString() }, data: {} },
      config: { method: 'get', url: '/agents', _retryCount: 5 },
    };
    // The rejection handler re-throws (or retries); only the side effect matters.
    await Promise.allSettled(handlers.map((handler) => handler.rejected?.(error)));

    expect(serverClockOffsetMs()).not.toBeNull();
  });

  it('leaves the offset unmeasured when no response carries a Date', async () => {
    const handlers = responseHandlers();
    handlers.forEach((handler) => handler.fulfilled?.({ headers: {}, data: {} }));
    // Unmeasured must stay distinct from "measured as zero": a UI that cannot
    // tell them apart claims the clocks agree when it has never checked.
    expect(serverClockOffsetMs()).toBeNull();
  });
});
