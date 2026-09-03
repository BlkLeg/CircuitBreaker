import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import ServerLifecycleBanner from '../components/ServerLifecycleBanner.jsx';
import { MAX_OFFLINE_BEFORE_NOTIFY_MS } from '../lib/constants.js';

vi.mock('../hooks/useServerLifecycle.js', () => ({
  useServerLifecycle: vi.fn(),
}));

import { useServerLifecycle } from '../hooks/useServerLifecycle.js';

describe('ServerLifecycleBanner', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('renders children during initial lifecycle check', () => {
    useServerLifecycle.mockReturnValue({
      state: 'checking',
      isReady: false,
      offlineSince: null,
    });

    render(
      <ServerLifecycleBanner>
        <div>Standard Loading</div>
      </ServerLifecycleBanner>
    );

    expect(screen.getByText('Standard Loading')).toBeInTheDocument();
    expect(screen.queryByText('Server is starting up…')).not.toBeInTheDocument();
  });

  it('shows the startup banner without unmounting the app below it', async () => {
    // R5: "never unmount the route tree for a degraded banner". This component
    // used to return a replacement element instead of its children, so a health
    // blip destroyed every page's state — an open form, a running scan view, an
    // unsent edit — and remounted the whole tree on recovery.
    useServerLifecycle.mockReturnValue({
      state: 'starting',
      isReady: false,
      offlineSince: null,
    });

    render(
      <ServerLifecycleBanner>
        <div>Standard Loading</div>
      </ServerLifecycleBanner>
    );

    await act(async () => {
      vi.advanceTimersByTime(MAX_OFFLINE_BEFORE_NOTIFY_MS + 1);
    });

    expect(screen.getByText('Server is starting up…')).toBeInTheDocument();
    expect(screen.getByText('Standard Loading')).toBeInTheDocument();
  });

  it('does not blank the screen on a single starting response', () => {
    // The streak/delay applied only to the offline path. `starting` and
    // `stopping` rendered immediately, so one health response during a rolling
    // worker restart or a migration lock blanked the app with no delay at all.
    useServerLifecycle.mockReturnValue({
      state: 'starting',
      isReady: false,
      offlineSince: null,
    });

    render(
      <ServerLifecycleBanner>
        <div>Standard Loading</div>
      </ServerLifecycleBanner>
    );

    expect(screen.queryByText('Server is starting up…')).not.toBeInTheDocument();
    expect(screen.getByText('Standard Loading')).toBeInTheDocument();
  });
});
