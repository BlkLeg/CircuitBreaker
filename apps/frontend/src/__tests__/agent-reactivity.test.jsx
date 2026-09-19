import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { useTabActivity } from '../hooks/useTabActivity';
import { METRIC_THRESHOLDS, hotMetrics } from '../lib/agentThresholds';
import AgentDetailPage from '../pages/AgentDetailPage';

const AGENT = {
  id: 3,
  name: 'branch-office-01',
  hostname: 'box1',
  status: 'active',
  fingerprint: 'a'.repeat(32),
  agent_version: '0.8.1',
  capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
};

/** A cool sample: nothing over threshold, so nothing is news yet. */
const coolTelemetry = {
  latest: {
    collected_at: new Date().toISOString(),
    projected: false,
    summary: { cpu_pct: 12 },
    payload: {},
  },
  readiness: [],
  capability: { enabled: true, config: { interval_s: 30 } },
  spool: { depth: 0 },
};

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
  getAgent: vi.fn(),
  getAgentEvents: vi.fn(),
  getAgentProbes: vi.fn(),
  getAgentTelemetry: vi.fn(),
  getAgentTelemetryHistory: vi.fn(),
  getAgentsPresence: vi.fn(),
  getCapabilityDefaults: vi.fn(),
  getAgentDiscovery: vi.fn(),
  pauseAgentDiscovery: vi.fn(),
  resumeAgentDiscovery: vi.fn(),
  setAgentCapabilities: vi.fn(),
  revokeAgent: vi.fn(),
  triggerAgentUpdate: vi.fn(),
  listProbeEligibleAgents: vi.fn(),
}));

const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

// The identity of this object is stable on purpose: a fresh Map per render
// would re-fire the page's live-update effects on every commit.
const mockTelemetryStream = vi.hoisted(() => ({ data: new Map(), connected: true }));
vi.mock('../hooks/useTelemetryStream', () => ({ useTelemetryStream: () => mockTelemetryStream }));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

const tree = (tab) => (
  <MemoryRouter initialEntries={[`/agents/3?tab=${tab}`]}>
    <Routes>
      <Route path="/agents/:id" element={<AgentDetailPage />} />
    </Routes>
  </MemoryRouter>
);

describe('hotMetrics', () => {
  it('names nothing while every metric is under its threshold', () => {
    expect(hotMetrics({ cpu_pct: 12, mem_pct: 38, root_disk_pct: 61, max_temp_c: 44 })).toEqual([]);
  });

  it('names a metric at or over its threshold', () => {
    expect(hotMetrics({ cpu_pct: METRIC_THRESHOLDS.cpu_pct, mem_pct: 10 })).toEqual(['cpu_pct']);
  });

  it('names several, in a stable order', () => {
    expect(hotMetrics({ cpu_pct: 95, mem_pct: 5, root_disk_pct: 99, max_temp_c: 90 })).toEqual([
      'cpu_pct',
      'root_disk_pct',
      'max_temp_c',
    ]);
  });

  it('ignores metrics the sample did not carry', () => {
    expect(hotMetrics({ cpu_pct: null, mem_pct: undefined })).toEqual([]);
  });

  it('ignores a summary that has not arrived', () => {
    expect(hotMetrics(null)).toEqual([]);
  });
});

describe('useTabActivity', () => {
  const mount = (initial) =>
    renderHook(({ activeTab, signals }) => useTabActivity({ activeTab, signals }), {
      initialProps: initial,
    });

  it('raises nothing on first render', () => {
    // Everything is new on mount. Lighting every tab would say nothing.
    const { result } = mount({ activeTab: 'overview', signals: { telemetry: '', events: 3 } });
    expect(result.current.telemetry).toBeNull();
    expect(result.current.events).toBeNull();
  });

  it('raises a flag when a signal changes on an inactive tab', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { telemetry: '' } });
    rerender({ activeTab: 'overview', signals: { telemetry: 'cpu_pct' } });
    expect(result.current.telemetry).toBe(true);
  });

  it('raises nothing when the change is on the tab being watched', () => {
    const { result, rerender } = mount({ activeTab: 'telemetry', signals: { telemetry: '' } });
    rerender({ activeTab: 'telemetry', signals: { telemetry: 'cpu_pct' } });
    expect(result.current.telemetry).toBeNull();
  });

  it('counts how many arrived for a numeric signal', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: 3 } });
    rerender({ activeTab: 'overview', signals: { events: 6 } });
    expect(result.current.events).toBe(3);
  });

  it('does not count a numeric signal going down', () => {
    // A shrinking list is a reload, not new activity.
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: 6 } });
    rerender({ activeTab: 'overview', signals: { events: 2 } });
    expect(result.current.events).toBeNull();
  });

  it('clears and rebaselines when its tab is selected', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: 3 } });
    rerender({ activeTab: 'overview', signals: { events: 6 } });
    expect(result.current.events).toBe(3);

    rerender({ activeTab: 'events', signals: { events: 6 } });
    expect(result.current.events).toBeNull();

    // Rebaselined: the next arrival counts from 6, not from 3.
    rerender({ activeTab: 'overview', signals: { events: 7 } });
    expect(result.current.events).toBe(1);
  });

  it('stays quiet while a signal is still unknown', () => {
    // `null` is "the request behind this has not resolved". The first load
    // filling the page is not activity, and a page that lights every tab on
    // arrival has said nothing.
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: null } });
    rerender({ activeTab: 'overview', signals: { events: 12 } });
    expect(result.current.events).toBeNull();
  });

  it('counts from the first value it was given once that value is known', () => {
    const { result, rerender } = mount({ activeTab: 'overview', signals: { events: null } });
    rerender({ activeTab: 'overview', signals: { events: 12 } });
    rerender({ activeTab: 'overview', signals: { events: 14 } });
    expect(result.current.events).toBe(2);
  });

  it('tracks each tab independently', () => {
    const { result, rerender } = mount({
      activeTab: 'overview',
      signals: { telemetry: '', discovery: 'job-1' },
    });
    rerender({ activeTab: 'overview', signals: { telemetry: 'cpu_pct', discovery: 'job-1' } });
    expect(result.current.telemetry).toBe(true);
    expect(result.current.discovery).toBeNull();
  });
});

describe('a spike on a tab you are not looking at', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const api = await import('../api/agents');
    api.getAgent.mockResolvedValue({ data: { ...AGENT } });
    api.getAgentEvents.mockResolvedValue({ data: [] });
    api.getAgentProbes.mockResolvedValue({
      data: { agent_id: 3, max_concurrent: 20, active_runs: 0, assignments: [] },
    });
    api.getAgentTelemetry.mockResolvedValue({ data: coolTelemetry });
    api.getAgentTelemetryHistory.mockResolvedValue({ data: { points: [] } });
    api.getAgentsPresence.mockResolvedValue({
      data: [{ agent_id: 3, online: true, connected_since: null, last_seen_at: null }],
    });
    api.getCapabilityDefaults.mockResolvedValue({
      data: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
    });
    api.getAgentDiscovery.mockResolvedValue({ data: null });
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    // Seeded so the page's stream is already "delivering" at mount: the sample
    // push below must not be the thing that flips that, because the resulting
    // poll would land after the merge and overwrite it.
    mockTelemetryStream.data = new Map([['seed:unrelated', {}]]);
  });

  const telemetryTab = () => screen.getByRole('tab', { name: /^Telemetry/ });

  it('raises an indicator on the Telemetry tab, and clears it when you go there', async () => {
    const { rerender } = render(tree('discovery'));

    // Parked on Discovery, with a healthy sample already on screen.
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Discovery' })).toBeTruthy());
    expect(telemetryTab()).toHaveAccessibleName('Telemetry');

    mockTelemetryStream.data = new Map([
      ['seed:unrelated', {}],
      [
        'agent:3',
        {
          type: 'telemetry.host',
          agent_id: 3,
          collected_at: new Date().toISOString(),
          payload: { status: 'ok', summary: { cpu_pct: 96 } },
        },
      ],
    ]);
    rerender(tree('discovery'));

    // The operator never left Discovery, and still hears about the spike.
    await waitFor(() => expect(telemetryTab()).toHaveAccessibleName('Telemetry — new activity'));
    expect(document.querySelector('.cb-tab__indicator')).toBeTruthy();
    // …and the strip, which is on screen on every tab, marks which metric.
    expect(document.querySelector('.agent-strip__metric[data-metric="cpu_pct"]').dataset.hot).toBe(
      'true'
    );

    fireEvent.click(telemetryTab());
    await waitFor(() => expect(telemetryTab()).toHaveAccessibleName('Telemetry'));
  });

  it('says nothing for a sample that crosses no threshold', async () => {
    const { rerender } = render(tree('discovery'));
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Discovery' })).toBeTruthy());

    mockTelemetryStream.data = new Map([
      ['seed:unrelated', {}],
      [
        'agent:3',
        {
          type: 'telemetry.host',
          agent_id: 3,
          collected_at: new Date().toISOString(),
          payload: { status: 'ok', summary: { cpu_pct: 31 } },
        },
      ],
    ]);
    rerender(tree('discovery'));

    // At a ten-second cadence a dot per sample would be lit permanently,
    // which says exactly as much as no dot at all.
    await waitFor(() => expect(screen.getByText('31.0%')).toBeTruthy());
    expect(telemetryTab()).toHaveAccessibleName('Telemetry');
  });
});
