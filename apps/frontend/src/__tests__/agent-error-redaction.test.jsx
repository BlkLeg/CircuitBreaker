import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

/**
 * AGT-15 at the surfaces themselves: "SECURITY-CRITICAL: audit every error
 * surface for leaked enrollment keys, pairing codes, tokens or wire-protocol
 * detail."
 *
 * lib/agentErrors is unit-tested in agent-errors.test.js. This file asserts the
 * surfaces actually route through it — which is the half that regresses, since
 * `error?.response?.data?.detail ?? 'something failed'` is the shortest thing
 * to write and reads as harmless.
 */

const DEVICE_PK = 'a3f1'.repeat(16); // 64 hex — an X25519 public key
const PAIRING_CODE = '7QK2-4M1X-9ZTP';

const AGENT = {
  id: 3,
  name: null,
  hostname: 'box1',
  status: 'active',
  fingerprint: 'a'.repeat(32),
  agent_version: '0.9.0',
  capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
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
  setAgentCapabilities: vi.fn(),
  revokeAgent: vi.fn(),
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

import * as api from '../api/agents';
import AgentDetailPage from '../pages/AgentDetailPage';
import AddAgentPanel from '../components/agents/AddAgentPanel';
import AddAgentPairingCode from '../components/agents/AddAgentPairingCode';

const renderDetail = () =>
  render(
    <MemoryRouter initialEntries={['/agents/3']}>
      <Routes>
        <Route path="/agents/:id" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>
  );

/** Everything the operator could have seen: the DOM plus every toast raised. */
const everythingShown = () =>
  [
    document.body.textContent,
    ...mockToast.error.mock.calls.flat(),
    ...mockToast.success.mock.calls.flat(),
  ].join('\n');

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
  api.getAgentsPresence.mockResolvedValue({ data: [{ agent_id: 3, online: true }] });
  api.getCapabilityDefaults.mockResolvedValue({
    data: { host_telemetry: { enabled: true, config: { interval_s: 45 } } },
  });
  api.setAgentCapabilities.mockResolvedValue({ data: { ...AGENT } });
});

describe('the install step', () => {
  it('does not print key material a 503 detail happened to carry', async () => {
    api.getInstallCommand.mockRejectedValue({
      response: {
        status: 503,
        data: { detail: `no pin for ${DEVICE_PK}; run chmod 644 /data/tls/fullchain.pem` },
      },
    });
    render(<AddAgentPanel isStandalone pendingAgents={[]} />);

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    const shown = everythingShown();
    expect(shown).not.toContain(DEVICE_PK);
    // …while keeping the half that makes the failure fixable.
    expect(shown).toContain('chmod 644');
  });
});

describe('the pairing-code form', () => {
  it('never echoes the code that was typed', async () => {
    api.lookupPairingCode.mockRejectedValue({ response: { status: 404 } });
    render(<AddAgentPairingCode onResolved={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Or paste a pairing code:'), {
      target: { value: PAIRING_CODE },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    // A code in a toast is a code in a screenshot, and in a shared bug report.
    expect(mockToast.error.mock.calls.flat().join('\n')).not.toContain(PAIRING_CODE);
  });
});

describe('the event timeline', () => {
  it('shows a protocol violation as an audit row without its wire detail', async () => {
    api.getAgentEvents.mockResolvedValue({
      data: [
        {
          id: 9,
          event_type: 'protocol_violation',
          created_at: '2026-08-26T10:00:00Z',
          detail: {
            reason: 'sequence_regression',
            seq: 41,
            last_seq: 92,
            frame_type: 'telemetry.host',
            device_pk: DEVICE_PK,
          },
        },
      ],
    });
    renderDetail();
    fireEvent.click(await screen.findByRole('tab', { name: 'Events' }));

    await waitFor(() => expect(screen.getByText('Protocol violation')).toBeInTheDocument());
    const shown = everythingShown();
    expect(shown).not.toContain(DEVICE_PK);
    expect(shown).not.toContain('telemetry.host');
    expect(shown).not.toContain('last_seq');
  });

  it('shows an update failure’s version but not an agent-authored error blob', async () => {
    api.getAgentEvents.mockResolvedValue({
      data: [
        {
          id: 10,
          event_type: 'update_failed',
          created_at: '2026-08-26T10:00:00Z',
          detail: { version: '0.9.2', error: `verify failed for digest ${DEVICE_PK}` },
        },
      ],
    });
    renderDetail();
    fireEvent.click(await screen.findByRole('tab', { name: 'Events' }));

    // More than one match on purpose: the timeline row, and the banner the
    // header derives from that same event (AGT-14's update_failed).
    await waitFor(() => expect(screen.getAllByText('Update failed').length).toBeGreaterThan(0));
    expect(everythingShown()).toContain('0.9.2');
    expect(everythingShown()).not.toContain(DEVICE_PK);
  });
});

describe('a rejected capability config change', () => {
  it('reports the server’s reason with secret-shaped material removed', async () => {
    api.setAgentCapabilities.mockRejectedValue({
      response: {
        status: 400,
        data: { detail: `invalid config for ${DEVICE_PK}: interval_s out of range` },
      },
    });
    renderDetail();

    const cadence = await screen.findByRole('spinbutton');
    fireEvent.change(cadence, { target: { value: '60' } });

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    const message = mockToast.error.mock.calls.at(-1)[0];
    expect(message).toContain('interval_s out of range');
    expect(message).not.toContain(DEVICE_PK);
  });
});
