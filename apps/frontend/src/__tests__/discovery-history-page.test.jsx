import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import DiscoveryHistoryPage from '../pages/DiscoveryHistoryPage.jsx';

vi.mock('../api/discovery.js', () => ({
  getJobs: vi.fn().mockResolvedValue({ data: [] }),
  getJobResults: vi.fn().mockResolvedValue({ data: [] }),
  cancelJob: vi.fn(),
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
  it('renders live progress, eta, and message from parent job data', () => {
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

    expect(screen.getByText('42%')).toBeInTheDocument();
    expect(screen.getByText('ETA 00:01:05')).toBeInTheDocument();
    expect(screen.getByText('probe: Scanning host 10.0.0.12')).toBeInTheDocument();
  });

  it('keeps placeholder layout values rendered for queued rows', () => {
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

    expect(screen.getByText('ETA --:--:--')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(screen.getAllByText('\u2014').length).toBeGreaterThan(0);
  });
});
