import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScanProgressAnimation from '../components/discovery/ScanProgressAnimation.jsx';
import ScanDetailPanel from '../components/discovery/ScanDetailPanel.jsx';

const mockUseSettings = vi.fn();

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => mockUseSettings(),
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
  it('renders the circuit style by default and reflects pct in the fill width', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'circuit' } });
    const { container } = render(<ScanProgressAnimation pct={62} />);

    expect(screen.getByTestId('scan-progress-animation')).toBeInTheDocument();
    const fill = container.querySelector('.spb-circuit-fill');
    expect(fill).toBeInTheDocument();
    expect(fill).toHaveStyle({ width: '62%' });
  });

  it('renders the scanline style when selected', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'scanline' } });
    const { container } = render(<ScanProgressAnimation pct={40} />);
    expect(container.querySelector('.spb-scanline-fill')).toHaveStyle({ width: '40%' });
  });

  it('renders the segmented style with the correct number of lit segments', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'segmented' } });
    const { container } = render(<ScanProgressAnimation pct={50} />);
    // 50% of 20 segments = 10 lit
    expect(container.querySelectorAll('.spb-segment-lit')).toHaveLength(10);
  });

  it('renders the minimal style when selected', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'minimal' } });
    const { container } = render(<ScanProgressAnimation pct={80} />);
    expect(container.querySelector('.spb-minimal-fill')).toHaveStyle({ width: '80%' });
  });

  it('falls back to circuit for an unknown or missing style value', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'not_a_real_style' } });
    const { container } = render(<ScanProgressAnimation pct={10} />);
    expect(container.querySelector('.spb-circuit-fill')).toBeInTheDocument();
  });

  it('clamps out-of-range pct values into 0-100', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'minimal' } });
    const { container } = render(<ScanProgressAnimation pct={150} />);
    expect(container.querySelector('.spb-minimal-fill')).toHaveStyle({ width: '100%' });
  });
});

describe('ScanDetailPanel', () => {
  it('shows the animation instead of the old progress bar when a scan is running', () => {
    mockUseSettings.mockReturnValue({ settings: { scan_progress_style: 'circuit' } });
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
    expect(container.querySelector('.spb-circuit-fill')).toHaveStyle({ width: '42%' });
    expect(container.querySelector('.scan-progress-bar-wrap')).toBeNull();
    expect(container.querySelector('.scan-progress-bar-fill')).toBeNull();
  });
});
