import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../api/agents', () => ({
  getServerKeyStatus: vi.fn(),
  rotateServerKey: vi.fn(),
  getServerKeyPendingAgents: vi.fn(),
}));

import { getServerKeyStatus, rotateServerKey, getServerKeyPendingAgents } from '../api/agents';
import ServerKeyRotationPanel from '../components/agents/ServerKeyRotationPanel.jsx';

const IDLE = {
  active: false,
  current_key_fingerprint: 'a3f9c1e27b40d5a3f9c1e27b40d5a3f9',
  successor_key_fingerprint: null,
  started_at: null,
  overlap_expires_at: null,
  fleet: null,
};

const ACTIVE = {
  active: true,
  current_key_fingerprint: 'a3f9c1e27b40d5a3f9c1e27b40d5a3f9',
  successor_key_fingerprint: 'e77b0a941c2f8ee77b0a941c2f8ee77b',
  started_at: '2026-08-20T02:00:00Z',
  overlap_expires_at: '2026-08-27T02:00:00Z',
  fleet: { total: 38, successor: 27, current: 6, unseen: 5 },
};

beforeEach(() => {
  vi.clearAllMocks();
  getServerKeyPendingAgents.mockResolvedValue({ data: [] });
});

describe('ServerKeyRotationPanel', () => {
  it('shows the current fingerprint and an enabled Rotate when idle', async () => {
    getServerKeyStatus.mockResolvedValue({ data: IDLE });

    render(<ServerKeyRotationPanel />);

    await waitFor(() => expect(screen.getByText(/no rotation in progress/i)).toBeInTheDocument());
    expect(screen.getByText(/a3f9c1e2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /rotate key/i })).toBeEnabled();
  });

  it('frames itself as a named region carrying the rotation state in its head', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);

    const panel = await screen.findByRole('region', { name: 'Agent server key' });
    // The state and the control that changes it read from the panel's own
    // head, so an operator scanning the page sees whether a rotation is in
    // flight without reading the fingerprints underneath.
    expect(within(panel).getByText('rotation in progress')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: /rotate key/i })).toBeInTheDocument();
  });

  it('disables Rotate during an overlap and says why', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);

    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /rotate key/i })).toBeDisabled();
    expect(screen.getByText(/one rotation in flight/i)).toBeInTheDocument();
  });

  it('reports adoption without claiming an agent holds the successor key', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);

    await waitFor(() =>
      expect(screen.getByText(/27 authenticated with successor/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/6 still on current/i)).toBeInTheDocument();
    expect(screen.getByText(/5 not seen since rotation/i)).toBeInTheDocument();
    expect(screen.queryByText(/has the successor/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/will fail/i)).not.toBeInTheDocument();
  });

  it('expands the drill-down of agents not yet on the successor', async () => {
    getServerKeyStatus.mockResolvedValue({ data: ACTIVE });
    getServerKeyPendingAgents.mockResolvedValue({
      data: [
        { id: 1, hostname: 'lagging-01', name: null, last_seen_at: null, bucket: 'current' },
        { id: 2, hostname: 'never-01', name: null, last_seen_at: null, bucket: 'unseen' },
      ],
    });

    render(<ServerKeyRotationPanel />);
    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /show agents/i }));

    await waitFor(() => expect(screen.getByText('lagging-01')).toBeInTheDocument());
    expect(screen.getByText('never-01')).toBeInTheDocument();
  });

  it('rotates only after the phrase is typed, then refetches', async () => {
    getServerKeyStatus.mockResolvedValueOnce({ data: IDLE }).mockResolvedValue({ data: ACTIVE });
    rotateServerKey.mockResolvedValue({ data: ACTIVE });

    render(<ServerKeyRotationPanel />);
    await waitFor(() => expect(screen.getByText(/no rotation in progress/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /rotate key/i }));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(rotateServerKey).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(rotateServerKey).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());
  });

  it('treats a racing 409 as state, not as an error', async () => {
    getServerKeyStatus.mockResolvedValueOnce({ data: IDLE }).mockResolvedValue({ data: ACTIVE });
    rotateServerKey.mockRejectedValue({ response: { status: 409 } });

    render(<ServerKeyRotationPanel />);
    await waitFor(() => expect(screen.getByText(/no rotation in progress/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /rotate key/i }));
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText(/rotation in progress/i)).toBeInTheDocument());
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('renders an error distinct from the idle state when status cannot be read', async () => {
    getServerKeyStatus.mockRejectedValue(new Error('boom'));

    render(<ServerKeyRotationPanel />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByText(/no rotation in progress/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
