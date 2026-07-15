import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockGetNetworkThreatAlerts = vi.fn();
const mockGetNetworkPrivacyScore = vi.fn();

vi.mock('../api/client', () => ({
  windscribeApi: {
    getNetworkThreatAlerts: (...args) => mockGetNetworkThreatAlerts(...args),
    getNetworkPrivacyScore: (...args) => mockGetNetworkPrivacyScore(...args),
    getDeviceThreatProfile: vi.fn(),
  },
  hardwareApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}));

vi.mock('../hooks/useDiscoveryStream', () => ({
  discoveryEmitter: { on: vi.fn(), off: vi.fn(), emit: vi.fn() },
}));

import HostileNetworkBanner from '../components/security/HostileNetworkBanner';
import PrivacyScoreWidget from '../components/security/PrivacyScoreWidget';

beforeEach(() => {
  mockGetNetworkThreatAlerts.mockReset();
  mockGetNetworkPrivacyScore.mockReset();
});

describe('HostileNetworkBanner', () => {
  it('renders nothing when status is safe', async () => {
    mockGetNetworkThreatAlerts.mockResolvedValue({
      data: { status: 'safe', alerts: [] },
    });
    const { container } = render(<HostileNetworkBanner />);
    await waitFor(() => expect(mockGetNetworkThreatAlerts).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when status is unknown or disabled', async () => {
    mockGetNetworkThreatAlerts.mockResolvedValue({
      data: { enabled: false, status: 'unknown', alerts: [] },
    });
    const { container } = render(<HostileNetworkBanner />);
    await waitFor(() => expect(mockGetNetworkThreatAlerts).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a warning banner on warning status', async () => {
    mockGetNetworkThreatAlerts.mockResolvedValue({
      data: {
        status: 'warning',
        alerts: [
          {
            check_id: 'captive_portal',
            severity: 'warning',
            detail: 'generate_204 returned 302',
            detected_at: '2026-07-15T00:00:00+00:00',
          },
        ],
      },
    });
    render(<HostileNetworkBanner />);
    expect(await screen.findByText(/Network anomaly detected/)).toBeInTheDocument();
    expect(screen.getByText(/generate_204 returned 302/)).toBeInTheDocument();
  });

  it('renders a hostile banner on critical status', async () => {
    mockGetNetworkThreatAlerts.mockResolvedValue({
      data: {
        status: 'critical',
        alerts: [
          {
            check_id: 'dns_tamper',
            severity: 'critical',
            detail: 'canary mismatch',
            detected_at: '2026-07-15T00:00:00+00:00',
          },
        ],
      },
    });
    render(<HostileNetworkBanner />);
    expect(await screen.findByText(/Hostile network detected/)).toBeInTheDocument();
  });
});

describe('PrivacyScoreWidget', () => {
  it('renders score and grade as a pill', async () => {
    mockGetNetworkPrivacyScore.mockResolvedValue({
      data: { enabled: true, score: 85, grade: 'B', deductions: [], history: [] },
    });
    render(
      <MemoryRouter>
        <PrivacyScoreWidget />
      </MemoryRouter>
    );
    expect(await screen.findByText('85')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
  });

  it('renders nothing when scoring is disabled', async () => {
    mockGetNetworkPrivacyScore.mockResolvedValue({
      data: { enabled: false, score: null, grade: null, deductions: [], history: [] },
    });
    const { container } = render(
      <MemoryRouter>
        <PrivacyScoreWidget />
      </MemoryRouter>
    );
    await waitFor(() => expect(mockGetNetworkPrivacyScore).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when no snapshot exists yet', async () => {
    mockGetNetworkPrivacyScore.mockResolvedValue({
      data: { enabled: true, score: null, grade: null, deductions: [], history: [] },
    });
    const { container } = render(
      <MemoryRouter>
        <PrivacyScoreWidget />
      </MemoryRouter>
    );
    await waitFor(() => expect(mockGetNetworkPrivacyScore).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
