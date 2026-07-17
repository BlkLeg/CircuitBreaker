import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import DiscoveryHistoryPage from '../pages/DiscoveryHistoryPage.jsx';

vi.mock('../api/discovery.js', () => ({
  getJobs: vi.fn().mockResolvedValue({ data: [] }),
  getJobResults: vi.fn().mockResolvedValue({ data: [] }),
  cancelJob: vi.fn(),
  enrichOpnsenseJob: vi.fn(),
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    info: vi.fn(),
  }),
}));

vi.mock('../utils/logger.js', () => ({
  __esModule: true,
  default: {
    warn: vi.fn(),
  },
}));

describe('DiscoveryHistoryPage', () => {
  it('renders live progress and message from parent job data', async () => {
    render(
      <DiscoveryHistoryPage
        embedded
        jobsData={[
          {
            id: 101,
            status: 'running',
            source_type: 'network',
            started_at: '2026-03-12T12:00:00Z',
            target_cidr: '10.0.0.0/24',
            scan_types_json: '["nmap"]',
            hosts_found: 2,
            hosts_new: 1,
            hosts_conflict: 0,
            progress_percent: 42,
            eta_seconds: 65,
            current_phase: 'probe',
            current_message: 'Scanning host 10.0.0.12',
          },
        ]}
      />
    );

    // Wait for loading state to clear (useEffect sets loading=false for embedded mode)
    await waitFor(() => {
      expect(screen.getByText('42%')).toBeInTheDocument();
    });
    expect(screen.getByText('probe: Scanning host 10.0.0.12')).toBeInTheDocument();
  });

  it('keeps placeholder layout values rendered for queued rows', async () => {
    render(
      <DiscoveryHistoryPage
        embedded
        jobsData={[
          {
            id: 202,
            status: 'queued',
            source_type: 'network',
            created_at: '2026-03-12T12:00:00Z',
            target_cidr: '10.0.2.0/24',
            scan_types_json: '["nmap"]',
            hosts_found: 0,
            hosts_new: 0,
            hosts_conflict: 0,
          },
        ]}
      />
    );

    // Queued job has no started_at, so elapsed = null → '--:--:--'
    await waitFor(() => {
      expect(screen.getByText('--:--:--')).toBeInTheDocument();
    });
    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(screen.getAllByText('\u2014').length).toBeGreaterThan(0);
  });

  it('shows the animated progress bar (not the static status-colored one) for a running job', async () => {
    const { container } = render(
      <DiscoveryHistoryPage
        embedded
        jobsData={[
          {
            id: 303,
            status: 'running',
            source_type: 'network',
            started_at: '2026-03-12T12:00:00Z',
            target_cidr: '10.0.3.0/24',
            scan_types_json: '["nmap"]',
            hosts_found: 0,
            hosts_new: 0,
            hosts_conflict: 0,
            progress_percent: 55,
          },
        ]}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('scan-progress-animation')).toBeInTheDocument();
    });
    expect(container.querySelector('.scan-progress-animation.compact')).toBeInTheDocument();
    expect(container.querySelector('.history-progress-fill')).not.toBeInTheDocument();
  });

  it('shows the static status-colored bar (not the animation) for a completed job', async () => {
    const { container } = render(
      <DiscoveryHistoryPage
        embedded
        jobsData={[
          {
            id: 404,
            status: 'completed',
            source_type: 'network',
            started_at: '2026-03-12T12:00:00Z',
            target_cidr: '10.0.4.0/24',
            scan_types_json: '["nmap"]',
            hosts_found: 5,
            hosts_new: 2,
            hosts_conflict: 0,
          },
        ]}
      />
    );

    await waitFor(() => {
      expect(container.querySelector('.history-progress-fill.status-done')).toBeInTheDocument();
    });
    expect(
      container.querySelector('[data-testid="scan-progress-animation"]')
    ).not.toBeInTheDocument();
  });
});
