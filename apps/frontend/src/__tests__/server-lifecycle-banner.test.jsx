import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ServerLifecycleBanner from '../components/ServerLifecycleBanner.jsx';

vi.mock('../hooks/useServerLifecycle.js', () => ({
  useServerLifecycle: vi.fn(),
}));

import { useServerLifecycle } from '../hooks/useServerLifecycle.js';

describe('ServerLifecycleBanner', () => {
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

  it('renders startup banner when server reports starting', () => {
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

    expect(screen.getByText('Server is starting up…')).toBeInTheDocument();
    expect(screen.queryByText('Standard Loading')).not.toBeInTheDocument();
  });
});
