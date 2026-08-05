import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AgentApprovalModal from '../components/agents/AgentApprovalModal.jsx';

const mockGetAgent = vi.fn();
const mockApproveAgent = vi.fn();

vi.mock('../api/agents', () => ({
  getAgent: (...args) => mockGetAgent(...args),
  approveAgent: (...args) => mockApproveAgent(...args),
}));

const mockHardwareList = vi.fn();
const mockHardwareCreate = vi.fn();

vi.mock('../api/client', () => ({
  hardwareApi: {
    list: (...args) => mockHardwareList(...args),
    create: (...args) => mockHardwareCreate(...args),
  },
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

const BASE_AGENT = {
  id: 7,
  hostname: 'box7',
  os: 'linux',
  arch: 'amd64',
  fingerprint: 'f'.repeat(32),
  reported_ip: '10.0.0.7',
  proposed_hardware_id: null,
  proposed_hardware_name: null,
  duplicate_machine_id: false,
};

async function renderModal(agentOverrides = {}) {
  mockGetAgent.mockResolvedValue({ data: { ...BASE_AGENT, ...agentOverrides } });
  const onApproved = vi.fn();
  const onClose = vi.fn();
  render(<AgentApprovalModal agentId={7} onApproved={onApproved} onClose={onClose} />);
  await waitFor(() => expect(screen.getByText(/box7/i)).toBeInTheDocument());
  return { onApproved, onClose };
}

describe('AgentApprovalModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApproveAgent.mockResolvedValue({ data: {} });
    mockHardwareList.mockResolvedValue({ data: [] });
  });

  it('defaults to the normal preset with all three capabilities enabled', async () => {
    await renderModal();

    expect(screen.getByLabelText(/host telemetry/i)).toBeChecked();
    expect(screen.getByLabelText(/local discovery/i)).toBeChecked();
    expect(screen.getByLabelText(/remote probe/i)).toBeChecked();
  });

  it('renders the duplicate-machine warning when the agent-detail flags one', async () => {
    await renderModal({ duplicate_machine_id: true });

    expect(screen.getByRole('alert')).toHaveTextContent(/same machine ID/i);
  });

  it('does not render a duplicate warning when there is none', async () => {
    await renderModal({ duplicate_machine_id: false });

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('defaults host-link action to accept when a hardware match is proposed, and submits it', async () => {
    await renderModal({ proposed_hardware_id: 42, proposed_hardware_name: 'rack-server-1' });

    expect(screen.getByLabelText(/accept proposed hardware/i)).toBeChecked();

    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() => expect(mockApproveAgent).toHaveBeenCalled());
    expect(mockApproveAgent).toHaveBeenCalledWith(7, {
      hardware_id: 42,
      host_link_action: 'accept',
      capabilities: { host_telemetry: true, local_discovery: true, remote_probe: true },
    });
  });

  it('submits null hardware_id and "unlinked" when nothing is proposed and left as-is', async () => {
    await renderModal();

    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() => expect(mockApproveAgent).toHaveBeenCalled());
    expect(mockApproveAgent).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ hardware_id: null, host_link_action: 'unlinked' })
    );
  });

  it('lets the approver select a different existing hardware record', async () => {
    mockHardwareList.mockResolvedValue({
      data: [
        { id: 1, name: 'switch-a' },
        { id: 2, name: 'switch-b' },
      ],
    });
    await renderModal({ proposed_hardware_id: 42, proposed_hardware_name: 'rack-server-1' });

    fireEvent.click(screen.getByLabelText(/select another hardware record/i));
    await waitFor(() => expect(mockHardwareList).toHaveBeenCalled());

    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: '2' } });

    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() => expect(mockApproveAgent).toHaveBeenCalled());
    expect(mockApproveAgent).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ hardware_id: 2, host_link_action: 'select' })
    );
  });

  it('creates a new hardware record from reported facts before approving', async () => {
    mockHardwareCreate.mockResolvedValue({ data: { id: 99, name: 'box7' } });
    await renderModal();

    fireEvent.click(screen.getByLabelText(/create a new hardware record/i));

    const nameInput = screen.getByLabelText(/new hardware name/i);
    expect(nameInput).toHaveValue('box7');

    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() =>
      expect(mockHardwareCreate).toHaveBeenCalledWith({
        name: 'box7',
        ip_address: '10.0.0.7',
      })
    );
    await waitFor(() =>
      expect(mockApproveAgent).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ hardware_id: 99, host_link_action: 'create' })
      )
    );
  });

  it('lets the approver opt out of a capability before activation', async () => {
    await renderModal();

    fireEvent.click(screen.getByLabelText(/remote probe/i));
    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() => expect(mockApproveAgent).toHaveBeenCalled());
    expect(mockApproveAgent).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        capabilities: { host_telemetry: true, local_discovery: true, remote_probe: false },
      })
    );
  });
});
