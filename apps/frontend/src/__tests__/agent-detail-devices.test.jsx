import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import {
  renderDetail,
  openTab,
  telemetryFixture,
  findCards,
  cardValue,
  telemetryBanners,
  findTelemetryBanners,
} from './helpers/agentDetailHarness';

// Task 19: the default API responses live here rather than inline in the
// vi.mock factory so that beforeEach can *restore* them. `vi.clearAllMocks()`
// clears call records but leaves implementations installed, so a
// `mockResolvedValue` set by one test silently became the fixture for every
// test after it — the `hardware: null` presence override in the online/offline
// tests was reaching the telemetry tests below, and the never-resolving
// `getCapabilityDefaults` was reaching everything after it. Re-applying every
// implementation in beforeEach makes each test start from the same fixture.
const apiDefaults = vi.hoisted(() => {
  const agent = {
    id: 3,
    name: null,
    hostname: 'box1',
    status: 'active',
    fingerprint: 'a'.repeat(32),
    agent_version: '0.1.0',
    capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
  };
  return {
    agent,
    getAgent: () => Promise.resolve({ data: { ...agent } }),
    getAgentEvents: () =>
      Promise.resolve({
        data: [{ id: 1, event_type: 'approved', created_at: '2026-07-27T12:00:00Z', detail: null }],
      }),
    // Slice 3 Task 21: the page now also loads its assigned probes. Empty
    // here — the assigned-probes surface has its own suite
    // (agent-assigned-probes.test.jsx); this fixture only has to keep the
    // section from reporting a load failure in every unrelated test.
    getAgentProbes: () =>
      Promise.resolve({
        data: { agent_id: 3, max_concurrent: 20, active_runs: 0, assignments: [] },
      }),
    getAgentTelemetry: () => Promise.resolve({ data: { latest: null, readiness: [] } }),
    getAgentTelemetryHistory: () => Promise.resolve({ data: { points: [] } }),
    getAgentsPresence: () =>
      Promise.resolve({
        data: [
          {
            agent_id: 3,
            online: true,
            connected_since: '2026-08-04T10:00:00Z',
            last_seen_at: '2026-08-04T10:05:00Z',
            capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
            hardware: {
              id: 5,
              name: 'lab-nas',
              hostname: 'nas.local',
              ip_address: null,
              mac_address: null,
            },
          },
        ],
      }),
    // Task 14: HOST_DEFAULTS is gone from the page; the host-telemetry config
    // key list and every fallback value come from the server registry. This
    // fixture deliberately carries a key the frontend has never heard of
    // (`include_gpu`) so the test proves the page renders whatever the server
    // declares rather than a hardcoded copy.
    getCapabilityDefaults: () =>
      Promise.resolve({
        data: {
          host_telemetry: {
            enabled: true,
            config: {
              interval_s: 45,
              include_filesystems: true,
              include_disks: true,
              include_network: true,
              include_temperatures: true,
              include_virtual: false,
              include_docker: false,
              include_gpu: true,
            },
          },
          remote_probe: { enabled: true, config: {} },
          local_discovery: { enabled: true, config: {} },
        },
      }),
    setAgentCapabilities: () => Promise.resolve({ data: { ...agent } }),
    revokeAgent: () => Promise.resolve({ data: {} }),
    triggerAgentUpdate: () => Promise.resolve({ data: {} }),
  };
});

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
  getAgent: vi.fn(apiDefaults.getAgent),
  getAgentEvents: vi.fn(apiDefaults.getAgentEvents),
  getAgentProbes: vi.fn(apiDefaults.getAgentProbes),
  getAgentTelemetry: vi.fn(apiDefaults.getAgentTelemetry),
  getAgentTelemetryHistory: vi.fn(apiDefaults.getAgentTelemetryHistory),
  getAgentsPresence: vi.fn(apiDefaults.getAgentsPresence),
  getCapabilityDefaults: vi.fn(apiDefaults.getCapabilityDefaults),
  setAgentCapabilities: vi.fn(apiDefaults.setAgentCapabilities),
  revokeAgent: vi.fn(apiDefaults.revokeAgent),
  triggerAgentUpdate: vi.fn(apiDefaults.triggerAgentUpdate),
  // Slice 4 Task 27: AgentDetailPage now also loads GET /agents/{id}/discovery
  // for the Discovery scope section. Plain functions rather than vi.fn(): these
  // tests assert nothing about discovery, and a stub with no implementation
  // would throw inside the page's loader.
  getAgentDiscovery: () => Promise.resolve({ data: null }),
  pauseAgentDiscovery: () => Promise.resolve({ data: null }),
  resumeAgentDiscovery: () => Promise.resolve({ data: null }),
}));

// See agents-page.test.jsx for why useAgentLive needs vi.hoisted() here.
const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

// Task 18: the page consumes the telemetry stream's `data` Map directly, so
// the tests drive it by swapping the Map. The returned object identity is
// stable across renders on purpose — a fresh object (or a fresh Map) per
// render would re-fire the live-update effects on every commit.
const mockTelemetryStream = vi.hoisted(() => ({ data: new Map(), connected: true }));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => mockTelemetryStream,
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

// The unverified-clock caveat is conditional on the offset having been
// measured, and nothing in this suite carries a Date header, so one test has to
// say it was. Only serverClockOffsetMs is replaced — lib/agentState's serverNow
// keeps the real implementation.
const mockClockOffsetMs = vi.hoisted(() => vi.fn(() => null));
vi.mock('../utils/serverClock', async (importOriginal) => ({
  ...(await importOriginal()),
  serverClockOffsetMs: mockClockOffsetMs,
}));

describe('AgentDetailPage', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    // clearAllMocks does NOT restore implementations; do it explicitly so no
    // test inherits another test's mockResolvedValue.
    const api = await import('../api/agents');
    api.getAgent.mockImplementation(apiDefaults.getAgent);
    api.getAgentEvents.mockImplementation(apiDefaults.getAgentEvents);
    api.getAgentProbes.mockImplementation(apiDefaults.getAgentProbes);
    api.getAgentTelemetry.mockImplementation(apiDefaults.getAgentTelemetry);
    api.getAgentTelemetryHistory.mockImplementation(apiDefaults.getAgentTelemetryHistory);
    api.getAgentsPresence.mockImplementation(apiDefaults.getAgentsPresence);
    api.getCapabilityDefaults.mockImplementation(apiDefaults.getCapabilityDefaults);
    api.setAgentCapabilities.mockImplementation(apiDefaults.setAgentCapabilities);
    api.revokeAgent.mockImplementation(apiDefaults.revokeAgent);
    api.triggerAgentUpdate.mockImplementation(apiDefaults.triggerAgentUpdate);
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    mockTelemetryStream.data = new Map();
    mockClockOffsetMs.mockReturnValue(null);
  });

  afterEach(() => {
    // vi.restoreAllMocks() undoes any vi.spyOn() stubs from this file's own
    // tests. This file has none today; it is kept here, as it was in the
    // original single-file suite, for parity with agent-detail-capabilities.test.jsx,
    // whose window.confirm stub does need it.
    vi.restoreAllMocks();
  });

  describe('device tables', () => {
    it('derives one header cell per key of the first row and one row per entry', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              filesystems: [
                { device: '/dev/sda1', mountpoint: '/', used_pct: 41.2 },
                { device: '/dev/sdb1', mountpoint: '/var', used_pct: 12 },
              ],
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const table = (await screen.findByText('Filesystems')).closest('.agent-telemetry__table');
      const headers = within(table)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent);
      // The unit moves into the cell, beside the digits being compared, which
      // frees the header of it: "used %" over 41.2%, not "used pct".
      expect(headers).toEqual(['device', 'mountpoint', 'used %']);
      // getAllByRole('row') includes the header row.
      expect(within(table).getAllByRole('row')).toHaveLength(3);
      expect(within(table).getByText('/var')).toBeInTheDocument();
      expect(within(table).getByText('41.2%')).toBeInTheDocument();
      // A whole number is still shown to one decimal: a column of 41.2 above
      // 12 does not line up, and these are read down the column.
      expect(within(table).getByText('12.0%')).toBeInTheDocument();
    });

    it('reads every unit off the key the collector chose', async () => {
      // The rows are free-form maps (frame.go: []map[string]any), so the unit
      // can only come from the key's suffix. Raw values are what this tab
      // shipped with: an operator counted digits to tell 674126548964 from
      // 1024731513088.
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              filesystems: [
                {
                  device: '/dev/nvme0n1p3',
                  read_only: false,
                  total_bytes: 1024731513088,
                  available_bytes: 674126548964,
                  used_pct: 64.8697303,
                },
              ],
              interfaces: [{ name: 'eth0', rx_bps: 20973103, speed_mbps: 10000 }],
              temperatures: [{ name: 'hwmon0/temp1', temp_c: 25.3 }],
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const filesystems = (await screen.findByText('Filesystems')).closest(
        '.agent-telemetry__table'
      );
      // Base-1024, because df is what an operator will check this against.
      expect(within(filesystems).getByText('954.4 GB')).toBeInTheDocument();
      expect(within(filesystems).getByText('627.8 GB')).toBeInTheDocument();
      expect(within(filesystems).getByText('64.9%')).toBeInTheDocument();
      // "false" is a word to stop and parse; the column asks a question.
      expect(within(filesystems).getByText('no')).toBeInTheDocument();

      const interfaces = screen.getByText('Interfaces').closest('.agent-telemetry__table');
      // Base-1000 for a link rate, matching the NIC's own quoted speed.
      expect(within(interfaces).getByText('21.0 MB/s')).toBeInTheDocument();
      expect(within(interfaces).getByText('10,000 Mb/s')).toBeInTheDocument();

      const temps = screen.getByText('Temperatures').closest('.agent-telemetry__table');
      expect(within(temps).getByText('25.3 °C')).toBeInTheDocument();
    });

    it('states an absence rather than leaving the cell blank', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              // A sysfs read that found an empty file, and a key the second
              // row simply does not carry.
              temperatures: [
                { name: 'hwmon0/temp1', temp_c: 25.3, warning_c: '' },
                { name: 'hwmon1/temp1', temp_c: 44 },
              ],
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const temps = (await screen.findByText('Temperatures')).closest('.agent-telemetry__table');
      expect(within(temps).getAllByText('—')).toHaveLength(2);
    });

    it('renders nothing for an empty or absent device array', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              // present but empty
              disks: [],
              // absent entirely: filesystems, interfaces, temperatures
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(screen.queryByText('Disks')).not.toBeInTheDocument();
      expect(screen.queryByText('Filesystems')).not.toBeInTheDocument();
      expect(screen.queryByText('Interfaces')).not.toBeInTheDocument();
      expect(screen.queryByText('Temperatures')).not.toBeInTheDocument();
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('renders the interface and temperature tables from their own payload arrays', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          latest: {
            payload: {
              interfaces: [{ name: 'eth0', rx_bps: 1000, tx_bps: 2000 }],
              temperatures: [
                { sensor: 'coretemp', celsius: 48.5 },
                { sensor: 'nvme', celsius: 33 },
              ],
            },
          },
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const interfaces = (await screen.findByText('Interfaces')).closest('.agent-telemetry__table');
      expect(within(interfaces).getAllByRole('row')).toHaveLength(2);
      expect(within(interfaces).getByText('eth0')).toBeInTheDocument();

      const temps = screen.getByText('Temperatures').closest('.agent-telemetry__table');
      expect(
        within(temps)
          .getAllByRole('columnheader')
          .map((cell) => cell.textContent)
      ).toEqual(['sensor', 'celsius']);
      expect(within(temps).getAllByRole('row')).toHaveLength(3);
    });
  });

  describe('readiness', () => {
    it('alerts only on degraded and unavailable collectors', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          readiness: [
            { collector: 'host.core', state: 'ready', reason: null, remediation: null },
            {
              collector: 'host.thermal',
              state: 'degraded',
              reason: 'no thermal zones exposed',
              remediation: 'install lm-sensors',
            },
            {
              collector: 'host.docker',
              state: 'unavailable',
              reason: 'docker socket not readable',
              remediation: 'mount /var/run/docker.sock',
            },
            { collector: 'host.net', state: 'disabled', reason: 'not enabled', remediation: null },
          ],
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const alerts = await findTelemetryBanners();
      expect(alerts).toHaveLength(2);
      expect(alerts[0]).toHaveTextContent('host.thermal: degraded');
      expect(alerts[0]).toHaveTextContent('no thermal zones exposed — install lm-sensors');
      expect(alerts[1]).toHaveTextContent('host.docker: unavailable');
      expect(alerts[1]).toHaveTextContent(
        'docker socket not readable — mount /var/run/docker.sock'
      );
      expect(screen.queryByText(/host\.core/)).not.toBeInTheDocument();
      expect(screen.queryByText(/host\.net/)).not.toBeInTheDocument();
    });

    it('omits the em-dash remediation clause when there is no remediation', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          readiness: [
            {
              collector: 'host.core',
              state: 'degraded',
              reason: 'partial read',
              remediation: null,
            },
          ],
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const [alert] = await findTelemetryBanners();
      // Banner keeps the collector line and the reason in separate elements,
      // so they are asserted separately; what matters is that the em-dash
      // clause is absent when there is nothing to remediate.
      expect(alert).toHaveTextContent('host.core: degraded');
      expect(alert).toHaveTextContent('partial read');
      expect(alert.textContent).not.toContain('—');
    });

    it('renders a partial readiness list — collectors absent entirely — without error', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      // Only one of the host collectors reported; the rest are simply missing,
      // which is the normal shape while a collector has never run.
      getAgentTelemetry.mockResolvedValue({
        data: telemetryFixture({
          readiness: [{ collector: 'host.thermal', state: 'unavailable' }],
        }),
      });

      renderDetail();
      await openTab('Telemetry');

      const [alert] = await findTelemetryBanners();
      expect(alert).toHaveTextContent('host.thermal: unavailable');
      expect(cardValue('CPU')).toBe('12.5%');
    });

    it('renders the section when the response carries no readiness key at all', async () => {
      const { getAgentTelemetry } = await import('../api/agents');
      const fixture = telemetryFixture();
      delete fixture.readiness;
      getAgentTelemetry.mockResolvedValue({ data: fixture });

      renderDetail();
      await openTab('Telemetry');

      await findCards();
      expect(telemetryBanners()).toHaveLength(0);
    });
  });

  // Placed last on purpose: it fails if any test above in this file leaked a
  // mockResolvedValue past beforeEach. vi.clearAllMocks() alone does not
  // restore implementations, which is why beforeEach re-applies each one.
  // Every test in this file reassigns getAgentTelemetry, so that is the one
  // fixture this canary checks.
  it('starts every test from the default api fixtures', async () => {
    const api = await import('../api/agents');
    await expect(api.getAgentTelemetry()).resolves.toEqual(await apiDefaults.getAgentTelemetry());
  });
});
