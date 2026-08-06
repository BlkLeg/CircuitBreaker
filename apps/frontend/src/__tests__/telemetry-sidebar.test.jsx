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

  // The agent host-telemetry projection writes `hardware.telemetry_data` through
  // `app/services/telemetry_normalize.py`'s `agent_summary_to_platform`, so the
  // entity response carries *platform* key names only — never the collector's
  // `root_disk_pct`/`max_temp_c`/`mem_used_bytes`. This fixture is that exact
  // shape; if the normalizer stops emitting the GB views these rows go blank.
  const agentProjectedTelemetry = {
    status: 'online',
    telemetry_status: 'healthy',
    cpu_pct: 12.5,
    mem_pct: 32.27,
    mem_used: 5368709120,
    mem_total: 16637792256,
    mem_used_mb: 5120.0,
    mem_total_mb: 15867.04,
    mem_used_gb: 5.0,
    mem_total_gb: 15.5,
    disk_pct: 41.8,
    rootfs_used: 209045065728,
    rootfs_total: 500107862016,
    disk_used_gb: 194.7,
    disk_total_gb: 465.8,
    temp_c: 48.0,
    cpu_temp: 48.0,
    uptime_s: 864000,
  };

  it('renders memory and disk GB rows from an agent-projected telemetry_data', async () => {
    telemetryApi.getEntity.mockResolvedValueOnce(agentProjectedTelemetry);

    render(
      <TelemetrySidebar
        node={baseNode}
        position={{ x: 200, y: 120 }}
        onClose={vi.fn()}
        onBoundsChange={vi.fn()}
      />
    );

    expect(await screen.findByText('Memory (5/15.5 GB)')).toBeInTheDocument();
    expect(screen.getByText('Disk (194.7/465.8 GB)')).toBeInTheDocument();
    expect(screen.getByText('CPU')).toBeInTheDocument();
  });

  it('falls back to raw byte counts when the GB views are absent', async () => {
    const bytesOnly = { ...agentProjectedTelemetry };
    delete bytesOnly.mem_used_gb;
    delete bytesOnly.mem_total_gb;
    delete bytesOnly.disk_used_gb;
    delete bytesOnly.disk_total_gb;
    telemetryApi.getEntity.mockResolvedValueOnce(bytesOnly);

    render(
      <TelemetrySidebar
        node={baseNode}
        position={{ x: 200, y: 120 }}
        onClose={vi.fn()}
        onBoundsChange={vi.fn()}
      />
    );

    expect(await screen.findByText('Memory (5/15.5 GB)')).toBeInTheDocument();
    expect(screen.getByText('Disk (194.7/465.8 GB)')).toBeInTheDocument();
  });

  it('renders no memory or disk row for raw agent collector key names', async () => {
    // The pre-normalizer projection wrote the agent summary verbatim; these are
    // its key names, and none of them is a key this sidebar reads. This is the
    // blank-UI regression `telemetry_normalize` exists to prevent.
    telemetryApi.getEntity.mockResolvedValueOnce({
      status: 'online',
      telemetry_status: 'healthy',
      cpu_pct: 12.5,
      mem_used_bytes: 5368709120,
      mem_total_bytes: 16637792256,
      root_disk_pct: 41.8,
      max_temp_c: 48.0,
    });

    render(
      <TelemetrySidebar
        node={baseNode}
        position={{ x: 200, y: 120 }}
        onClose={vi.fn()}
        onBoundsChange={vi.fn()}
      />
    );

    expect(await screen.findByText('CPU')).toBeInTheDocument();
    expect(screen.queryByText(/^Memory \(/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Disk \(/)).not.toBeInTheDocument();
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
