import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AddAgentPanel from '../components/agents/AddAgentPanel';

// Design §5 pins two behaviours of this panel: the waiting → checked-in
// transition (driven by the pending rows a live `enrolled` event splices into
// the page) and the inline install-command error. Both are what make the flow
// "one continuous flow that ends when the agent is approved" rather than a
// command handed over and an enrollment surfacing somewhere else later.
vi.mock('../api/agents', () => ({
  getInstallCommand: vi.fn(),
  getAgent: vi.fn(),
  getCapabilityDefaults: vi.fn(),
  approveAgent: vi.fn(),
  rejectAgent: vi.fn(),
  lookupPairingCode: vi.fn(),
  mintEnrollmentToken: vi.fn(),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

// The endpoint picker reads the operator-declared list off the settings
// context rather than fetching it, so a mutable holder is what lets one test
// run with endpoints configured and another with none.
const settingsMock = vi.hoisted(() => ({ current: { agent_endpoints: [] } }));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: settingsMock.current, reloadSettings: vi.fn(), loading: false }),
}));

import {
  approveAgent,
  getAgent,
  getCapabilityDefaults,
  getInstallCommand,
  mintEnrollmentToken,
} from '../api/agents';

const INSTALL = {
  tls_mode: 'self_signed',
  command: 'curl -fsSL https://cb.local/install.sh | sh',
  script_sha256: 'abc123',
};
const SERVER_DEFAULTS = { host_telemetry: { enabled: true, config: { interval_s: 30 } } };
const PENDING = [{ id: 9, hostname: 'box9', fingerprint: 'c'.repeat(32) }];

const ENDPOINTS = [
  { id: 'lan1', label: 'LAN', url: 'https://10.0.0.5' },
  { id: 'pub1', label: 'Public', url: 'https://cb.example.com' },
];

describe('AddAgentPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settingsMock.current = { agent_endpoints: [] };
    getInstallCommand.mockResolvedValue({ data: INSTALL });
    getAgent.mockResolvedValue({
      data: { id: 9, hostname: 'box9', os: 'linux', arch: 'amd64', fingerprint: 'c'.repeat(32) },
    });
    getCapabilityDefaults.mockResolvedValue({ data: SERVER_DEFAULTS });
    approveAgent.mockResolvedValue({ data: {} });
  });

  it('fetches the command on its own when it is the whole page', async () => {
    render(<AddAgentPanel isStandalone pendingAgents={[]} />);

    expect(await screen.findByText(INSTALL.command)).toBeInTheDocument();
    expect(screen.getByText('self-signed')).toBeInTheDocument();
    // The generated script is Linux-only (useradd, sha256sum), so the other
    // platforms are advertised as unavailable rather than fabricated.
    expect(screen.getByRole('button', { name: 'macOS' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Linux' })).toBeEnabled();
  });

  it('never throws when the clipboard API is absent, as in jsdom and on http', async () => {
    render(<AddAgentPanel isStandalone pendingAgents={[]} />);
    await screen.findByText(INSTALL.command);

    expect(navigator.clipboard).toBeUndefined();
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(screen.getByText(INSTALL.command)).toBeInTheDocument();
  });

  it('renders what the server said went wrong inline, and still toasts it', async () => {
    getInstallCommand.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { detail: 'The TLS certificate at /x/y.pem is not readable' },
      },
    });

    render(<AddAgentPanel isStandalone pendingAgents={[]} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/not readable/i);
    expect(mockToast.error).toHaveBeenCalledWith(expect.stringContaining('not readable'));
  });

  it('turns the admin-only 403 into an instruction rather than a raw refusal', async () => {
    getInstallCommand.mockRejectedValueOnce({ response: { status: 403, data: {} } });

    render(<AddAgentPanel isStandalone pendingAgents={[]} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Ask an administrator for the install command'
    );
  });

  it('flips from waiting to checked in when a pending agent appears', async () => {
    const { rerender } = render(<AddAgentPanel isStandalone pendingAgents={[]} />);
    await screen.findByText(INSTALL.command);
    expect(screen.getByText(/Waiting for the machine to check in/i)).toBeInTheDocument();

    rerender(<AddAgentPanel isStandalone pendingAgents={PENDING} />);

    expect(await screen.findByText(/Waiting for approval/i)).toBeInTheDocument();
    expect(screen.getByText(/box9 checked in/i)).toBeInTheDocument();
  });

  it('approves with the server capability defaults, never a local preset', async () => {
    const onApproved = vi.fn();
    render(<AddAgentPanel isStandalone pendingAgents={PENDING} onApproved={onApproved} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    await waitFor(() =>
      expect(approveAgent).toHaveBeenCalledWith(9, { capabilities: SERVER_DEFAULTS })
    );
    expect(onApproved).toHaveBeenCalled();
  });

  it('hands off to the full review flow rather than approving on a guess', async () => {
    // Without the AgentRead there is no duplicate_machine_id to show, and
    // without the server defaults there is no grant to send — so the inline
    // path must step aside instead of improvising either one.
    getCapabilityDefaults.mockRejectedValueOnce(new Error('boom'));
    const onReview = vi.fn();
    render(<AddAgentPanel isStandalone pendingAgents={PENDING} onReview={onReview} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));

    expect(onReview).toHaveBeenCalledWith(9);
    expect(approveAgent).not.toHaveBeenCalled();
  });

  it('shows the fingerprint comparison it shares with the approval modal', async () => {
    render(<AddAgentPanel isStandalone pendingAgents={PENDING} />);

    expect(await screen.findByText('c'.repeat(32))).toBeInTheDocument();
    expect(screen.getByText(/Compare this fingerprint/i)).toBeInTheDocument();
  });

  it('puts the failure inline in the panel the operator just opened, not only in a toast', async () => {
    // The standalone case above covers the empty-fleet page; this is the common
    // one — a fleet that already exists, so the panel is inline and collapsed
    // until asked for. Design §4 puts the reason where the operator is looking,
    // and a toast that has faded by the time they scroll back is not that.
    getInstallCommand.mockRejectedValueOnce({
      response: { status: 503, data: { detail: 'No TLS certificate has been issued yet' } },
    });

    render(<AddAgentPanel pendingAgents={[]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add agent' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/No TLS certificate/i);
    expect(mockToast.error).toHaveBeenCalledWith(expect.stringContaining('No TLS certificate'));
  });

  it('starts collapsed behind Add agent when the fleet is not empty', async () => {
    render(<AddAgentPanel pendingAgents={[]} />);

    expect(getInstallCommand).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Add agent' }));

    expect(await screen.findByText(INSTALL.command)).toBeInTheDocument();
  });

  // ── Which address the agent is told to dial ───────────────────────────────

  it('requests the install command for the chosen endpoint', async () => {
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    render(<AddAgentPanel isStandalone pendingAgents={[]} />);
    await screen.findByText(INSTALL.command);

    fireEvent.change(screen.getByLabelText(/endpoint/i), { target: { value: 'pub1' } });

    await waitFor(() => expect(getInstallCommand).toHaveBeenCalledWith('pub1', null));
  });

  it('defaults to the endpoint matching the address this browser is on', async () => {
    // Nothing matches jsdom's origin, so the first endpoint stands in — the
    // operator who never opens the picker still gets a declared address, not
    // an empty one.
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    render(<AddAgentPanel isStandalone pendingAgents={[]} />);

    await waitFor(() => expect(getInstallCommand).toHaveBeenCalledWith('lan1', null));
    expect(screen.getByLabelText(/endpoint/i)).toHaveValue('lan1');
  });

  it('warns when no endpoint is configured, because the browsed host will be used', async () => {
    render(<AddAgentPanel isStandalone pendingAgents={[]} />);
    await screen.findByText(INSTALL.command);

    expect(screen.getByText(/address you are browsing/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/endpoint/i)).not.toBeInTheDocument();
    expect(getInstallCommand).toHaveBeenCalledWith('', null);
  });

  it('names the address to check once nothing has checked in for 90 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);
      expect(screen.queryByText(/Nothing has checked in yet/i)).not.toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(90_000);

      expect(await screen.findByText(/Nothing has checked in yet/i)).toBeInTheDocument();
      // The address is the whole point of the warning: "unreachable" is not
      // actionable, "https://10.0.0.5 is unreachable" is.
      expect(screen.getByText('https://10.0.0.5')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── Slice B: attended or unattended ───────────────────────────────────────

  describe('unattended enrollment', () => {
    it('defaults to attended, and mints nothing until asked', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      expect(screen.getByRole('radio', { name: /^attended/i })).toBeChecked();
      expect(mintEnrollmentToken).not.toHaveBeenCalled();
    });

    it('mints only when the operator asks, not when they choose unattended', async () => {
      // A credential burned on every stray click is a credential nobody can
      // account for.
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));

      expect(mintEnrollmentToken).not.toHaveBeenCalled();
      expect(await screen.findByRole('button', { name: /generate token/i })).toBeInTheDocument();
    });

    it('shows the token once, and says so', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_shown-once' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));

      expect(await screen.findByText('cbe_shown-once')).toBeInTheDocument();
      expect(screen.getByText(/not be shown again/i)).toBeInTheDocument();
    });

    it('warns that the token must not be passed as an argument', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));

      expect(await screen.findByText(/visible in/i)).toBeInTheDocument();
    });

    it('re-fetches the command with the token, so the copied command carries it', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));

      await waitFor(() => expect(getInstallCommand).toHaveBeenLastCalledWith('lan1', 'cbe_x'));
    });

    it('mints for the endpoint that is selected', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.change(screen.getByLabelText(/endpoint/i), { target: { value: 'pub1' } });
      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));

      await waitFor(() =>
        expect(mintEnrollmentToken).toHaveBeenCalledWith(
          expect.objectContaining({ endpoint_id: 'pub1' })
        )
      );
    });

    it('drops a minted token when the endpoint changes, since it is scoped to one', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);
      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));
      await screen.findByText('cbe_x');

      fireEvent.change(screen.getByLabelText(/endpoint/i), { target: { value: 'pub1' } });

      await waitFor(() => expect(screen.queryByText('cbe_x')).not.toBeInTheDocument());
      await waitFor(() => expect(getInstallCommand).toHaveBeenLastCalledWith('pub1', null));
    });

    it('drops the token when the operator goes back to attended', async () => {
      // Otherwise the copied command still carries a credential they think
      // they abandoned.
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);
      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));
      await screen.findByText('cbe_x');

      fireEvent.click(screen.getByRole('radio', { name: /^attended/i }));

      await waitFor(() => expect(screen.queryByText('cbe_x')).not.toBeInTheDocument());
      await waitFor(() => expect(getInstallCommand).toHaveBeenLastCalledWith('lan1', null));
    });

    it('surfaces a mint failure inline rather than silently staying attended', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockRejectedValue({ response: { data: { detail: 'no endpoint' } } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));

      expect(await screen.findByText(/no endpoint/)).toBeInTheDocument();
      expect(mockToast.error).toHaveBeenCalled();
    });

    it('tells the operator the machine will not wait for approval', async () => {
      settingsMock.current = { agent_endpoints: ENDPOINTS };
      mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
      render(<AddAgentPanel isStandalone pendingAgents={[]} />);
      await screen.findByText(INSTALL.command);

      fireEvent.click(screen.getByRole('radio', { name: /^unattended/i }));
      fireEvent.click(await screen.findByRole('button', { name: /generate token/i }));

      // Wait for the mint to land first: before it does, the *pre*-mint copy
      // carries this same sentence, so asserting straight away can pass or
      // fail on whichever render it catches.
      await screen.findByText('cbe_x');
      expect(await screen.findByText(/without waiting for approval/i)).toBeInTheDocument();
    });
  });
});
