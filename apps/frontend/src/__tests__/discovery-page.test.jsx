import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DiscoveryPage from '../pages/DiscoveryPage.jsx';

function renderDiscoveryPage() {
  return render(
    <MemoryRouter>
      <DiscoveryPage />
    </MemoryRouter>
  );
}

// Mock api client
vi.mock('../api/client', () => {
  const mockClient = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return {
    default: mockClient,
    systemApi: {
      getStats: vi
        .fn()
        .mockResolvedValue({ data: { mem: { total: 16000, used: 8000 }, disk: { percent: 45 } } }),
    },
  };
});

// Must import discovery API functions as named exports
import * as discoveryApi from '../api/discovery.js';

vi.mock('../api/discovery.js', () => ({
  getDiscoveryStatus: vi.fn().mockResolvedValue({
    data: {
      effective_mode: 'native',
      docker_available: false,
      net_raw_capable: true,
      docker_container_count: 0,
    },
  }),
  getProfiles: vi.fn().mockResolvedValue({ data: [] }),
  getJobs: vi.fn().mockResolvedValue({ data: [] }),
  cancelJob: vi.fn(),
  getPendingResults: vi.fn().mockResolvedValue({ data: { total: 0 } }),
  getJobLogs: vi.fn().mockResolvedValue({ data: [] }),
  startAdHocScan: vi.fn(),
  syncDocker: vi.fn(),
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
  default: {
    warn: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    debug: vi.fn(),
  },
}));

// Mock the discovery event emitter
vi.mock('../hooks/useDiscoveryStream.js', () => ({
  discoveryEmitter: {
    on: vi.fn(),
    off: vi.fn(),
    emit: vi.fn(),
  },
}));

// Mock child components to keep tests focused
vi.mock('../components/discovery/DiscoverySidebar.jsx', () => ({
  default: ({ filter, onFilterChange, pendingReviewCount }) =>
    React.createElement(
      'nav',
      { 'data-testid': 'discovery-sidebar' },
      React.createElement('span', { 'data-testid': 'filter-label' }, filter),
      React.createElement('span', { 'data-testid': 'pending-count' }, String(pendingReviewCount)),
      React.createElement('button', { onClick: () => onFilterChange('all') }, 'All Scans'),
      React.createElement('button', { onClick: () => onFilterChange('new-scan') }, 'New Scan')
    ),
}));

vi.mock('../components/discovery/ScanTable.jsx', () => ({
  default: ({ jobs }) =>
    React.createElement(
      'div',
      { 'data-testid': 'scan-table' },
      jobs.map((j) =>
        React.createElement('div', { key: j.id, 'data-testid': `job-${j.id}` }, j.target || j.id)
      )
    ),
}));

vi.mock('../components/discovery/ScanDetailPanel.jsx', () => ({
  default: () => null,
}));

vi.mock('../components/discovery/DiscoveryStatusBar.jsx', () => ({
  default: ({ totalScans, activeCount }) =>
    React.createElement(
      'div',
      { 'data-testid': 'status-bar' },
      `${totalScans} scans, ${activeCount} active`
    ),
}));

vi.mock('../components/discovery/ScanProfilesPanel.jsx', () => ({
  default: () => React.createElement('div', null, 'ScanProfiles'),
}));

vi.mock('../pages/DiscoveryHistoryPage.jsx', () => ({
  default: () => React.createElement('div', null, 'DiscoveryHistory'),
}));

vi.mock('../components/discovery/NewScanPage.jsx', () => ({
  default: () =>
    React.createElement(
      'div',
      { 'data-testid': 'new-scan-page' },
      React.createElement('button', { type: 'button' }, 'Start Scan')
    ),
}));

vi.mock('../components/discovery/ReviewQueuePanel.jsx', () => ({
  default: () => React.createElement('div', null, 'ReviewQueue'),
}));

vi.mock('../components/proxmox/ProxmoxIntegrationSection.jsx', () => ({
  default: () => React.createElement('div', null, 'ProxmoxIntegration'),
}));

vi.mock('lucide-react', () => ({
  X: () => React.createElement('span', null, 'X'),
}));

vi.mock('../styles/discovery.css', () => ({}));

describe('DiscoveryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset default mock values
    discoveryApi.getJobs.mockResolvedValue({ data: [] });
    discoveryApi.getProfiles.mockResolvedValue({ data: [] });
    discoveryApi.getPendingResults.mockResolvedValue({ data: { total: 0 } });
    discoveryApi.getDiscoveryStatus.mockResolvedValue({
      data: {
        effective_mode: 'native',
        docker_available: false,
        net_raw_capable: true,
        docker_container_count: 0,
      },
    });
  });

  it('renders discovery page with sidebar and main content', async () => {
    renderDiscoveryPage();

    await waitFor(() => {
      expect(screen.getByTestId('discovery-sidebar')).toBeInTheDocument();
    });

    expect(screen.getByText('DiscoveryHistory')).toBeInTheDocument();
  });

  it('loads jobs and keeps default Discovery history view', async () => {
    discoveryApi.getJobs.mockResolvedValueOnce({
      data: [
        { id: 1, target: '192.168.1.0/24', status: 'completed', hosts_found: 5 },
        { id: 2, target: '10.0.0.0/24', status: 'running', hosts_found: 2 },
      ],
    });

    renderDiscoveryPage();

    await waitFor(() => {
      expect(discoveryApi.getJobs).toHaveBeenCalled();
    });

    expect(screen.getByText('DiscoveryHistory')).toBeInTheDocument();
  });

  it('keeps all filter selected by default', async () => {
    discoveryApi.getJobs.mockResolvedValueOnce({
      data: [
        { id: 1, target: '192.168.1.0/24', status: 'completed', hosts_found: 5 },
        { id: 2, target: '10.0.0.0/24', status: 'running', hosts_found: 2 },
      ],
    });

    renderDiscoveryPage();

    await waitFor(() => {
      expect(screen.getByTestId('filter-label')).toHaveTextContent('all');
    });
  });

  it('displays pending review count in sidebar', async () => {
    discoveryApi.getPendingResults.mockResolvedValueOnce({ data: { total: 7 } });

    renderDiscoveryPage();

    await waitFor(() => {
      expect(screen.getByTestId('pending-count')).toHaveTextContent('7');
    });
  });

  it('shows start scan action after switching to New Scan', async () => {
    renderDiscoveryPage();

    await waitFor(() => {
      expect(screen.getByTestId('discovery-sidebar')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'New Scan' }));

    expect(screen.getByTestId('new-scan-page')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Scan' })).toBeInTheDocument();
  });
});
