import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

/**
 * AGT-16: "Revoke, uninstall, scope expansion, remote-probe/discovery grants
 * and update dispatch must require explicit confirmation… naming the exact
 * consequence and the exact target — not a generic 'Are you sure?'."
 *
 * Two properties are asserted for each action, and the second is the one that
 * usually rots: the action must not reach the API before a confirmation, and
 * the confirmation must name *this* machine and *this* outcome. A dialog that
 * says "Are you sure?" satisfies the first and fails the requirement.
 */

const AGENT = {
  id: 3,
  name: null,
  hostname: 'branch-office-01',
  status: 'active',
  fingerprint: 'a'.repeat(32),
  agent_version: '0.8.1',
  capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
};

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
  listAgents: vi.fn(),
  getAgent: vi.fn(),
  getAgentEvents: vi.fn(),
  getAgentProbes: vi.fn(),
  getAgentTelemetry: vi.fn(),
  getAgentTelemetryHistory: vi.fn(),
  getAgentsPresence: vi.fn(),
  getAgentsMetricsSeries: vi.fn(),
  getCapabilityDefaults: vi.fn(),
  setAgentCapabilities: vi.fn(),
  revokeAgent: vi.fn(),
  deleteAgent: vi.fn(),
  triggerAgentUpdate: vi.fn(),
  getInstallCommand: vi.fn(),
  lookupPairingCode: vi.fn(),
  approveAgent: vi.fn(),
  rejectAgent: vi.fn(),
  getAgentDiscovery: () => Promise.resolve({ data: null }),
  pauseAgentDiscovery: () => Promise.resolve({ data: null }),
  resumeAgentDiscovery: () => Promise.resolve({ data: null }),
}));

const mockUseAgentLive = vi.hoisted(() => vi.fn());
vi.mock('../hooks/useAgentLive', () => ({ useAgentLive: mockUseAgentLive }));

const mockTelemetryStream = vi.hoisted(() => ({ data: new Map(), connected: true }));
vi.mock('../hooks/useTelemetryStream', () => ({ useTelemetryStream: () => mockTelemetryStream }));

const mockToast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
}));
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../components/agents/ServerKeyRotationPanel', () => ({ default: () => null }));

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }));

import * as api from '../api/agents';
import AgentDetailPage from '../pages/AgentDetailPage';
import AgentsPage from '../pages/AgentsPage';

const renderDetail = () =>
  render(
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );

const renderFleet = () =>
  render(
    <MemoryRouter initialEntries={['/agents']}>
      <AgentsPage />
    </MemoryRouter>
  );

/** The ConfirmDialog's own affirmative button, distinct from the trigger. */
const confirmButton = () =>
  within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm' });

const dialogText = () => screen.getByRole('dialog').textContent;

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAgentLive.mockReturnValue({ statuses: new Map(), connected: true });
  mockTelemetryStream.data = new Map();

  api.getAgent.mockResolvedValue({ data: { ...AGENT } });
  api.getAgentEvents.mockResolvedValue({ data: [] });
  api.getAgentProbes.mockResolvedValue({
    data: { agent_id: 3, max_concurrent: 20, active_runs: 0, assignments: [] },
  });
  api.getAgentTelemetry.mockResolvedValue({ data: { latest: null, readiness: [] } });
  api.getAgentTelemetryHistory.mockResolvedValue({ data: { points: [] } });
  api.getAgentsPresence.mockResolvedValue({
    data: [{ agent_id: 3, online: true, connected_since: null, last_seen_at: null }],
  });
  api.getAgentsMetricsSeries.mockResolvedValue({ data: [] });
  api.getCapabilityDefaults.mockResolvedValue({
    data: {
      host_telemetry: { enabled: true, config: { interval_s: 45 } },
      remote_probe: { enabled: true, config: {} },
      local_discovery: { enabled: true, config: {} },
    },
  });
  api.setAgentCapabilities.mockResolvedValue({ data: { ...AGENT } });
  api.revokeAgent.mockResolvedValue({ data: {} });
  api.deleteAgent.mockResolvedValue({ data: {} });
  api.triggerAgentUpdate.mockResolvedValue({ data: {} });
  api.getInstallCommand.mockResolvedValue({
    data: { tls_mode: 'self_signed', command: 'curl ...', script_sha256: 'x' },
  });
  api.listAgents.mockResolvedValue({ data: [{ ...AGENT, status: 'revoked' }] });
});

describe('update dispatch', () => {
  it('does not replace the binary on a remote host on one unconfirmed click', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Update' }));
    expect(api.triggerAgentUpdate).not.toHaveBeenCalled();
  });

  it('names the machine and the version it is being moved off', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Update' }));
    const text = dialogText();
    expect(text).toContain('branch-office-01');
    expect(text).toContain('0.8.1');
    // The exact consequence, not a generic warning: it restarts, and it rolls
    // back on failure. Both are things an operator needs before clicking.
    expect(text).toMatch(/restarts itself/);
    expect(text).toMatch(/rolls back/);
    expect(text).not.toMatch(/are you sure/i);
  });

  it('dispatches only after the confirmation, and not at all on cancel', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Update' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(api.triggerAgentUpdate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Update' }));
    fireEvent.click(confirmButton());
    await waitFor(() => expect(api.triggerAgentUpdate).toHaveBeenCalledWith('3'));
  });

  it('reports a refused dispatch as an operator action, not as a raw server detail', async () => {
    api.triggerAgentUpdate.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: 'update in flight for device_pk ' + 'ab'.repeat(32) },
      },
    });
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Update' }));
    fireEvent.click(confirmButton());
    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    const message = mockToast.error.mock.calls.at(-1)[0];
    expect(message).toMatch(/already in flight/i);
    expect(message).not.toContain('ab'.repeat(32));
  });
});

describe('granting a capability that expands what the agent may do', () => {
  // getByLabelText alone is ambiguous for "Host telemetry": the page also has
  // a <section aria-label="Host telemetry">. Narrow to the checkbox itself.
  const toggle = (label) =>
    screen.getAllByLabelText(label).find((element) => element.type === 'checkbox');

  it('confirms before letting an agent probe the network, and says what that means', async () => {
    renderDetail();
    await waitFor(() => expect(toggle('Remote probe')).toBeInTheDocument());
    fireEvent.click(toggle('Remote probe'));

    expect(api.setAgentCapabilities).not.toHaveBeenCalled();
    const text = dialogText();
    expect(text).toContain('branch-office-01');
    expect(text).toMatch(/ICMP, TCP, HTTP\(S\) and DNS/);
    expect(text).toMatch(/derived network scope/);
  });

  it('confirms before letting an agent scan its local subnets', async () => {
    renderDetail();
    await waitFor(() => expect(toggle('Local discovery')).toBeInTheDocument());
    fireEvent.click(toggle('Local discovery'));

    expect(api.setAgentCapabilities).not.toHaveBeenCalled();
    const text = dialogText();
    expect(text).toContain('branch-office-01');
    expect(text).toMatch(/sweep the private subnets/);
    expect(text).toMatch(/review queue/);
  });

  it('grants only after confirmation, and leaves the grant alone on cancel', async () => {
    renderDetail();
    await waitFor(() => expect(toggle('Remote probe')).toBeInTheDocument());

    fireEvent.click(toggle('Remote probe'));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(api.setAgentCapabilities).not.toHaveBeenCalled();
    // The checkbox must fall back to what is actually persisted, not stay
    // showing the grant that was refused.
    expect(toggle('Remote probe')).not.toBeChecked();

    fireEvent.click(toggle('Remote probe'));
    fireEvent.click(confirmButton());
    await waitFor(() =>
      expect(api.setAgentCapabilities).toHaveBeenCalledWith('3', { remote_probe: true })
    );
  });

  it('leaves host telemetry unconfirmed — it expands no network privilege', async () => {
    renderDetail();
    await waitFor(() => expect(toggle('Host telemetry')).toBeInTheDocument());
    fireEvent.click(toggle('Host telemetry')); // granted -> withheld
    await waitFor(() =>
      expect(api.setAgentCapabilities).toHaveBeenCalledWith('3', { host_telemetry: false })
    );
  });
});

describe('revoke', () => {
  it('states what revocation costs, not just that it happens', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }));
    const text = dialogText();
    expect(text).toContain('branch-office-01');
    expect(text).toMatch(/every monitor assigned to it stops running/);
    expect(text).toMatch(/enrolled and approved again/);
    expect(api.revokeAgent).not.toHaveBeenCalled();
  });
});

describe('deleting an agent record from the fleet list', () => {
  it('does not delete on a single click — it shipped without any confirmation', async () => {
    renderFleet();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(api.deleteAgent).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('names the machine, says the record is gone for good, and that the host keeps the software', async () => {
    renderFleet();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    const text = dialogText();
    expect(text).toContain('branch-office-01');
    expect(text).toMatch(/cannot be undone/);
    expect(text).toMatch(/stays installed on the host/);
    expect(text).toMatch(/enroll again as a new pending agent/);
    expect(text).not.toMatch(/are you sure/i);
  });

  it('deletes only on confirm, and cancels cleanly', async () => {
    renderFleet();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(api.deleteAgent).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    fireEvent.click(confirmButton());
    await waitFor(() => expect(api.deleteAgent).toHaveBeenCalledWith(3));
  });
});
