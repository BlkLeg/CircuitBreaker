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

// Mutable, test-controlled backing stores for the two WebSocket hooks.
// Reassigning `live.statuses` / `live.telemetry` to a *new* Map (rather than
// mutating one in place) mirrors exactly how the real hooks behave: a fresh
// Map only on an actual message, the *same* reference across renders that
// have nothing new to deliver. That distinction matters here — a mock that
// handed out a new Map on every call, regardless of whether anything changed,
// would make the hook's own `liveTelemetry`-dependent effect see a "changed"
// dependency on every render and loop forever once a push was present.
const live = vi.hoisted(() => ({
  statuses: new Map(),
  telemetry: new Map(),
}));

vi.mock('../hooks/useAgentLive', () => ({
  useAgentLive: () => ({ statuses: live.statuses, connected: true }),
}));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => ({ data: live.telemetry, connected: true }),
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
  live.statuses = new Map();
  live.telemetry = new Map();
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

  // Fix round: reloadProbes/reloadDiscovery are reachable both from the
  // tab-gated effect and as an external "refresh after mutation" callback, so
  // rapid re-triggering (e.g. tab switching) can leave two requests in flight
  // at once. A slower, earlier one resolving after a fresher one must not be
  // allowed to overwrite it.
  it('discards a stale reloadProbes response that resolves after a fresher one', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(api.getAgentProbes).toHaveBeenCalledTimes(1));

    let resolveStale;
    const stale = new Promise((resolve) => {
      resolveStale = resolve;
    });
    api.getAgentProbes
      .mockReturnValueOnce(stale)
      .mockResolvedValueOnce({ data: { assignments: [{ id: 'fresh' }] } });

    result.current.reloadProbes(); // in flight, resolves later
    result.current.reloadProbes(); // fired after — must win

    await waitFor(() => expect(result.current.probes).toEqual({ assignments: [{ id: 'fresh' }] }));

    resolveStale({ data: { assignments: [{ id: 'stale' }] } });
    await act(() => Promise.resolve());
    await act(() => Promise.resolve());

    expect(result.current.probes).toEqual({ assignments: [{ id: 'fresh' }] });
  });

  it('discards a stale reloadDiscovery response that resolves after a fresher one', async () => {
    const { result } = mount('overview');
    await waitFor(() => expect(api.getAgentDiscovery).toHaveBeenCalledTimes(1));

    let resolveStale;
    const stale = new Promise((resolve) => {
      resolveStale = resolve;
    });
    api.getAgentDiscovery
      .mockReturnValueOnce(stale)
      .mockResolvedValueOnce({ data: { subnets: [{ cidr: 'fresh' }] } });

    result.current.reloadDiscovery(); // in flight, resolves later
    result.current.reloadDiscovery(); // fired after — must win

    await waitFor(() => expect(result.current.discovery).toEqual({ subnets: [{ cidr: 'fresh' }] }));

    resolveStale({ data: { subnets: [{ cidr: 'stale' }] } });
    await act(() => Promise.resolve());
    await act(() => Promise.resolve());

    expect(result.current.discovery).toEqual({ subnets: [{ cidr: 'fresh' }] });
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

  // Fix round: the hook subscribed to both WebSockets but read neither, so
  // `online` never moved off the initial presence poll and a live
  // sample/readiness push sat unread in `liveTelemetry` until the next 30s
  // poll clobbered it. These four tests prove all three merges actually run.

  it('overrides a polled presence with a fresh connected/disconnected push', async () => {
    api.getAgentsPresence.mockResolvedValue({ data: [{ online: false, hardware: null }] });
    const { result, rerender } = mount('overview');
    await waitFor(() => expect(result.current.online).toBe(false));

    act(() => {
      live.statuses = new Map(live.statuses).set(7, {
        event_type: 'connected',
        detail: null,
        ts: Date.now(),
      });
    });
    rerender({ tab: 'overview' });

    await waitFor(() => expect(result.current.online).toBe(true));
  });

  it('ignores a connected/disconnected push older than the last presence poll', async () => {
    api.getAgentsPresence.mockResolvedValue({ data: [{ online: false, hardware: null }] });
    const { result, rerender } = mount('overview');
    await waitFor(() => expect(result.current.online).toBe(false));

    // Older than the presence poll that just landed: isLivePushFresh's
    // poll-recency guard must reject it, so the poll's answer stands.
    act(() => {
      live.statuses = new Map(live.statuses).set(7, {
        event_type: 'connected',
        detail: null,
        ts: Date.now() - 5000,
      });
    });
    rerender({ tab: 'overview' });

    await waitFor(() => expect(result.current.agent).toBeTruthy());
    expect(result.current.online).toBe(false);
  });

  it('merges a live sample push into telemetry.latest', async () => {
    // Seeded so `streamIsDelivering` (liveTelemetry.size > 0) is already true
    // at mount: the poll-backoff effect depends on that boolean, and the sample
    // push below must not be the thing that flips it, or the resulting
    // dependency change re-fires an immediate reloadTelemetry() that can land
    // after the merge and clobber it — the sample merge has no re-apply-after-
    // poll guard (matching AgentDetailPage.jsx exactly; see the readiness merge
    // below for the contrasting case that does need one).
    live.telemetry = new Map([['seed:unrelated', {}]]);
    const { result, rerender } = mount('overview');
    await waitFor(() => expect(result.current.telemetry).toBeTruthy());

    act(() => {
      live.telemetry = new Map(live.telemetry).set('agent:7', {
        payload: { summary: { cpu_pct: 42 }, status: 'ok' },
        collected_at: '2026-09-05T00:00:00Z',
      });
    });
    rerender({ tab: 'overview' });

    await waitFor(() =>
      expect(result.current.telemetry.latest?.payload?.summary).toEqual({
        cpu_pct: 42,
      })
    );
    expect(result.current.telemetry.latest.status).toBe('ok');
    expect(result.current.telemetry.latest.collected_at).toBe('2026-09-05T00:00:00Z');
  });

  it('applies a live readiness push, then lets a newer poll override a now-stale one', async () => {
    // Same seeding rationale as the sample-merge test above.
    live.telemetry = new Map([['seed:unrelated', {}]]);
    const { result, rerender } = mount('overview');
    await waitFor(() => expect(api.getAgentTelemetry).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.telemetry).toBeTruthy());

    const pushedReadiness = [{ collector: 'cpu', state: 'degraded' }];
    act(() => {
      live.telemetry = new Map(live.telemetry).set('readiness:agent:7', {
        readiness: pushedReadiness,
      });
    });
    rerender({ tab: 'overview' });

    // Applied: the push arrived after the poll that is currently applied.
    await waitFor(() => expect(result.current.telemetry.readiness).toBe(pushedReadiness));

    // A newer poll resolves with different readiness. Its request was issued
    // after the push arrived above, so it must win — the stale push must not
    // be re-applied on top of it.
    const freshReadiness = [{ collector: 'cpu', state: 'ok' }];
    api.getAgentTelemetry.mockResolvedValueOnce({
      data: { latest: null, readiness: freshReadiness, spool: null },
    });
    act(() => result.current.reloadTelemetry());

    await waitFor(() => expect(result.current.telemetry.readiness).toBe(freshReadiness));
    expect(result.current.telemetry.readiness).not.toBe(pushedReadiness);
  });
});
