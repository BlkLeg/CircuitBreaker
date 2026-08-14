import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetRow from '../components/agents/FleetRow';

/**
 * FleetRow's four variants (design §5): online, offline, telemetry-off and
 * pending-pinned. They exist because the same eleven columns have to answer
 * four different questions, and each variant has a specific way of lying:
 *
 *   online        — nothing, as long as the head values come from the poll.
 *   offline       — a stored uptime rendered as if the host were still up.
 *   telemetry-off — `latest: null` rendered as 0%, which reads as "idle host"
 *                   when the truth is "nobody granted the capability".
 *   pending       — a machine nobody has verified, shown as fleet data.
 *
 * Plus the spool backlog chip, which the design calls "the one signal that
 * predicts trouble before anything goes red" — a row that is online, green and
 * quietly buffering everything it collects.
 */

// normalizeCapability is pulled through importActual rather than re-implemented:
// a withheld grant arrives as {enabled: false, config: {}}, which is truthy, and
// a hand-written stub would keep passing after the real normalizer's semantics
// changed — exactly the drift this row's Caps cell has to survive.
vi.mock('../api/agents', async () => {
  const actual = await vi.importActual('../api/agents');
  return { normalizeCapability: actual.normalizeCapability };
});

const LATEST = {
  collected_at: '2026-08-14T10:00:00Z',
  cpu_pct: 62,
  mem_pct: 44,
  root_disk_pct: 71,
  net_rx_bps: 1_400_000,
  net_tx_bps: 340_000,
  max_temp_c: 54,
  load_1: 0.8,
  uptime_s: 273_600, // 3d 4h
};

const ONLINE_AGENT = {
  id: 2,
  status: 'active',
  name: null,
  hostname: 'box2',
  os: 'linux',
  arch: 'amd64',
  agent_version: '0.1.0',
  fingerprint: 'b'.repeat(32),
  last_seen_at: '2026-08-14T10:00:00Z',
  online: true,
  connected_since: '2026-08-14T08:00:00Z',
  capabilities: {
    host_telemetry: { enabled: true, config: { interval_s: 30 } },
    remote_probe: { enabled: false, config: {} },
  },
  hardware: null,
  latest: LATEST,
  spool_depth: 0,
  series: { cpu_pct: [40, 55, 62], mem_pct: [44, 44, 44], net_rx_bps: [1, 2, 3] },
};

function renderRow(agent, handlers = {}) {
  return render(
    <MemoryRouter>
      <table>
        <tbody>
          <FleetRow agent={agent} {...handlers} />
        </tbody>
      </table>
    </MemoryRouter>
  );
}

const rowOf = () => screen.getAllByRole('row')[0];

describe('FleetRow online variant', () => {
  beforeEach(() => vi.clearAllMocks());

  it('prints the head values the poll owns, with a sparkline beside the moving ones', () => {
    const { container } = renderRow(ONLINE_AGENT);

    expect(rowOf()).toHaveAttribute('data-state', 'online');
    expect(screen.getByText('online')).toBeInTheDocument();
    expect(screen.getByText('62%')).toBeInTheDocument();
    expect(screen.getByText('44%')).toBeInTheDocument();
    expect(screen.getByText('71%')).toBeInTheDocument();
    expect(screen.getByText('54°C')).toBeInTheDocument();
    expect(screen.getByText('3d 4h')).toBeInTheDocument();
    // CPU, Mem and Net move on a 30-minute scale and get a line; disk and
    // temperature do not, so they are head-value only and drawing them would
    // cost a row of pixels to say nothing.
    expect(container.querySelectorAll('.fleet-spark')).toHaveLength(3);
  });

  it('reads network rates in the decimal units every other tool quotes', () => {
    renderRow(ONLINE_AGENT);

    expect(screen.getByText('↓1.4 MB/s ↑340 kB/s')).toBeInTheDocument();
  });

  it('tones a metric by its own threshold rather than one shared band', () => {
    // 82% memory is unremarkable on a box with a big page cache; 82% CPU is
    // not. The two thresholds are separate constants for that reason.
    renderRow({
      ...ONLINE_AGENT,
      latest: { ...LATEST, cpu_pct: 95, mem_pct: 82, root_disk_pct: 12 },
    });

    expect(screen.getByText('95%')).toHaveAttribute('data-tone', 'critical');
    expect(screen.getByText('82%')).toHaveAttribute('data-tone', 'warn');
    expect(screen.getByText('12%')).toHaveAttribute('data-tone', 'ok');
  });

  it('shows only the capabilities actually granted, in full', () => {
    renderRow(ONLINE_AGENT);

    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    // {enabled: false, config: {}} is truthy — the object is never the test.
    expect(screen.queryByText('Remote probe')).not.toBeInTheDocument();
  });

  it('offers Revoke on an active agent and Delete once it is not', () => {
    const onRevoke = vi.fn();
    const onDelete = vi.fn();
    const { unmount } = renderRow(ONLINE_AGENT, { onRevoke, onDelete });

    fireEvent.click(screen.getByRole('button', { name: 'Revoke' }));
    expect(onRevoke).toHaveBeenCalledWith(ONLINE_AGENT);
    unmount();

    const revoked = { ...ONLINE_AGENT, status: 'revoked' };
    renderRow(revoked, { onRevoke, onDelete });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onDelete).toHaveBeenCalledWith(revoked);
  });
});

describe('FleetRow offline variant', () => {
  const OFFLINE_AGENT = {
    ...ONLINE_AGENT,
    online: false,
    connected_since: null,
    last_seen_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    spool_depth: 118,
  };

  it('collapses the metric columns into how long it has been gone', () => {
    renderRow(OFFLINE_AGENT);

    expect(rowOf()).toHaveAttribute('data-state', 'offline');
    expect(screen.getByText('offline')).toBeInTheDocument();
    expect(screen.getByText(/down 2h/)).toBeInTheDocument();
    expect(screen.getByText(/last seen/)).toBeInTheDocument();
  });

  it('never shows a metric or an uptime measured before the agent vanished', () => {
    // The stored `latest` is a snapshot from before it went away. Printing 62%
    // beside an offline dot claims a reading nobody took, and "3d 4h uptime"
    // claims a host that is currently unreachable is still up.
    renderRow(OFFLINE_AGENT);

    expect(screen.queryByText('62%')).not.toBeInTheDocument();
    expect(screen.queryByText('54°C')).not.toBeInTheDocument();
    expect(screen.queryByText('3d 4h')).not.toBeInTheDocument();
  });

  it('says what the agent will replay when it comes back', () => {
    renderRow(OFFLINE_AGENT);

    expect(screen.getByText(/spool 118/)).toBeInTheDocument();
  });
});

describe('FleetRow telemetry-off variant', () => {
  // Design §4 and §1.3, stated twice in the design because it is the row's
  // worst failure: `latest: null` is a real state and must NEVER render as 0%.
  const NO_TELEMETRY_AGENT = {
    ...ONLINE_AGENT,
    latest: null,
    series: undefined,
    capabilities: { host_telemetry: { enabled: false, config: {} } },
  };

  it('reads "telemetry off" and hints that it is a capability grant', () => {
    renderRow(NO_TELEMETRY_AGENT);

    const cell = screen.getByText('telemetry off');
    expect(cell).toBeInTheDocument();
    expect(cell).toHaveAttribute('title', 'Host telemetry is not granted to this agent');
  });

  it('renders no zero anywhere — a missing reading is not an idle host', () => {
    const { container } = renderRow(NO_TELEMETRY_AGENT);

    expect(screen.queryByText('0%')).not.toBeInTheDocument();
    expect(screen.queryByText('0°C')).not.toBeInTheDocument();
    expect(container.querySelectorAll('.fleet-spark')).toHaveLength(0);
    // Still an online agent: the dot is the one thing that does not depend on
    // host telemetry, and losing it would make a healthy agent look absent.
    expect(rowOf()).toHaveAttribute('data-state', 'online');
    expect(screen.getByText('online')).toBeInTheDocument();
  });

  it('still prints a real zero when the agent actually reported one', () => {
    // The other half of the rule: 0% is a legitimate reading from an idle box,
    // and suppressing it would be the same lie in the opposite direction.
    renderRow({ ...ONLINE_AGENT, latest: { ...LATEST, cpu_pct: 0 } });

    expect(screen.getByText('0%')).toBeInTheDocument();
  });
});

describe('FleetRow pending-pinned variant', () => {
  const PENDING_AGENT = {
    id: 7,
    status: 'pending',
    name: null,
    hostname: 'freshbox',
    os: 'linux',
    arch: 'arm64',
    fingerprint: 'abcd1234'.padEnd(32, 'f'),
    online: null,
    capabilities: {},
    hardware: null,
    latest: null,
  };

  it('carries the state the amber left edge is keyed off', () => {
    renderRow(PENDING_AGENT);

    expect(rowOf()).toHaveAttribute('data-state', 'pending');
  });

  it('asks for a decision instead of pretending to have measurements', () => {
    renderRow(PENDING_AGENT);

    expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument();
    expect(screen.getByText('linux / arm64')).toBeInTheDocument();
    expect(screen.queryByText('telemetry off')).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('shows enough fingerprint to start the comparison, with the whole of it on hover', () => {
    renderRow(PENDING_AGENT);
    const chip = screen.getByTitle(PENDING_AGENT.fingerprint);

    expect(chip).toHaveTextContent('abcd1234');
  });

  it('routes the decision through Review rather than a one-click Delete', () => {
    // Rejecting an enrolment is a judgement about an identity, so it belongs
    // behind the fingerprint comparison — not next to a destructive button on
    // a row nobody has verified yet.
    const onReview = vi.fn();
    const onDelete = vi.fn();
    renderRow(PENDING_AGENT, { onReview, onDelete });

    const row = rowOf();
    expect(within(row).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: 'Review' }));
    expect(onReview).toHaveBeenCalledWith(PENDING_AGENT);
  });
});

describe('FleetRow spool backlog', () => {
  it('flags an online agent that is quietly buffering', () => {
    // Design §4: the one signal that predicts trouble before anything goes red.
    // The agent is up, green and reporting — and none of it is reaching us.
    renderRow({ ...ONLINE_AGENT, spool_depth: 42 });

    const chip = screen.getByText(/spool 42/);
    expect(chip).toHaveAttribute('data-tone', 'warn');
    expect(chip).toHaveAttribute('title', expect.stringMatching(/not yet drained/i));
  });

  it('stays quiet on a drained spool, and on one that was never reported', () => {
    // 0 means "reported, drained" and null means "never reported" — neither is
    // a backlog, and a chip on every healthy row would train the eye past it.
    renderRow(ONLINE_AGENT);
    expect(screen.queryByText(/spool/)).not.toBeInTheDocument();

    renderRow({ ...ONLINE_AGENT, spool_depth: null });
    expect(screen.queryByText(/spool/)).not.toBeInTheDocument();
  });
});

describe('FleetRow identity', () => {
  it('links to the detail page under the name an operator recognises', () => {
    renderRow({ ...ONLINE_AGENT, name: 'Rack A probe' });

    const link = screen.getByRole('link', { name: 'Rack A probe' });
    expect(link).toHaveAttribute('href', '/agents/2');
    // The hostname stays beneath it — the name is what an operator chose, the
    // hostname is what they will grep the logs for.
    expect(screen.getByText('box2')).toBeInTheDocument();
  });

  it('does not print the hostname twice when it is the only label there is', () => {
    renderRow(ONLINE_AGENT);

    expect(screen.getAllByText('box2')).toHaveLength(1);
  });

  it('names the linked hardware in the same cell', () => {
    renderRow({ ...ONLINE_AGENT, hardware: { id: 9, name: 'rack-a-switch' } });

    expect(screen.getByText('rack-a-switch')).toBeInTheDocument();
  });

  it('chips a non-active status so a revoked agent cannot pass as fleet', () => {
    renderRow({ ...ONLINE_AGENT, status: 'revoked' });

    expect(screen.getByText('revoked')).toHaveAttribute('data-tone', 'critical');
  });
});
