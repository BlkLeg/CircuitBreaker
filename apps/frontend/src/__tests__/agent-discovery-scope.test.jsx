import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';

// Slice 4 Task 27, cloned from agent-assigned-probes.test.jsx. Same discipline:
// every default implementation lives in this hoisted object and is re-applied in
// beforeEach, because vi.clearAllMocks() clears call records but leaves
// implementations installed — a mockResolvedValue set by one test would
// otherwise become the fixture for every test after it.
const apiDefaults = vi.hoisted(() => {
  // The registry's `local_discovery` defaults, byte-identical to
  // `_LOCAL_DISCOVERY_DEFAULT_CONFIG` in services/agent_capabilities.py.
  const discoveryDefaults = {
    scope_mode: 'direct_private',
    excluded_cidrs: [],
    additional_cidrs: [],
    max_addresses_per_job: 1024,
    max_concurrent_hosts: 64,
    tcp_ports: [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
    host_timeout_ms: 1500,
    job_timeout_seconds: 300,
    auto_discovery_paused: false,
  };
  const discoveryConfig = {
    ...discoveryDefaults,
    excluded_cidrs: ['10.30.40.128/25', '10.30.41.0/24'],
    additional_cidrs: ['10.31.0.0/24', '100.64.0.0/10'],
  };
  const agent = {
    id: 3,
    name: 'branch-office',
    hostname: 'box1',
    status: 'active',
    fingerprint: 'a'.repeat(32),
    agent_version: '0.1.0',
    capabilities: {
      host_telemetry: false,
      remote_probe: false,
      local_discovery: { enabled: true, config: discoveryConfig },
    },
  };
  const job = (over) => ({
    id: 0,
    profile_id: 77,
    scan_agent_id: 3,
    source_type: 'agent',
    label: null,
    target_cidr: '10.30.40.0/24',
    vlan_ids: [],
    network_ids: [],
    scan_types_json: '["agent_connect"]',
    status: 'completed',
    started_at: '2026-08-08T09:00:00Z',
    completed_at: '2026-08-08T09:02:00Z',
    hosts_found: 0,
    hosts_new: 0,
    hosts_updated: 0,
    hosts_conflict: 0,
    error_text: null,
    error_reason: null,
    triggered_by: 'scheduler',
    progress_phase: null,
    progress_message: null,
    created_at: '2026-08-08T09:00:00Z',
    ...over,
  });
  const running = job({
    id: 501,
    status: 'running',
    completed_at: null,
    progress_phase: 'sweep',
    progress_message: '12 of 254 hosts',
    hosts_found: 2,
  });
  const discovery = {
    agent_id: 3,
    online: true,
    granted: true,
    paused: false,
    globally_paused: false,
    eligible: true,
    reason: null,
    detail: null,
    scope_version: 'sha256:9f1c',
    // Provenance is the point of this fixture. Two directly connected subnets,
    // one of them centrally excluded; a directly connected /8 that is private
    // (so the backend derives it) but that no bounded job can ever cover; an
    // administrator's routed override; a tunnel/CGNAT override; and an
    // exclusion narrower than any allow-list network.
    scope: [
      { cidr: '10.30.40.0/24', provenance: 'automatic', effective: true, reason: 'in_scope' },
      { cidr: '10.30.41.0/24', provenance: 'automatic', effective: false, reason: 'excluded_cidr' },
      { cidr: '10.0.0.0/8', provenance: 'automatic', effective: false, reason: 'prefix_too_wide' },
      { cidr: '10.31.0.0/24', provenance: 'override', effective: true, reason: 'in_scope' },
      {
        cidr: '100.64.0.0/10',
        provenance: 'override',
        effective: false,
        reason: 'prefix_too_wide',
      },
      {
        cidr: '10.30.40.128/25',
        provenance: 'excluded',
        effective: false,
        reason: 'excluded_cidr',
      },
    ],
    limits: {
      scope_mode: 'direct_private',
      max_addresses_per_job: 1024,
      max_concurrent_hosts: 64,
      host_timeout_ms: 1500,
      job_timeout_seconds: 300,
      tcp_ports: [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
    },
    readiness: [
      {
        collector: 'discovery.neighbor',
        state: null,
        reason: null,
        remediation: null,
        updated_at: null,
        stale: false,
        required: false,
      },
      {
        collector: 'discovery.icmp',
        state: 'degraded',
        reason: 'no datagram socket',
        remediation: 'widen net.ipv4.ping_group_range',
        updated_at: '2026-08-08T09:00:00Z',
        stale: false,
        required: false,
      },
      {
        collector: 'discovery.tcp',
        state: 'ready',
        reason: null,
        remediation: null,
        updated_at: '2026-08-08T09:00:00Z',
        stale: false,
        required: true,
      },
      {
        collector: 'discovery.dns',
        state: 'ready',
        reason: null,
        remediation: null,
        updated_at: '2026-08-08T09:00:00Z',
        stale: false,
        required: false,
      },
    ],
    active_jobs: [running],
    recent_jobs: [
      running,
      job({ id: 499, hosts_found: 7 }),
      job({ id: 498, status: 'failed', hosts_found: 1, error_reason: 'partial_findings' }),
    ],
    profiles: [
      {
        id: 77,
        name: 'branch-office 10.30.40.0/24',
        cidr: '10.30.40.0/24',
        scan_agent_id: 3,
        managed_by: 'system',
        paused_at: null,
        vlan_ids: [],
        scan_types: ['agent_connect'],
        nmap_arguments: null,
        snmp_version: '2c',
        snmp_port: 161,
        docker_network_types: [],
        docker_port_scan: false,
        docker_socket_path: '',
        schedule_cron: '3 */6 * * *',
        enabled: true,
        last_run: '2026-08-08T09:02:00Z',
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-08T09:02:00Z',
      },
    ],
  };
  return {
    agent,
    discovery,
    discoveryDefaults,
    discoveryConfig,
    getAgent: () => Promise.resolve({ data: structuredClone(agent) }),
    getAgentEvents: () => Promise.resolve({ data: [] }),
    getAgentProbes: () =>
      Promise.resolve({
        data: { agent_id: 3, max_concurrent: 20, active_runs: 0, assignments: [] },
      }),
    getAgentDiscovery: () => Promise.resolve({ data: structuredClone(discovery) }),
    pauseAgentDiscovery: () =>
      Promise.resolve({ data: { ...structuredClone(discovery), paused: true } }),
    resumeAgentDiscovery: () => Promise.resolve({ data: structuredClone(discovery) }),
    getAgentTelemetry: () => Promise.resolve({ data: { latest: null, readiness: [] } }),
    getAgentTelemetryHistory: () => Promise.resolve({ data: { points: [] } }),
    getAgentsPresence: () =>
      Promise.resolve({
        data: [{ agent_id: 3, online: true, connected_since: null, hardware: null }],
      }),
    getCapabilityDefaults: () =>
      Promise.resolve({
        data: {
          host_telemetry: { enabled: true, config: { interval_s: 45 } },
          remote_probe: { enabled: true, config: { max_concurrent: 20 } },
          local_discovery: { enabled: true, config: structuredClone(discoveryDefaults) },
        },
      }),
    setAgentCapabilities: () => Promise.resolve({ data: structuredClone(agent) }),
    revokeAgent: () => Promise.resolve({ data: {} }),
    triggerAgentUpdate: () => Promise.resolve({ data: {} }),
    listProbeEligibleAgents: () => Promise.resolve({ data: [] }),
    updateProfile: () => Promise.resolve({ data: {} }),
    // Both hold endpoints answer with the `DiscoveryProfileOut` they changed —
    // `paused_at` is "held since", and nothing else about the profile moves.
    pauseProfile: () =>
      Promise.resolve({
        data: { ...structuredClone(discovery.profiles[0]), paused_at: '2026-08-09T10:00:00Z' },
      }),
    resumeProfile: () => Promise.resolve({ data: structuredClone(discovery.profiles[0]) }),
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
  getAgentDiscovery: vi.fn(apiDefaults.getAgentDiscovery),
  pauseAgentDiscovery: vi.fn(apiDefaults.pauseAgentDiscovery),
  resumeAgentDiscovery: vi.fn(apiDefaults.resumeAgentDiscovery),
  getAgentTelemetry: vi.fn(apiDefaults.getAgentTelemetry),
  getAgentTelemetryHistory: vi.fn(apiDefaults.getAgentTelemetryHistory),
  getAgentsPresence: vi.fn(apiDefaults.getAgentsPresence),
  getCapabilityDefaults: vi.fn(apiDefaults.getCapabilityDefaults),
  setAgentCapabilities: vi.fn(apiDefaults.setAgentCapabilities),
  revokeAgent: vi.fn(apiDefaults.revokeAgent),
  triggerAgentUpdate: vi.fn(apiDefaults.triggerAgentUpdate),
  listProbeEligibleAgents: vi.fn(apiDefaults.listProbeEligibleAgents),
}));

vi.mock('../api/discovery', () => ({
  updateProfile: vi.fn(apiDefaults.updateProfile),
  pauseProfile: vi.fn(apiDefaults.pauseProfile),
  resumeProfile: vi.fn(apiDefaults.resumeProfile),
}));

vi.mock('../api/monitor', () => ({
  runCheck: vi.fn(() => Promise.resolve({ data: {} })),
  updateMonitor: vi.fn(() => Promise.resolve({ data: {} })),
}));

const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

const mockTelemetryStream = vi.hoisted(() => ({ data: new Map(), connected: true }));
vi.mock('../hooks/useTelemetryStream', () => ({
  useTelemetryStream: () => mockTelemetryStream,
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

// The section renders as soon as the page has an agent, so every query below
// would race the two requests that fill it. Waiting on one element from each —
// the readiness table (GET /agents/{id}/discovery) and the config editor
// (GET /agents/capability-defaults) — is what makes the rest synchronous.
async function scopeSection() {
  const section = await screen.findByRole('region', { name: 'Discovery scope' });
  await within(section).findByRole('table', { name: 'Collector readiness' });
  await within(section).findByRole('group', { name: 'Local discovery settings' });
  return section;
}

// The persisted config with `patch` applied — the exact body the page sends,
// assembled the way the capability endpoint's merge does it.
const savedConfig = (patch) => ({
  local_discovery: {
    enabled: true,
    config: { ...apiDefaults.discoveryConfig, ...patch },
  },
});

describe('Agent Detail — discovery scope', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const api = await import('../api/agents');
    api.getAgent.mockImplementation(apiDefaults.getAgent);
    api.getAgentEvents.mockImplementation(apiDefaults.getAgentEvents);
    api.getAgentProbes.mockImplementation(apiDefaults.getAgentProbes);
    api.getAgentDiscovery.mockImplementation(apiDefaults.getAgentDiscovery);
    api.pauseAgentDiscovery.mockImplementation(apiDefaults.pauseAgentDiscovery);
    api.resumeAgentDiscovery.mockImplementation(apiDefaults.resumeAgentDiscovery);
    api.getAgentTelemetry.mockImplementation(apiDefaults.getAgentTelemetry);
    api.getAgentTelemetryHistory.mockImplementation(apiDefaults.getAgentTelemetryHistory);
    api.getAgentsPresence.mockImplementation(apiDefaults.getAgentsPresence);
    api.getCapabilityDefaults.mockImplementation(apiDefaults.getCapabilityDefaults);
    api.setAgentCapabilities.mockImplementation(apiDefaults.setAgentCapabilities);
    api.revokeAgent.mockImplementation(apiDefaults.revokeAgent);
    api.triggerAgentUpdate.mockImplementation(apiDefaults.triggerAgentUpdate);
    api.listProbeEligibleAgents.mockImplementation(apiDefaults.listProbeEligibleAgents);
    const discoveryApi = await import('../api/discovery');
    discoveryApi.updateProfile.mockImplementation(apiDefaults.updateProfile);
    discoveryApi.pauseProfile.mockImplementation(apiDefaults.pauseProfile);
    discoveryApi.resumeProfile.mockImplementation(apiDefaults.resumeProfile);
    mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
    mockTelemetryStream.data = new Map();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders automatic subnets, central exclusions and routed overrides with different provenance', async () => {
    renderDetail();
    const section = await scopeSection();

    const automatic = within(section).getByRole('table', { name: 'Automatically included' });
    const auto = within(automatic).getByRole('row', { name: /10\.30\.40\.0\/24/ });
    expect(within(auto).getByText('Directly connected')).toBeInTheDocument();

    const overrides = within(section).getByRole('table', { name: 'Routed overrides' });
    const override = within(overrides).getByRole('row', { name: /10\.31\.0\.0\/24/ });
    expect(within(override).getByText('Added centrally')).toBeInTheDocument();

    const exclusions = within(section).getByRole('table', { name: 'Central exclusions' });
    const excluded = within(exclusions).getByRole('row', { name: /10\.30\.40\.128\/25/ });
    expect(within(excluded).getByText('Removed centrally')).toBeInTheDocument();

    // The three provenance labels are distinct strings, not one shared word:
    // "the agent is attached to this" and "an administrator added this" are
    // different facts with different controls.
    expect(within(automatic).queryByText('Added centrally')).toBeNull();
    expect(within(overrides).queryByText('Directly connected')).toBeNull();
  });

  it('never shows a tunnel, default-route or over-wide candidate as automatically included', async () => {
    renderDetail();
    const section = await scopeSection();

    const automatic = within(section).getByRole('table', { name: 'Automatically included' });
    // A directly connected 10.0.0.0/8 is private, so the backend derives it and
    // marks it `automatic` — but no bounded job can cover a /8, and rendering it
    // as included would tell an operator the agent is sweeping 16 million
    // addresses it will in fact refuse.
    expect(within(automatic).queryByRole('row', { name: /10\.0\.0\.0\/8/ })).toBeNull();
    // CGNAT/tunnel space arrives as an administrator's override, never as a
    // directly connected subnet.
    expect(within(automatic).queryByRole('row', { name: /100\.64\.0\.0\/10/ })).toBeNull();

    const ineligible = within(section).getByRole('table', { name: 'Reported, not eligible' });
    const wide = within(ineligible).getByRole('row', { name: /10\.0\.0\.0\/8/ });
    expect(within(wide).getByText(/wider than \/16/)).toBeInTheDocument();
  });

  it('separates the allow list from what the evaluator will actually permit', async () => {
    renderDetail();
    const section = await scopeSection();

    const effective = within(section).getByText(/^Effectively scanned:/);
    expect(effective).toHaveTextContent('10.30.40.0/24');
    expect(effective).toHaveTextContent('10.31.0.0/24');
    // Both of these are in the allow list and neither is scanned.
    expect(effective).not.toHaveTextContent('10.30.41.0/24');
    expect(effective).not.toHaveTextContent('10.0.0.0/8');

    const refused = within(section).getByText(/^In the allow list but refused:/);
    expect(refused).toHaveTextContent('10.30.41.0/24 (excluded cidr)');
    expect(refused).toHaveTextContent('10.0.0.0/8 (prefix too wide)');
  });

  it('warns about a degraded collector and renders every readiness row', async () => {
    renderDetail();
    const section = await scopeSection();

    const warning = within(section).getByRole('alert');
    expect(warning).toHaveTextContent('discovery.icmp: degraded');
    expect(warning).toHaveTextContent('no datagram socket');
    expect(warning).toHaveTextContent('widen net.ipv4.ping_group_range');

    const readiness = within(section).getByRole('table', { name: 'Collector readiness' });
    expect(
      within(readiness).getByRole('row', { name: /discovery\.tcp.*ready.*Required/ })
    ).toBeInTheDocument();
    // A collector that has never reported is rendered, not omitted: "not
    // installed" is what makes a job refuse with readiness_unknown.
    expect(
      within(readiness).getByRole('row', { name: /discovery\.neighbor.*Never reported/ })
    ).toBeInTheDocument();
  });

  it('renders the active job and the job history, and links the agent name into discovery history', async () => {
    renderDetail();
    const section = await scopeSection();

    const active = within(section).getByText(/Running · 10\.30\.40\.0\/24/);
    expect(active).toHaveTextContent('sweep');
    expect(active).toHaveTextContent('12 of 254 hosts');

    const history = within(section).getByRole('table', { name: 'Recent discovery jobs' });
    expect(within(history).getByRole('row', { name: /499.*completed.*7/ })).toBeInTheDocument();
    expect(
      within(history).getByRole('row', { name: /498.*failed.*partial findings/ })
    ).toBeInTheDocument();

    expect(within(section).getByRole('link', { name: 'branch-office' })).toHaveAttribute(
      'href',
      '/discovery?agent=3'
    );
  });

  it('persists the pause toggle, the per-subnet cadence and the scan depth', async () => {
    const { pauseAgentDiscovery } = await import('../api/agents');
    const { setAgentCapabilities } = await import('../api/agents');
    const { updateProfile } = await import('../api/discovery');
    renderDetail();
    const section = await scopeSection();

    const pause = within(section).getByLabelText('Pause automatic discovery');
    expect(pause).not.toBeChecked();
    fireEvent.click(pause);
    await waitFor(() => expect(pauseAgentDiscovery).toHaveBeenCalledWith('3'));
    await waitFor(() => expect(pause).toBeChecked());

    const cadence = within(section).getByLabelText('Cadence for branch-office 10.30.40.0/24');
    expect(cadence).toHaveValue('3 */6 * * *');
    fireEvent.change(cadence, { target: { value: '9 */2 * * *' } });
    fireEvent.blur(cadence);
    await waitFor(() =>
      expect(updateProfile).toHaveBeenCalledWith(77, { schedule_cron: '9 */2 * * *' })
    );

    const depth = within(section).getByRole('textbox', { name: /Scan depth/ });
    fireEvent.change(depth, { target: { value: '22, 443' } });
    fireEvent.blur(depth);
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith('3', savedConfig({ tcp_ports: [22, 443] }))
    );
  });

  it('persists excluding an automatic subnet and adding a routed CIDR', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();
    const section = await scopeSection();

    const automatic = within(section).getByRole('table', { name: 'Automatically included' });
    const row = within(automatic).getByRole('row', { name: /10\.30\.40\.0\/24/ });
    fireEvent.click(within(row).getByRole('button', { name: 'Exclude' }));
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith(
        '3',
        savedConfig({ excluded_cidrs: ['10.30.40.128/25', '10.30.41.0/24', '10.30.40.0/24'] })
      )
    );

    const routed = within(section).getByRole('textbox', { name: /Routed overrides/ });
    fireEvent.change(routed, { target: { value: '10.31.0.0/24, 100.64.0.0/10, 192.168.50.0/24' } });
    fireEvent.blur(routed);
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith(
        '3',
        savedConfig({
          additional_cidrs: ['10.31.0.0/24', '100.64.0.0/10', '192.168.50.0/24'],
        })
      )
    );
  });

  it('confirms a scope wider than the hard-safe range, and refuses a default route outright', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();
    const section = await scopeSection();
    const routed = within(section).getByRole('textbox', { name: /Routed overrides/ });

    fireEvent.change(routed, { target: { value: '10.31.0.0/24, 100.64.0.0/10, 172.16.0.0/12' } });
    fireEvent.blur(routed);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('172.16.0.0/12');
    expect(dialog).toHaveTextContent(/wider than \/16/);
    // Nothing is written until the user confirms.
    expect(setAgentCapabilities).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith(
        '3',
        savedConfig({ additional_cidrs: ['10.31.0.0/24', '100.64.0.0/10', '172.16.0.0/12'] })
      )
    );

    // A /17 is inside the hard prefix ceiling but is 32768 addresses against a
    // 1024-address per-job ceiling: every scan of it refuses with
    // address_limit_exceeded, so it is confirmation-worthy too.
    fireEvent.change(routed, { target: { value: '10.31.0.0/24, 100.64.0.0/10, 10.40.0.0/17' } });
    fireEvent.blur(routed);
    const second = await screen.findByRole('dialog');
    expect(second).toHaveTextContent(/32768 addresses/);
    expect(second).toHaveTextContent(/1024/);
    fireEvent.click(within(second).getByRole('button', { name: 'Cancel' }));
    expect(setAgentCapabilities).toHaveBeenCalledTimes(1);
  });

  it('rejects a default route before it reaches the API', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();
    const section = await scopeSection();

    const routed = within(section).getByRole('textbox', { name: /Routed overrides/ });
    fireEvent.change(routed, { target: { value: '10.31.0.0/24, 100.64.0.0/10, 0.0.0.0/0' } });
    fireEvent.blur(routed);

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        '0.0.0.0/0 covers the whole address space and is not a scope'
      )
    );
    expect(setAgentCapabilities).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('refuses a bound-breaking number locally instead of round-tripping a 422', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();
    const section = await scopeSection();

    const addresses = () => within(section).getByRole('spinbutton', { name: /Addresses per job/ });
    expect(addresses()).toHaveValue(1024);

    // Clearing a number input reads back as Number('') === 0. Unguarded that is
    // what got sent to PUT /agents/{id}/capabilities, 422'd, toasted and
    // remounted the editor — a round trip to learn a bound this page already
    // holds. The message and the numbers are the registry's own.
    fireEvent.change(addresses(), { target: { value: '' } });
    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith('Addresses per job must be between 1 and 4096')
    );
    expect(setAgentCapabilities).not.toHaveBeenCalled();
    // …and the editor is left showing what is really stored, not the refusal.
    expect(addresses()).toHaveValue(1024);

    const hostTimeout = () => within(section).getByRole('spinbutton', { name: /Host timeout/ });
    fireEvent.change(hostTimeout(), { target: { value: '20000' } });
    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        'Host timeout (ms) must be between 100 and 10000'
      )
    );
    expect(setAgentCapabilities).not.toHaveBeenCalled();

    // The guard refuses only what the endpoint would: an in-range edit still
    // saves, without a confirmation.
    fireEvent.change(within(section).getByRole('spinbutton', { name: /Concurrent hosts/ }), {
      target: { value: '32' },
    });
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith(
        '3',
        savedConfig({ max_concurrent_hosts: 32 })
      )
    );
  });

  it('pauses and resumes one subnet from the row that shows its state', async () => {
    const { pauseProfile, resumeProfile } = await import('../api/discovery');
    renderDetail();
    const section = await scopeSection();

    const subnets = within(section).getByRole('table', { name: 'Discovery subnets' });
    const row = () => within(subnets).getByRole('row', { name: /10\.30\.40\.0\/24/ });
    expect(within(row()).getByText('Scheduled')).toBeInTheDocument();

    fireEvent.click(within(row()).getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(pauseProfile).toHaveBeenCalledWith(77));
    // `paused_at` is "held since", so the row says since when.
    await waitFor(() => expect(within(row()).getByText(/^Paused since /)).toBeInTheDocument());

    fireEvent.click(within(row()).getByRole('button', { name: 'Resume' }));
    await waitFor(() => expect(resumeProfile).toHaveBeenCalledWith(77));
    await waitFor(() => expect(within(row()).getByText('Scheduled')).toBeInTheDocument());

    // A hold is not a delete and not a stop: it withholds future scheduling
    // only, which is also what makes it a different state from Disabled.
    const hint = within(section).getByText(/withholds its future scheduled scans/);
    expect(hint).toHaveTextContent('Nothing is deleted');
    expect(hint).toHaveTextContent('a scan already queued or running is not stopped');
    expect(hint).toHaveTextContent(/different state from Disabled/);
  });

  it('disabling local discovery explains that active work is cancelled and history retained', async () => {
    const { setAgentCapabilities } = await import('../api/agents');
    renderDetail();
    await scopeSection();

    fireEvent.click(await screen.findByLabelText('Local discovery'));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(/cancelled/);
    expect(dialog).toHaveTextContent(/results and job history are retained/);
    expect(setAgentCapabilities).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(setAgentCapabilities).toHaveBeenCalledWith('3', { local_discovery: false })
    );
  });
});
