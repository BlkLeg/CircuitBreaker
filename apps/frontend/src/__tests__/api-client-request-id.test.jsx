import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import client from '../api/client';
import { getEntries, clearEntries } from '../lib/diagnosticsBuffer';

/**
 * Task 1 shipped the server half of Route §4.2's correlation path: an
 * `X-Request-ID` middleware that echoes back any inbound ID matching
 * `[A-Za-z0-9_.-]{1,64}` unchanged, and logs/slow-query warnings keyed on it.
 * This is the browser half — the axios client mints that ID, times the
 * request, and records exactly one diagnostics entry per *logical* request,
 * even across retries.
 *
 * The client's response interceptor also carries load-bearing behavior that
 * predates this task (retry-on-5xx/network-error, a single 429 retry,
 * session-expiry detection, CSRF injection) — every test below either
 * exercises or guards one of those paths to make sure request-ID/diagnostics
 * wiring didn't disturb it.
 *
 * A real XHR/fetch adapter can't be driven synchronously in jsdom, so these
 * tests swap in a scripted `client.defaults.adapter` — the same seam axios
 * itself uses to talk to the network — rather than mocking `fetch` or a
 * transport library.
 */

const ORIGINAL_ADAPTER = client.defaults.adapter;

function successResponse(config, { status = 200, data = {} } = {}) {
  return Promise.resolve({
    data,
    status,
    statusText: 'OK',
    headers: { date: new Date().toUTCString() },
    config,
    request: {},
  });
}

function errorResponse(config, { status, data = {} } = {}) {
  const error = new Error(`Request failed with status code ${status}`);
  error.config = config;
  error.response = {
    status,
    statusText: 'Error',
    headers: { date: new Date().toUTCString() },
    data,
    config,
  };
  return Promise.reject(error);
}

function networkError(config) {
  const error = new Error('Network Error');
  error.config = config;
  return Promise.reject(error);
}

function rateLimitedResponse(config, retryAfterSeconds) {
  const error = new Error('Request failed with status code 429');
  error.config = config;
  error.response = {
    status: 429,
    statusText: 'Too Many Requests',
    headers: { date: new Date().toUTCString(), 'retry-after': String(retryAfterSeconds) },
    data: { detail: 'Too many requests' },
    config,
  };
  return Promise.reject(error);
}

beforeEach(() => {
  clearEntries();
  document.cookie = 'cb_csrf=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
});

afterEach(() => {
  client.defaults.adapter = ORIGINAL_ADAPTER;
});

describe('request ID injection', () => {
  it('sets an X-Request-ID header, and a successful response records one entry carrying it', async () => {
    let seenRequestId;
    client.defaults.adapter = (config) => {
      seenRequestId = config.headers['X-Request-ID'];
      return successResponse(config, { status: 200, data: { ok: true } });
    };

    const res = await client.get('/hardware');

    expect(res.status).toBe(200);
    expect(seenRequestId).toEqual(expect.any(String));
    expect(seenRequestId.length).toBeGreaterThan(0);

    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      kind: 'request',
      requestId: seenRequestId,
      status: 200,
      retryCount: 0,
    });
  });
});

describe('failure recording', () => {
  it('records the right status for a non-retryable failure', async () => {
    client.defaults.adapter = (config) => errorResponse(config, { status: 404 });

    await expect(client.get('/hardware/999')).rejects.toMatchObject({ statusCode: 404 });

    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ kind: 'request', status: 404, retryCount: 0 });
  });

  it('records status 0 for a responseless network error', async () => {
    // POST is not auto-retried, so this resolves after exactly one attempt.
    client.defaults.adapter = (config) => networkError(config);

    await expect(client.post('/hardware', {})).rejects.toMatchObject({ isNetworkError: true });

    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ kind: 'request', status: 0, retryCount: 0 });
  });
});

describe('retry collapsing', () => {
  it('records ONE entry with retryCount incremented for a retried request, not one per attempt', async () => {
    let attempts = 0;
    let firstRequestId;
    let secondRequestId;
    client.defaults.adapter = (config) => {
      attempts += 1;
      if (attempts === 1) {
        firstRequestId = config.headers['X-Request-ID'];
        return errorResponse(config, { status: 500 });
      }
      secondRequestId = config.headers['X-Request-ID'];
      return successResponse(config, { status: 200, data: { ok: true } });
    };

    const res = await client.get('/hardware');

    expect(res.status).toBe(200);
    expect(attempts).toBe(2);
    // Same logical request across both attempts, not a fresh ID per retry.
    expect(secondRequestId).toBe(firstRequestId);

    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      kind: 'request',
      requestId: firstRequestId,
      status: 200,
      retryCount: 1,
    });
  });
});

describe('CSRF injection regression guard', () => {
  it('still injects X-CSRF-Token on a POST after the request-ID change', async () => {
    document.cookie = 'cb_csrf=test-csrf-token; path=/;';
    let seenCsrf;
    let seenRequestId;
    client.defaults.adapter = (config) => {
      seenCsrf = config.headers['X-CSRF-Token'];
      seenRequestId = config.headers['X-Request-ID'];
      return successResponse(config, { status: 201, data: { id: 1 } });
    };

    await client.post('/hardware', { name: 'test-device' });

    expect(seenCsrf).toBe('test-csrf-token');
    expect(seenRequestId).toEqual(expect.any(String));
  });
});

describe('429 handling (H5 / _noRateLimitRetry)', () => {
  // These tests need the fake-timer clock: the default 429 path sleeps
  // Retry-After before retrying, and the opt-out's entire point is that it
  // does not — asserting that with real timers would just make the "no
  // sleep" case pass trivially instead of proving it.
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('still sleeps Retry-After and retries once for a normal (foreground) request', async () => {
    let attempts = 0;
    client.defaults.adapter = (config) => {
      attempts += 1;
      if (attempts === 1) return rateLimitedResponse(config, 2);
      return successResponse(config, { status: 200, data: { ok: true } });
    };

    const promise = client.get('/hardware');
    await vi.advanceTimersByTimeAsync(2000);
    const res = await promise;

    expect(res.status).toBe(200);
    expect(attempts).toBe(2);

    // The 429 retry uses its own `_retried429` flag, not `_retryCount` (that
    // counter is for the separate 5xx/network-error retry path) — one entry,
    // `wasRateLimited: true` is the signal that the sleep-and-retry ran.
    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ status: 200, retryCount: 0, wasRateLimited: true });
  });

  it('surfaces a 429 immediately for a background poll opted out via _noRateLimitRetry, no sleep needed', async () => {
    let attempts = 0;
    client.defaults.adapter = (config) => {
      attempts += 1;
      return rateLimitedResponse(config, 5);
    };

    // No vi.advanceTimersByTimeAsync at all: if this needed the 5s
    // Retry-After sleep to settle, this call would hang forever under fake
    // timers and the test would time out rather than pass.
    await expect(client.get('/hardware', { _noRateLimitRetry: true })).rejects.toMatchObject({
      isRateLimited: true,
      statusCode: 429,
    });

    expect(attempts).toBe(1);

    // The opt-out still records exactly one diagnostics entry — Task 2's
    // one-entry-per-logical-request guarantee holds for this path too.
    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ status: 429, retryCount: 0 });
  });

  it('does not disturb the default retry path for a caller that never sets the flag', async () => {
    let attempts = 0;
    client.defaults.adapter = (config) => {
      attempts += 1;
      if (attempts === 1) return rateLimitedResponse(config, 1);
      return successResponse(config, { status: 200, data: {} });
    };

    const promise = client.post('/hardware', { name: 'x' });
    await vi.advanceTimersByTimeAsync(1000);
    await promise;

    expect(attempts).toBe(2);
  });
});

describe('generateRequestId fallback', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('still stamps a request ID when crypto.randomUUID is unavailable', async () => {
    // Simulate an older browser / jsdom without crypto.randomUUID.
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: undefined });

    let seenRequestId;
    client.defaults.adapter = (config) => {
      seenRequestId = config.headers['X-Request-ID'];
      return successResponse(config, { status: 200, data: {} });
    };

    await client.get('/hardware');
    expect(seenRequestId).toEqual(expect.any(String));
    expect(seenRequestId.length).toBeGreaterThan(0);
  });
});
