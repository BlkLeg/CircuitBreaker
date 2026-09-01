import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import {
  HEALTH_POLL_INTERVAL_READY_MS,
  HEALTH_POLL_INTERVAL_STARTING_MS,
  HEALTH_POLL_INTERVAL_OFFLINE_MS,
} from '../lib/constants.js';
import { useServerLifecycle } from '../hooks/useServerLifecycle.js';

// This hook talks to the network with raw fetch (not axios), specifically to
// stay outside the axios retry/intercept layer — see useServerLifecycle.js.
function Probe() {
  const { state } = useServerLifecycle();
  return <span data-testid="state">{state}</span>;
}

function okResponse(body) {
  return { ok: true, json: async () => body };
}

async function advance(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('useServerLifecycle', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = originalFetch;
  });

  it('does not resolve to offline after one or two consecutive failed polls, only the third', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse({ state: 'ready' }))
      .mockRejectedValueOnce(new Error('network error'))
      .mockRejectedValueOnce(new Error('network error'))
      .mockRejectedValueOnce(new Error('network error'));
    globalThis.fetch = fetchMock;

    render(<Probe />);

    // First poll (STARTING cadence) succeeds and reaches 'ready'.
    await advance(HEALTH_POLL_INTERVAL_STARTING_MS);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('ready'));

    // First failure (READY cadence). Not conclusive on its own — stays ready.
    await advance(HEALTH_POLL_INTERVAL_READY_MS);
    expect(screen.getByTestId('state').textContent).toBe('ready');

    // Second consecutive failure (fast retry cadence). Still not offline.
    await advance(HEALTH_POLL_INTERVAL_OFFLINE_MS);
    expect(screen.getByTestId('state').textContent).toBe('ready');

    // Third consecutive failure crosses HEALTH_FAILURES_BEFORE_OFFLINE.
    await advance(HEALTH_POLL_INTERVAL_OFFLINE_MS);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('offline'));
  });

  it('resets the failure streak on a success, so failure-success-failure stays online', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse({ state: 'ready' }))
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce(okResponse({ state: 'ready' }))
      .mockRejectedValueOnce(new Error('network error'));
    globalThis.fetch = fetchMock;

    render(<Probe />);

    await advance(HEALTH_POLL_INTERVAL_STARTING_MS);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('ready'));

    // Failure #1.
    await advance(HEALTH_POLL_INTERVAL_READY_MS);
    expect(screen.getByTestId('state').textContent).toBe('ready');

    // Success clears the counter.
    await advance(HEALTH_POLL_INTERVAL_OFFLINE_MS);
    expect(screen.getByTestId('state').textContent).toBe('ready');

    // Failure #1 again (streak was reset, so this alone must not go offline).
    await advance(HEALTH_POLL_INTERVAL_READY_MS);
    expect(screen.getByTestId('state').textContent).toBe('ready');
  });

  it('applies a successful "starting" response on the very first poll, with no threshold', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(okResponse({ state: 'starting' }));
    globalThis.fetch = fetchMock;

    render(<Probe />);

    await advance(HEALTH_POLL_INTERVAL_STARTING_MS);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('starting'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
