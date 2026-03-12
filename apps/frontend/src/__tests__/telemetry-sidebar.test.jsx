import React from 'react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import TelemetrySidebar from '../components/map/TelemetrySidebar';
import { telemetryApi, proxmoxApi } from '../api/client';

vi.mock('../api/client', () => ({
  telemetryApi: {
    getEntity: vi.fn(),
  },
  proxmoxApi: {
    clusterOverview: vi.fn(),
  },
}));

const baseNode = {
  originalType: 'hardware',
  _refId: 101,
  data: {
    label: 'pve-01',
    integration_config_id: 7,
  },
};

describe('TelemetrySidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    proxmoxApi.clusterOverview.mockResolvedValue({
      data: {
        cluster: {
          name: 'pve-cluster',
          quorum: true,
          nodes_online: 4,
          nodes_total: 4,
          vms: 12,
          lxcs: 3,
          uptime: '',
        },
        problems: [],
        storage: [],
      },
    });
  });

  it.each([
    [{ status: 'online', telemetry_status: 'healthy' }, 'healthy'],
    [{ status: 'running', telemetry_status: 'ok' }, 'ok'],
    [{ status: 'active', telemetry_status: 'unknown' }, 'unknown'],
  ])('shows green indicator for healthy status vocab %#', async (payload, statusLabel) => {
    telemetryApi.getEntity.mockResolvedValueOnce(payload);

    render(
      <TelemetrySidebar
        node={baseNode}
        position={{ x: 200, y: 120 }}
        onClose={vi.fn()}
        onBoundsChange={vi.fn()}
      />
    );

    const statusText = await screen.findByText(statusLabel);
    const statusDot = statusText.parentElement?.querySelector('span');
    expect(statusDot).toHaveStyle({ background: '#22c55e' });
    expect(screen.getByText('Quorum OK')).toBeInTheDocument();
    expect(screen.getByText(/Nodes\s+4\s*\/\s*4/)).toBeInTheDocument();
  });

  it('shows red indicator for unhealthy status', async () => {
    telemetryApi.getEntity.mockResolvedValueOnce({
      status: 'offline',
      telemetry_status: 'critical',
    });

    render(
      <TelemetrySidebar
        node={baseNode}
        position={{ x: 200, y: 120 }}
        onClose={vi.fn()}
        onBoundsChange={vi.fn()}
      />
    );

    const statusText = await screen.findByText('critical');
    const statusDot = statusText.parentElement?.querySelector('span');
    expect(statusDot).toHaveStyle({ background: '#ef4444' });
  });
});
