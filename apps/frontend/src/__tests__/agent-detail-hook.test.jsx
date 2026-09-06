import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// vi.hoisted (not a plain top-level const) because vi.mock's factory below
// spreads `api` eagerly at factory-execution time, and vi.mock calls are
// hoisted above a file's own top-level statements. A plain `const api = {}`
// would still be in its pre-initialization TDZ when the mocked module is
// first transitively imported, throwing "Cannot access 'api' before
// initialization". vi.hoisted runs before that import happens.
const api = vi.hoisted(() => ({
  getAgent: vi.fn(),
  getAgentEvents: vi.fn(),
  getAgentsPresence: vi.fn(),
  getAgentTelemetry: vi.fn(),
  getAgentTelemetryHistory: vi.fn(),
  getAgentProbes: vi.fn(),
  getAgentDiscovery: vi.fn(),
  getCapabilityDefaults: vi.fn(),
}));

vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return { ...api, normalizeCapability: actual.normalizeCapability };
});
vi.mock('../hooks/useAgentLive', () => ({
  useAgentLive: () => ({ statuses: new Map(), connected: true }),
}));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => ({ data: new Map(), connected: true }),
}));
vi.mock('../components/common/Toast', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}));

import { useAgentDetail, POLL_ACTIVE_MS } from '../hooks/useAgentDetail';

const AGENT = {
  id: 7,
  status: 'active',
  hostname: 'edge-01',
  agent_version: '0.4.0',
  fingerprint: 'a'.repeat(32),
  last_seen_at: new Date().toISOString(),
  capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
};

const wrapper = ({ children }) => <MemoryRouter>{children}</MemoryRouter>;

function mount(activeTab = 'overview') {
  return renderHook(({ tab }) => useAgentDetail('7', { activeTab: tab }), {
    wrapper,
    initialProps: { tab: activeTab },
  });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getAgent.mockResolvedValue({ data: AGENT });
  api.getAgentEvents.mockResolvedValue({ data: [] });
  api.getAgentsPresence.mockResolvedValue({ data: [{ online: true, hardware: null }] });
  api.getAgentTelemetry.mockResolvedValue({ data: { latest: null, readiness: [], spool: null } });
  api.getAgentTelemetryHistory.mockResolvedValue({ data: { points: [] } });
  api.getAgentProbes.mockResolvedValue({ data: [] });
  api.getAgentDiscovery.mockResolvedValue({ data: { subnets: [] } });
  api.getCapabilityDefaults.mockResolvedValue({
    data: { host_telemetry: { config: { interval_s: 30 } } },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useAgentDetail', () => {
  it('loads identity, presence and the latest sample regardless of tab', async () => {
    mount('events');
    await waitFor(() => expect(api.getAgent).toHaveBeenCalled());
    expect(api.getAgentsPresence).toHaveBeenCalled();
    // The header live strip is on every tab, so its source must be too.
    expect(api.getAgentTelemetry).toHaveBeenCalled();
  });

  it('does not fetch telemetry history until the telemetry tab is open', async () => {
    const { rerender } = mount('overview');
    await waitFor(() => expect(api.getAgent).toHaveBeenCalled());
    expect(api.getAgentTelemetryHistory).not.toHaveBeenCalled();

    rerender({ tab: 'telemetry' });
    await waitFor(() => expect(api.getAgentTelemetryHistory).toHaveBeenCalled());
  });

  it('does not fetch discovery on the telemetry tab', async () => {
    mount('telemetry');
    await waitFor(() => expect(api.getAgent).toHaveBeenCalled());
    expect(api.getAgentDiscovery).not.toHaveBeenCalled();
  });

  it('fetches probes and discovery on overview, which summarises both', async () => {
    mount('overview');
    await waitFor(() => expect(api.getAgentProbes).toHaveBeenCalled());
    expect(api.getAgentDiscovery).toHaveBeenCalled();
  });

  it('polls the latest sample on the active interval', async () => {
    mount('overview');
    await waitFor(() => expect(api.getAgentTelemetry).toHaveBeenCalledTimes(1));
    await act(() => vi.advanceTimersByTimeAsync(POLL_ACTIVE_MS + 100));
    await waitFor(() => expect(api.getAgentTelemetry.mock.calls.length).toBeGreaterThan(1));
  });

  it('derives states and a page composition from what it loaded', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(Array.isArray(result.current.states)).toBe(true);
    expect(result.current.page.tabs).toContain('overview');
  });

  it('exposes a freshness reading for the header pill', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.freshness.label).toMatch(/LIVE|LAGGING|STALE|OFFLINE/);
  });

  it('keeps the page usable when presence fails', async () => {
    // Presence is additive. A hiccup there must not blank identity.
    api.getAgentsPresence.mockRejectedValue(new Error('boom'));
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.presence).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('keeps the page usable when discovery fails', async () => {
    api.getAgentDiscovery.mockRejectedValue(new Error('boom'));
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.discovery).toBeNull();
  });

  it('refetches history when the range changes', async () => {
    const { result } = mount('telemetry');
    await waitFor(() => expect(api.getAgentTelemetryHistory).toHaveBeenCalledTimes(1));
    act(() => result.current.setHistoryRange('7d'));
    await waitFor(() => expect(api.getAgentTelemetryHistory).toHaveBeenCalledTimes(2));
    expect(api.getAgentTelemetryHistory).toHaveBeenLastCalledWith('7', '7d');
  });

  it('returns setDiscovery so DiscoveryScopeSection can push in-place updates', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(typeof result.current.setDiscovery).toBe('function');
    act(() => result.current.setDiscovery({ subnets: [{ cidr: '10.0.0.0/24' }] }));
    await waitFor(() =>
      expect(result.current.discovery).toEqual({ subnets: [{ cidr: '10.0.0.0/24' }] })
    );
  });
});
