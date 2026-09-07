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

// The spool block always carries a report time, because the tab distinguishes
// a backlog it can still call current from one frozen by an outage. A fixture
// without it describes the second, which is a different indicator entirely —
// phase 4's own cases are at the bottom of this file.
const FRESH_REPORT = () => new Date(Date.now() - 15_000).toISOString();

const withLatest = (overrides = {}) => ({
  capability: { config: { interval_s: 30 } },
  latest: {
    collected_at: new Date().toISOString(),
    projected: false,
    summary: { cpu_pct: 12, mem_pct: 38, root_disk_pct: 61, net_rx_bps: 2400, max_temp_c: 44 },
    payload: {},
  },
  readiness: [],
  spool: { depth: 0, reported_at: FRESH_REPORT() },
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
    renderTab({
      telemetry: {
        latest: null,
        readiness: [],
        spool: { depth: 42, reported_at: FRESH_REPORT() },
      },
    });
    expect(screen.getByText(/42 samples buffered/)).toBeTruthy();
  });

  it('shows no backlog indicator for a drained spool', () => {
    renderTab({
      telemetry: { latest: null, readiness: [], spool: { depth: 0, reported_at: FRESH_REPORT() } },
    });
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
    reported_at: FRESH_REPORT(),
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
        spool: {
          depth: 0,
          reported_at: FRESH_REPORT(),
          refused_frames: 512,
          refused_last_reason: 'capability_withheld',
        },
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
    const { unmount } = renderTab({
      telemetry: withLatest({ spool: { depth: 0, reported_at: FRESH_REPORT() } }),
    });
    expect(screen.queryByText(/permanently missing/)).toBeNull();
    unmount();

    renderTab({
      telemetry: withLatest({ spool: { depth: 0, evicted_frames: 0, refused_frames: 0 } }),
    });
    expect(screen.queryByText(/permanently missing/)).toBeNull();
  });
});

describe('a backlog reading that is no longer current (plan Phase 4)', () => {
  const STALE_AT = '2026-09-05T09:00:00Z';
  const stale = (depth, extra = {}) => ({ depth, reported_at: STALE_AT, stale: true, ...extra });

  it('replaces the live catch-up indicator with a last-known value and its time', () => {
    // "Catching up · N samples buffered" describes motion — a backlog draining
    // right now. The agent reports its backlog only while connected, so
    // rendering that from a frozen number animates a measurement nobody took.
    renderTab({ telemetry: withLatest({ spool: stale(1195, { bytes: 240000 }) }) });

    expect(screen.getByText(/Backlog unknown · last known 1195 buffered/)).toBeTruthy();
    expect(screen.queryByText(/Catching up/)).toBeNull();
  });

  it('drops the live styling with it', () => {
    // The pill is amber and uppercase because it means "this is happening".
    // Keeping the treatment while the number is stale would keep the claim.
    const { container } = renderTab({ telemetry: withLatest({ spool: stale(1195) }) });

    expect(container.querySelector('.agent-telemetry__catchup')).toBeNull();
    expect(container.querySelector('.agent-telemetry__last-known')).toBeTruthy();
  });

  it('says so even when the frozen value is zero — the bug this fixes', () => {
    // The observed shape: hours offline, 1,195 frames on disk, stored depth 0.
    // The old rule rendered nothing at all for it, which reads as "drained".
    renderTab({ telemetry: withLatest({ spool: stale(0) }) });

    expect(screen.getByText(/Backlog unknown · last known 0 buffered/)).toBeTruthy();
  });

  it('renders nothing for an agent that never reported a backlog', () => {
    // Null predates spool reporting. There is no reading to qualify.
    renderTab({ telemetry: withLatest({ spool: { depth: null, reported_at: null } }) });

    expect(screen.queryByText(/Backlog unknown/)).toBeNull();
    expect(screen.queryByText(/Catching up/)).toBeNull();
  });

  it('keeps the destroyed-history banner beside it', () => {
    // Phase 3's fact and this one are independent. "History was destroyed" is
    // cumulative and stays true however stale the current reading is; letting
    // the unknown swallow it would hide the permanent loss behind a temporary
    // one.
    renderTab({
      telemetry: withLatest({
        spool: stale(0, { evicted_frames: 9412, evicted_bytes: 33554432 }),
      }),
    });

    expect(screen.getByText(/Backlog unknown/)).toBeTruthy();
    expect(screen.getByText(/permanently missing/)).toBeTruthy();
  });

  it('never prints a confident "0 buffered" in the workbench spool stat', () => {
    // Same silent zero, second location: `{depth ?? 0} buffered` read as a
    // measurement for both a stale reading and one that never happened.
    // The stat lives in the workbench, which needs two points to draw.
    const HISTORY = [
      { collected_at: '2026-09-05T09:00:00Z', summary: { cpu_pct: 10 } },
      { collected_at: '2026-09-05T09:01:00Z', summary: { cpu_pct: 12 } },
    ];
    const { unmount } = renderTab({
      history: HISTORY,
      telemetry: withLatest({ spool: stale(1195) }),
    });
    expect(screen.getByText(/unknown · last 1195/)).toBeTruthy();
    unmount();

    renderTab({
      history: HISTORY,
      telemetry: withLatest({ spool: { depth: null, reported_at: null } }),
    });
    expect(screen.getByText('not reported')).toBeTruthy();
    expect(screen.queryByText(/0 buffered/)).toBeNull();
  });
});
