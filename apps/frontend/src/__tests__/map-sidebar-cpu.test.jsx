import React from 'react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Sidebar from '../components/Map/Sidebar';
import { telemetryApi } from '../api/client';

vi.mock('../../api/client', () => ({}));
vi.mock('../api/client', () => ({
  telemetryApi: {
    getEntity: vi.fn(),
  },
  docsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
  servicesApi: {
    discovery: vi.fn().mockResolvedValue({}),
  },
}));

// The click sidebar's telemetry block only fetches for a Proxmox-linked node
// (Sidebar.jsx's `hasProxmox = node?.data?.integration_config_id != null`), so
// that field is what makes this fixture reach the CPU row at all.
const proxmoxNode = {
  id: 'hardware-101',
  originalType: 'hardware',
  _refId: 101,
  label: 'pve-01',
  data: {
    label: 'pve-01',
    integration_config_id: 7,
  },
};

describe('Map/Sidebar CPU row (F-1)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // F-1: this row used to render `Math.round(data.cpu_pct * 100)`, which
  // assumes the raw Proxmox 0-1 fraction. Every backend producer of `cpu_pct`
  // is on the 0-100 convention — the Proxmox pollers convert at ingest
  // (services/proxmox_telemetry.py, proxmox_discovery.py,
  // discovery_proxmox_merge.py), and services/agent_telemetry.py outright
  // rejects an agent summary outside 0..100 — so the extra factor rendered a
  // 12.5% host as 1250%. The sibling hover panel
  // (components/map/TelemetrySidebar.jsx) consumes this identical
  // `telemetryApi.getEntity` response and has always rendered it unscaled;
  // this test pins the two together.
  it('renders cpu_pct on the 0-100 convention the API actually returns', async () => {
    telemetryApi.getEntity.mockResolvedValueOnce({
      status: 'online',
      telemetry_status: 'healthy',
      cpu_pct: 12.5,
    });

    render(<Sidebar node={proxmoxNode} onClose={vi.fn()} />);

    // Math.round(12.5) === 13. The point of the fixture value is that the
    // pre-fix code turned this exact input into "1250%".
    expect(await screen.findByText('13%')).toBeInTheDocument();
    expect(screen.queryByText('1250%')).not.toBeInTheDocument();
  });

  it('leaves a full-load host at 100%, not 10000%', async () => {
    telemetryApi.getEntity.mockResolvedValueOnce({
      status: 'online',
      cpu_pct: 100,
    });

    render(<Sidebar node={proxmoxNode} onClose={vi.fn()} />);

    expect(await screen.findByText('100%')).toBeInTheDocument();
    expect(screen.queryByText('10000%')).not.toBeInTheDocument();
  });
});
