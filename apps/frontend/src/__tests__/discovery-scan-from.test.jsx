import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// Slice 4 Task 28. Cloned from `monitor-run-from.test.jsx:9-52` — same product
// idea one slice later, so the fixture shape, the hoisted-defaults trick and the
// beforeEach restore are deliberately identical. Defaults live in a hoisted
// object so `beforeEach` can *restore* them: `vi.clearAllMocks()` clears call
// records but leaves implementations installed, so a `mockResolvedValue` set by
// one test would otherwise become the fixture for every test after it.
const apiDefaults = vi.hoisted(() => {
  // EligibleDiscoveryAgent, field for field (schemas/discovery.py:313-356).
  const base = {
    agent_id: 7,
    name: 'branch-office',
    // Carried alongside `name`, exactly as the schema does, and deliberately
    // *not* equal to it: `name` winning over `hostname` for a renamed agent has
    // to be observable, not an artefact of the two strings matching.
    hostname: 'agent-7.lan',
    online: true,
    granted: true,
    paused: false,
    readiness: 'ready',
    readiness_collector: 'discovery.tcp',
    scope_version: 'gen-3',
    scope_networks: ['10.0.0.0/24'],
    direct_networks: ['10.0.0.0/24'],
    excluded_networks: [],
    max_addresses_per_job: 1024,
    max_concurrent_hosts: 32,
    tcp_ports: [22, 80, 443],
    active_jobs: 0,
    assigned_profiles: 1,
    in_scope: null,
    eligible: true,
    reason: null,
    detail: null,
  };
  return {
    eligibleAgent: base,
    // `degraded` is a *refusal* for discovery even though remote probing treats
    // it as usable (services/discovery_eligibility.py module docstring).
    degradedAgent: {
      ...base,
      agent_id: 8,
      name: 'closet-pi',
      online: true,
      readiness: 'degraded',
      eligible: false,
      reason: 'readiness_degraded',
      detail: 'discovery.tcp:degraded',
    },
    revokedGrantAgent: {
      ...base,
      agent_id: 9,
      name: 'dmz-probe',
      granted: false,
      eligible: false,
      reason: 'capability_disabled',
      detail: null,
    },
    listEligible: () => Promise.resolve({ data: [base] }),
  };
});

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  info: vi.fn(),
}));

vi.mock('../api/discovery.js', () => ({
  getEligibleDiscoveryAgents: vi.fn(apiDefaults.listEligible),
  createProfile: vi.fn().mockResolvedValue({ data: { id: 1 } }),
  updateProfile: vi.fn().mockResolvedValue({ data: { id: 1 } }),
  startAdHocScan: vi.fn().mockResolvedValue({ data: { id: 55 } }),
  runProfile: vi.fn().mockResolvedValue({ data: { id: 56 } }),
  getDockerNetworks: vi.fn().mockResolvedValue({ data: [] }),
}));

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  networksApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}));

vi.mock('../components/common/Toast', () => ({
  useToast: () => toastSpies,
}));

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {
      nmap_enabled: true,
      scan_ack_accepted: true,
      discovery_mode: 'safe',
      discovery_default_cidr: '',
      discovery_nmap_args: '-sV -O --open -T4',
    },
    reloadSettings: vi.fn(),
  }),
}));

import { getEligibleDiscoveryAgents, createProfile, startAdHocScan } from '../api/discovery.js';
import ScanProfileForm, { CIDR_RE } from '../components/discovery/ScanProfileForm.jsx';
import NewScanPage from '../components/discovery/NewScanPage.jsx';

const { eligibleAgent, degradedAgent, revokedGrantAgent } = apiDefaults;

/** The one 422 body every agent-targeted refusal shares (api/discovery.py:92-95). */
const executionLocation422 = (reason, detail, message) => ({
  statusCode: 422,
  message: '[object Object]',
  response: { status: 422, data: { detail: { reason, detail, message } } },
});

function renderProfileForm(props = {}) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const utils = render(<ScanProfileForm onClose={onClose} onSaved={onSaved} {...props} />);
  return { ...utils, onClose, onSaved };
}

function renderNewScanPage(props = {}) {
  const onStarted = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <NewScanPage
      discoveryCapabilities={{ dockerAvailable: false, netRawCapable: true }}
      profiles={[]}
      onStarted={onStarted}
      onCancel={onCancel}
      {...props}
    />
  );
  return { ...utils, onStarted, onCancel };
}

beforeEach(() => {
  vi.clearAllMocks();
  getEligibleDiscoveryAgents.mockImplementation(apiDefaults.listEligible);
  createProfile.mockResolvedValue({ data: { id: 1 } });
  startAdHocScan.mockResolvedValue({ data: { id: 55 } });
});

describe('ScanProfileForm CIDR validation', () => {
  it('accepts IPv6 ULA prefixes as well as IPv4', () => {
    // fc00::/7 is the only IPv6 range plan §7 lets an agent scope contain, and
    // the agent's own scope is exactly what this field has to be able to hold.
    expect(CIDR_RE.test('fd00::/8')).toBe(true);
    expect(CIDR_RE.test('fd12:3456:789a:1::/64')).toBe(true);
    expect(CIDR_RE.test('fc00::/7')).toBe(true);
    expect(CIDR_RE.test('192.168.1.0/24')).toBe(true);
    // Still not a free pass for every IPv6 prefix: §7 rejects link-local,
    // globally routable and unspecified ranges.
    expect(CIDR_RE.test('fe80::/10')).toBe(false);
    expect(CIDR_RE.test('2001:db8::/32')).toBe(false);
    expect(CIDR_RE.test('::/0')).toBe(false);
    expect(CIDR_RE.test('192.168.1.0')).toBe(false);
  });

  it('does not flag a ULA target as an invalid CIDR on save', async () => {
    renderProfileForm();
    fireEvent.change(screen.getByLabelText('Profile Name'), { target: { value: 'ula lan' } });
    fireEvent.change(screen.getByPlaceholderText('192.168.1.0/24'), {
      target: { value: 'fd00::/8' },
    });
    fireEvent.submit(document.querySelector('form.cb-scan-modal-form'));

    await waitFor(() => expect(createProfile).toHaveBeenCalled());
    expect(screen.queryByText(/Enter a valid CIDR/)).toBeNull();
  });
});

describe('ScanProfileForm "Scan from" execution location', () => {
  it('defaults to the Circuit Breaker server with an empty value', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderProfileForm();
    expect(screen.getByRole('option', { name: 'Circuit Breaker server' })).toBeTruthy();
    // Asserted *after* the fleet has loaded, not before: an eligible agent is
    // sitting in the list and defaulting to it would silently change where an
    // existing profile's scans run.
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());
    expect(screen.getByLabelText('Scan from').value).toBe('');
    expect(screen.getByLabelText('agent_connect').checked).toBe(false);
  });

  it('reads an existing profile execution location back out', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderProfileForm({
      profile: {
        id: 3,
        name: 'branch lan',
        cidr: '10.0.0.0/24',
        scan_agent_id: 7,
        scan_types: ['agent_connect'],
      },
    });
    await waitFor(() => expect(screen.getByLabelText('Scan from').value).toBe('7'));
  });

  it('filters the scan types to agent_connect and disables the server-only ones', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderProfileForm();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    // Before an agent is picked, `agent_connect` is the unavailable one.
    expect(screen.getByLabelText('agent_connect').disabled).toBe(true);
    expect(screen.getByLabelText('nmap').disabled).toBe(false);

    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });

    expect(screen.getByLabelText('agent_connect').disabled).toBe(false);
    expect(screen.getByLabelText('agent_connect').checked).toBe(true);
    for (const serverType of ['nmap', 'arp', 'snmp', 'http', 'docker', 'proxmox', 'deep_dive']) {
      expect(screen.getByLabelText(serverType).disabled).toBe(true);
      expect(screen.getByLabelText(serverType).checked).toBe(false);
    }
  });

  it('labels an un-renamed agent by its hostname rather than "agent 7"', async () => {
    // The fixture above is the *rare* agent. `agents.name` is nullable and
    // enrollment never writes it — `ws_agents.enroll_stream` calls
    // `agent_registry.create_pending_agent` with hostname/os/arch and no name,
    // and the only writer is an explicit operator `PATCH /agents/{id}` — so
    // `name: null` is what most of the fleet looks like, and a selector reading
    // only `name` labels the common case "Agent 7". A fixture that supplies a
    // name cannot see this, which is why it shipped.
    getEligibleDiscoveryAgents.mockResolvedValue({
      data: [{ ...eligibleAgent, name: null, hostname: 'branch-office-01' }],
    });
    renderProfileForm();

    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'branch-office-01 — online · ready' })).toBeTruthy()
    );
    expect(screen.queryByRole('option', { name: /agent 7/i })).toBeNull();
  });

  it('still prefers the name an operator chose over the hostname', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderProfileForm();

    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'branch-office — online · ready' })).toBeTruthy()
    );
    expect(screen.queryByRole('option', { name: /agent-7\.lan/ })).toBeNull();
  });

  it('names an un-renamed agent by hostname in the refusal line too', async () => {
    // The two labels are one shared helper away from drifting: the dropdown
    // could read "branch-office-01" while the reason under it said "Agent 8".
    getEligibleDiscoveryAgents.mockResolvedValue({
      data: [{ ...degradedAgent, name: null, hostname: 'closet-pi-02' }],
    });
    renderProfileForm();

    await waitFor(() =>
      expect(
        screen.getByText(
          /closet-pi-02 cannot scan: the agent reports its TCP connect collector as degraded/
        )
      ).toBeTruthy()
    );
    expect(screen.queryByText(/agent 8 cannot scan/i)).toBeNull();
  });

  it('shows why an ineligible agent cannot be chosen instead of hiding it', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({
      data: [eligibleAgent, degradedAgent, revokedGrantAgent],
    });
    renderProfileForm();

    await waitFor(() =>
      expect(
        screen.getByText(
          /closet-pi cannot scan: the agent reports its TCP connect collector as degraded/
        )
      ).toBeTruthy()
    );
    expect(screen.getByText(/discovery\.tcp:degraded/)).toBeTruthy();
    expect(
      screen.getByText(/dmz-probe cannot scan: local discovery is not enabled for this agent/)
    ).toBeTruthy();
    // Listed, not hidden — and not selectable.
    expect(screen.getByRole('option', { name: /closet-pi/ }).disabled).toBe(true);
    expect(screen.getByRole('option', { name: /branch-office/ }).disabled).toBe(false);
  });

  it('submits scan_agent_id with the profile', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderProfileForm();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Profile Name'), { target: { value: 'branch lan' } });
    fireEvent.change(screen.getByPlaceholderText('192.168.1.0/24'), {
      target: { value: '10.0.0.0/24' },
    });
    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });
    fireEvent.submit(document.querySelector('form.cb-scan-modal-form'));

    await waitFor(() => expect(createProfile).toHaveBeenCalled());
    const payload = createProfile.mock.calls[0][0];
    expect(payload.scan_agent_id).toBe(7);
    expect(payload.scan_types).toEqual(['agent_connect']);
  });

  it('renders the structured 422 message rather than a generic failure', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    createProfile.mockRejectedValue(
      executionLocation422(
        'out_of_scope',
        'not_directly_connected:10.9.0.0/24',
        'agent 7 may not run this discovery request: out_of_scope (not_directly_connected:10.9.0.0/24)'
      )
    );
    renderProfileForm();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Profile Name'), { target: { value: 'bad lan' } });
    fireEvent.change(screen.getByPlaceholderText('192.168.1.0/24'), {
      target: { value: '10.9.0.0/24' },
    });
    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });
    fireEvent.submit(document.querySelector('form.cb-scan-modal-form'));

    await waitFor(() => expect(toastSpies.error).toHaveBeenCalled());
    expect(toastSpies.error).toHaveBeenCalledWith(
      'agent 7 may not run this discovery request: out_of_scope (not_directly_connected:10.9.0.0/24)'
    );
  });
});

describe('NewScanPage "Scan from" execution location', () => {
  it('defaults to the Circuit Breaker server with an empty value', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderNewScanPage();
    expect(screen.getByRole('option', { name: 'Circuit Breaker server' })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());
    expect(screen.getByLabelText('Scan from').value).toBe('');
    // Still the server's own vocabulary, so nothing about an existing ad hoc
    // scan has moved.
    expect(screen.queryByLabelText('AGENT_CONNECT')).toBeNull();
    expect(screen.getByLabelText('SNMP').disabled).toBe(false);
  });

  it('filters the scan types to agent_connect and disables the server-only ones', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderNewScanPage();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });

    expect(screen.getByLabelText('AGENT_CONNECT').checked).toBe(true);
    expect(screen.getByLabelText('AGENT_CONNECT').disabled).toBe(false);
    for (const serverType of ['SNMP', 'HTTP']) {
      expect(screen.getByLabelText(serverType).disabled).toBe(true);
      expect(screen.getByLabelText(serverType).checked).toBe(false);
    }
  });

  it('disables the server-only scan modes while an agent is selected', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderNewScanPage();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });

    for (const mode of ['Full', 'Deep Dive', 'Docker', 'OPNsense']) {
      expect(screen.getByText(mode).closest('button').className).toContain('disabled');
    }
    // Safe is what an agent runs, so it stays selectable.
    expect(screen.getByText('Safe').closest('button').className).not.toContain('disabled');
  });

  it('starts an agent scan with scan_agent_id and the agent scan type', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    const { onStarted } = renderNewScanPage();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('e.g., 192.168.1.0/24'), {
      target: { value: '10.0.0.0/24' },
    });
    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: /Start Scan/ }));

    await waitFor(() => expect(startAdHocScan).toHaveBeenCalled());
    expect(startAdHocScan.mock.calls[0][0]).toEqual({
      cidrs: ['10.0.0.0/24'],
      scan_types: ['agent_connect'],
      scan_agent_id: 7,
    });
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith({ id: 55 }));
  });

  it('shows why an ineligible agent cannot be chosen instead of hiding it', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent, degradedAgent] });
    renderNewScanPage();

    await waitFor(() =>
      expect(
        screen.getByText(
          /closet-pi cannot scan: the agent reports its TCP connect collector as degraded/
        )
      ).toBeTruthy()
    );
    expect(screen.getByRole('option', { name: /closet-pi/ }).disabled).toBe(true);
  });

  it('renders the structured 422 message and keeps the operator on the form', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    startAdHocScan.mockRejectedValue(
      executionLocation422(
        'address_limit_exceeded',
        '4096>1024',
        'agent 7 may not run this discovery request: address_limit_exceeded (4096>1024)'
      )
    );
    const { onStarted } = renderNewScanPage();
    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('e.g., 192.168.1.0/24'), {
      target: { value: '10.0.0.0/20' },
    });
    fireEvent.change(screen.getByLabelText('Scan from'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: /Start Scan/ }));

    await waitFor(() => expect(toastSpies.error).toHaveBeenCalled());
    expect(toastSpies.error).toHaveBeenCalledWith(
      'agent 7 may not run this discovery request: address_limit_exceeded (4096>1024)'
    );
    // The backend definitively refused: nothing started, so the existing
    // "navigate back and refresh, the scan may have started anyway" fallback
    // must not fire.
    expect(onStarted).not.toHaveBeenCalled();
  });

  it('judges each agent against the CIDR the operator has typed', async () => {
    getEligibleDiscoveryAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderNewScanPage();
    await waitFor(() => expect(getEligibleDiscoveryAgents).toHaveBeenCalledWith({}));

    fireEvent.change(screen.getByPlaceholderText('e.g., 192.168.1.0/24'), {
      target: { value: '10.0.0.0/24' },
    });
    await waitFor(() =>
      expect(getEligibleDiscoveryAgents).toHaveBeenCalledWith({ cidr: '10.0.0.0/24' })
    );
  });
});
