import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Slice 3 §7 (plans/2026-08-04-cbi-agent-slice3-remote-probe.md:414):
//
//   Offer "Create monitor from this agent" actions for devices found in Slice
//   4. These preselect the agent vantage and target while leaving monitor
//   type, interval, and alert policy under user control.
//
// It sits in that plan's "Agent UI" subsection, which is entirely about Agent
// Detail — so the action hangs off the agent's own discovery section, and
// Slice 4's review queue stays "preserved unchanged"
// (plans/2026-08-04-cbi-agent-slice4-local-discovery.md:339).
//
// Cloned from monitor-run-from.test.jsx, whose fixture shape this reuses.
const apiDefaults = vi.hoisted(() => {
  const base = {
    agent_id: 7,
    name: 'branch-office',
    online: true,
    granted: true,
    readiness: 'ready',
    readiness_collector: 'probe.icmp',
    max_concurrent: 20,
    active_runs: 0,
    assigned_monitors: 2,
    scope_version: 'gen-3',
    scope_networks: ['10.77.0.0/24'],
    excluded_networks: [],
    in_scope: true,
    eligible: true,
    reason: null,
  };
  return { eligibleAgent: base };
});

vi.mock('../api/agents', () => ({
  listProbeEligibleAgents: vi.fn(() => Promise.resolve({ data: [apiDefaults.eligibleAgent] })),
  pauseAgentDiscovery: vi.fn(),
  resumeAgentDiscovery: vi.fn(),
  setAgentCapabilities: vi.fn(),
}));

vi.mock('../api/discovery', () => ({
  getAgentDiscoveredDevices: vi.fn(),
  pauseProfile: vi.fn(),
  resumeProfile: vi.fn(),
  updateProfile: vi.fn(),
}));

import { listProbeEligibleAgents } from '../api/agents';
import { getAgentDiscoveredDevices } from '../api/discovery';
import MonitorForm from '../components/monitors/MonitorForm.jsx';
import DiscoveryScopeSection from '../components/agents/DiscoveryScopeSection.jsx';
import { ToastProvider } from '../components/common/Toast';

// One accepted device (merged into Hardware 55) and one still in review.
const acceptedDevice = {
  id: 1,
  ip_address: '10.77.0.11',
  hostname: 'branch-nas',
  merge_status: 'merged',
  matched_entity_type: 'hardware',
  matched_entity_id: 55,
  discovery_agent_id: 7,
};
const pendingDevice = {
  id: 2,
  ip_address: '10.77.0.12',
  hostname: null,
  merge_status: 'pending',
  matched_entity_type: null,
  matched_entity_id: null,
  discovery_agent_id: 7,
};

const discovery = {
  agent_id: 7,
  online: true,
  granted: true,
  paused: false,
  globally_paused: false,
  eligible: true,
  reason: null,
  scope_version: 'gen-3',
  scope: [{ cidr: '10.77.0.0/24', provenance: 'automatic' }],
  limits: { max_addresses_per_job: 1024 },
  readiness: [],
  active_jobs: [],
  recent_jobs: [],
  profiles: [],
};

function renderSection() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <DiscoveryScopeSection
          agentId="7"
          agentName="branch-office"
          discovery={discovery}
          granted
          config={{}}
          defaults={{}}
          onDiscovery={vi.fn()}
          onChanged={vi.fn()}
        />
      </ToastProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listProbeEligibleAgents.mockImplementation(() =>
    Promise.resolve({ data: [apiDefaults.eligibleAgent] })
  );
  getAgentDiscoveredDevices.mockResolvedValue({ data: [acceptedDevice, pendingDevice] });
});

describe('Create monitor from this agent — the action on Agent Detail', () => {
  it('asks only for the devices this agent itself found', async () => {
    renderSection();

    await waitFor(() => expect(getAgentDiscoveredDevices).toHaveBeenCalled());
    // The agent id, not a global feed: a device another agent (or the server)
    // found is not "found by this agent".
    expect(getAgentDiscoveredDevices).toHaveBeenCalledWith('7', expect.anything());
  });

  it('links an accepted device to a prefilled monitor with this agent as the vantage', async () => {
    renderSection();

    const link = await screen.findByRole('link', { name: 'Create monitor' });
    const href = link.getAttribute('href');
    const query = new URLSearchParams(href.split('?')[1]);

    expect(href.startsWith('/monitors?')).toBe(true);
    expect(query.get('new')).toBe('1');
    // The vantage — the whole point of the action.
    expect(query.get('probe_agent_id')).toBe('7');
    // The target: an inventory row, not a raw address, so the monitor joins
    // the same target machinery every other monitor uses.
    expect(query.get('target_type')).toBe('hardware');
    expect(query.get('target_id')).toBe('55');
    expect(query.get('host')).toBe('10.77.0.11');
    // Type, interval and alert policy are deliberately absent — they stay
    // under the operator's control per §7.
    expect(query.get('check_type')).toBeNull();
    expect(query.get('interval_secs')).toBeNull();
  });

  it('offers no monitor action for a device still awaiting review', async () => {
    getAgentDiscoveredDevices.mockResolvedValue({ data: [pendingDevice] });

    renderSection();

    expect(await screen.findByText('Accept it first')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create monitor' })).toBeNull();
  });
});

describe('MonitorForm prefill', () => {
  it('opens a CREATE seeded with the device and the agent vantage', async () => {
    render(
      <MonitorForm
        initial={null}
        prefill={{
          name: 'branch-nas',
          host: '10.77.0.11',
          target_type: 'hardware',
          target_id: 55,
          probe_agent_id: 7,
        }}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />
    );

    // Still a create, not an edit — the check type must remain changeable.
    expect(screen.getByText('Add monitor')).toBeInTheDocument();
    expect(screen.getByDisplayValue('10.77.0.11')).toBeInTheDocument();

    // RunFromSelect compares its value with === against a numeric agent_id, so
    // a string here would leave the select looking right while the eligibility
    // warnings silently stopped matching.
    await waitFor(() => expect(listProbeEligibleAgents).toHaveBeenCalled());
    const select = await screen.findByLabelText('Run from');
    await waitFor(() => expect(select.value).toBe('7'));
  });

  it('submits the prefilled vantage and target through to the API payload', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <MonitorForm
        initial={null}
        prefill={{
          name: 'branch-nas',
          host: '10.77.0.11',
          target_type: 'hardware',
          target_id: 55,
          probe_agent_id: 7,
        }}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />
    );

    fireEvent.submit(container.querySelector('form.entity-form'));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      host: '10.77.0.11',
      target_type: 'hardware',
      target_id: 55,
      probe_agent_id: 7,
    });
  });
});
