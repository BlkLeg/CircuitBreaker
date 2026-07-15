import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScanProgressAnimation from '../components/discovery/ScanProgressAnimation.jsx';
import ScanDetailPanel from '../components/discovery/ScanDetailPanel.jsx';

vi.mock('@lottiefiles/dotlottie-react', () => ({
  DotLottieReact: ({ src, autoplay, loop, style }) =>
    React.createElement('div', {
      'data-testid': 'dotlottie-player',
      'data-src': src,
      'data-autoplay': String(Boolean(autoplay)),
      'data-loop': String(Boolean(loop)),
      style,
    }),
}));

vi.mock('../api/discovery.js', () => ({
  getJobResults: vi.fn(),
}));

vi.mock('../components/discovery/JobStatusBadge.jsx', () => ({
  default: () => React.createElement('span', null, 'status'),
}));

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: () => ({
    getVirtualItems: () => [],
    getTotalSize: () => 0,
  }),
}));

describe('ScanProgressAnimation', () => {
  it('renders the dotLottie player for the scan progress asset', () => {
    render(<ScanProgressAnimation />);

    expect(screen.getByTestId('scan-progress-animation')).toBeInTheDocument();
    expect(screen.getByTestId('dotlottie-player')).toBeInTheDocument();
    expect(screen.getByTestId('dotlottie-player')).toHaveAttribute('data-src');
  });
});

describe('ScanDetailPanel', () => {
  it('shows the animation instead of the old progress bar when a scan is running', () => {
    const { container } = render(
      <ScanDetailPanel
        job={{
          id: 7,
          status: 'running',
          started_at: '2026-07-15T12:00:00Z',
          current_message: 'Scanning hosts',
          label: 'Test scan',
        }}
        progressPct={42}
        etaSeconds={120}
        logEntries={[]}
        detailedLogs={[]}
        profileMap={new Map()}
      />
    );

    expect(screen.getByTestId('scan-progress-animation')).toBeInTheDocument();
    expect(container.querySelector('.scan-progress-bar-wrap')).toBeNull();
    expect(container.querySelector('.scan-progress-bar-fill')).toBeNull();
  });
});
