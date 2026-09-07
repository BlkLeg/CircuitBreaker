import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AgentTelemetryTab, { SUMMARY_LABELS } from '../components/agents/AgentTelemetryTab';

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
}));

const HOST_DEFAULTS = { interval_s: 30 };

const withLatest = (overrides = {}) => ({
  capability: { config: { interval_s: 30 } },
  latest: {
    collected_at: new Date().toISOString(),
    projected: false,
    summary: { cpu_pct: 12, mem_pct: 38, root_disk_pct: 61, net_rx_bps: 2400, max_temp_c: 44 },
    payload: {},
  },
  readiness: [],
  spool: { depth: 0 },
  ...overrides,
});

function renderTab(props = {}) {
  return render(
    <AgentTelemetryTab
      telemetry={null}
      history={[]}
      historyRange="1h"
      onHistoryRange={() => {}}
      hostDefaults={HOST_DEFAULTS}
      hasHardware={false}
      {...props}
    />
  );
}

describe('AgentTelemetryTab', () => {
  it('says no samples have arrived rather than rendering empty tiles', () => {
    renderTab();
    expect(screen.getByText('No host samples received yet.')).toBeTruthy();
  });

  it('shows the spool backlog even when no sample has ever been delivered', () => {
    // An agent that buffered samples but delivered none is exactly when the
    // backlog is worth showing — nothing else here would explain the blank.
    renderTab({ telemetry: { latest: null, readiness: [], spool: { depth: 42 } } });
    expect(screen.getByText(/42 samples buffered/)).toBeTruthy();
  });

  it('shows no backlog indicator for a drained spool', () => {
    renderTab({ telemetry: { latest: null, readiness: [], spool: { depth: 0 } } });
    expect(screen.queryByText(/samples buffered/)).toBeNull();
  });

  it('renders a tile per summary metric once a sample exists', () => {
    // One per SUMMARY_LABELS entry, not one per metric the sample carried: a
    // metric the host stopped reporting has to keep its tile and say so,
    // rather than silently shortening the grid.
    const { container } = renderTab({ telemetry: withLatest() });
    expect(container.querySelectorAll('.cb-tile')).toHaveLength(Object.keys(SUMMARY_LABELS).length);
  });

  it('names an absent metric rather than leaving its tile blank', () => {
    const { container } = renderTab({ telemetry: withLatest() });
    // net_tx_bps, load_1 and uptime_s are absent from the fixture's summary.
    const values = [...container.querySelectorAll('.cb-tile__value')].map((el) => el.textContent);
    expect(values).toContain('Unavailable');
    expect(values).not.toContain('');
  });

  it('raises a banner for a degraded collector', () => {
    const { container } = renderTab({
      telemetry: withLatest({
        readiness: [
          {
            collector: 'host.cpu',
            state: 'degraded',
            reason: 'cannot read /proc',
            remediation: 'check perms',
          },
        ],
      }),
    });
    expect(container.querySelector('.cb-banner')).toBeTruthy();
    expect(screen.getByText(/cannot read \/proc/)).toBeTruthy();
  });

  it('does not raise a banner for a collector that is merely switched off', () => {
    // A disabled collector is a choice, not a fault.
    const { container } = renderTab({
      telemetry: withLatest({ readiness: [{ collector: 'host.docker', state: 'disabled' }] }),
    });
    expect(container.querySelector('.cb-banner')).toBeNull();
  });

  it('passes only the container rows to the device table, never the docker dict', () => {
    // payload.docker is {containers, total, running, truncated}. Handing the
    // dict to DeviceTable makes Object.keys(rows[0]) a nonsense header.
    renderTab({
      telemetry: withLatest({
        latest: {
          ...withLatest().latest,
          payload: {
            docker: {
              total: 2,
              running: 1,
              truncated: false,
              containers: [{ id: 'abc', name: 'web', image: 'nginx', state: 'running' }],
            },
          },
        },
      }),
    });
    expect(screen.getByText('1 of 2 containers running')).toBeTruthy();
    expect(screen.getByText('web')).toBeTruthy();
  });

  it('reports the selected history range and reports a change', async () => {
    const onHistoryRange = vi.fn();
    renderTab({ telemetry: withLatest(), historyRange: '6h', onHistoryRange });
    const select = screen.getByLabelText(/History range/);
    expect(select.value).toBe('6h');
  });

  it('offers to link hardware when none is linked', () => {
    renderTab({ telemetry: withLatest(), hasHardware: false });
    expect(
      screen.getByText(
        'Link this agent to Hardware to add topology, analytics, and Hardware telemetry views.'
      )
    ).toBeTruthy();
  });

  it('says nothing about hardware when hardware is already linked', () => {
    renderTab({ telemetry: withLatest(), hasHardware: true });
    expect(screen.queryByText(/Link this agent to Hardware/)).toBeNull();
  });

  it('renders the host-telemetry settings the registry declares', () => {
    // Spec §7 puts the cadence settings on this tab. The key list comes from
    // the fetched registry, so a collector only the server knows about still
    // gets a control.
    renderTab({
      telemetry: withLatest(),
      capabilities: { host_telemetry: { enabled: true, config: {} } },
      capabilityDefaults: { host_telemetry: { config: {} } },
      hostDefaults: { interval_s: 45, include_gpu: true },
      onUpdateHostConfig: () => {},
    });
    expect(screen.getByLabelText(/cadence/i).value).toBe('45');
    expect(screen.getByLabelText(/^gpu$/i).checked).toBe(true);
  });

  it('renders no settings for an agent that is not granted host telemetry', () => {
    renderTab({
      telemetry: withLatest(),
      capabilities: { host_telemetry: { enabled: false, config: {} } },
      capabilityDefaults: { host_telemetry: { config: {} } },
      onUpdateHostConfig: () => {},
    });
    expect(screen.queryByLabelText(/cadence/i)).toBeNull();
  });
});

describe('the permanent-loss banner (plan Phase 3)', () => {
  const LOSS = {
    depth: 4096,
    bytes: 67108864,
    evicted_frames: 9412,
    evicted_bytes: 33554432,
    evicted_oldest_at: '2026-09-01T00:00:00Z',
    evicted_newest_at: '2026-09-03T18:30:00Z',
  };

  it('names the destroyed observations, the size and the window', () => {
    renderTab({ telemetry: withLatest({ spool: LOSS }) });

    expect(screen.getByText(/Part of this host.s history is permanently missing/)).toBeTruthy();
    expect(screen.getByText(/permanently discarded 9,412 buffered observations/)).toBeTruthy();
    expect(screen.getByText(/The gap covers/)).toBeTruthy();
  });

  it('counts the frames this server refused separately from what the agent destroyed', () => {
    // Two losses with two different remedies. Collapsing them into one number
    // would name neither.
    renderTab({
      telemetry: withLatest({
        spool: { depth: 0, refused_frames: 512, refused_last_reason: 'capability_withheld' },
      }),
    });

    const body = screen.getByText(/refused and dropped 512 frames/);
    expect(body).toBeTruthy();
    expect(body.textContent).toMatch(/host telemetry capability is switched off/);
  });

  it('sits alongside the catch-up indicator, not inside it', () => {
    // Catch-up clears when the backlog drains; this does not. One replacing
    // the other is exactly how the loss stayed invisible.
    renderTab({ telemetry: withLatest({ spool: LOSS }) });

    expect(screen.getByText(/4096 samples buffered/)).toBeTruthy();
    expect(screen.getByText(/permanently missing/)).toBeTruthy();
  });

  it('still renders before any sample has arrived', () => {
    renderTab({ telemetry: { latest: null, readiness: [], spool: LOSS } });

    expect(screen.getByText(/permanently missing/)).toBeTruthy();
  });

  it('renders nothing when the counters are null or zero', () => {
    const { unmount } = renderTab({ telemetry: withLatest({ spool: { depth: 0 } }) });
    expect(screen.queryByText(/permanently missing/)).toBeNull();
    unmount();

    renderTab({
      telemetry: withLatest({ spool: { depth: 0, evicted_frames: 0, refused_frames: 0 } }),
    });
    expect(screen.queryByText(/permanently missing/)).toBeNull();
  });
});
