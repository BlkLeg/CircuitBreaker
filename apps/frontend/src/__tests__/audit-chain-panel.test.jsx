import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../api/audit', () => ({
  verifyChain: vi.fn(),
  repairChain: vi.fn(),
  REPAIR_AUTHORIZATION: 'REPAIR_AUDIT_CHAIN',
}));

import { verifyChain, repairChain } from '../api/audit';
import AuditChainPanel from '../components/logs/AuditChainPanel.jsx';

const INTACT = { valid: true, first_failure_id: null, message: 'ok', checked_count: 12481 };
const BROKEN = {
  valid: false,
  first_failure_id: 8214,
  message: 'Log id=8214: previous_hash mismatch (chain broken).',
  checked_count: 12481,
};

beforeEach(() => vi.clearAllMocks());

describe('AuditChainPanel', () => {
  it('reports an intact chain quietly, with the count checked', async () => {
    verifyChain.mockResolvedValue({ data: INTACT });
    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain intact/i)).toBeInTheDocument());
    expect(screen.getByText(/12,?481/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /repair/i })).not.toBeInTheDocument();
  });

  it('escalates a broken chain and names the first failing entry', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });
    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    expect(screen.getByText(/8214/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /repair chain/i })).toBeInTheDocument();
  });

  it('says repair does not recover altered entries', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });
    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    expect(screen.getByText(/does not recover/i)).toBeInTheDocument();
  });

  it('requires both the phrase and a long-enough reason before repairing', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });
    repairChain.mockResolvedValue({ data: { repaired: true } });
    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /repair chain/i }));

    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'too short' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'chain broken after database restore' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() =>
      expect(repairChain).toHaveBeenCalledWith({ reason: 'chain broken after database restore' })
    );
  });

  it('re-verifies and notifies the host after a repair, so the repair entry appears', async () => {
    verifyChain.mockResolvedValueOnce({ data: BROKEN }).mockResolvedValue({ data: INTACT });
    repairChain.mockResolvedValue({ data: { repaired: true } });
    const onRepaired = vi.fn();
    render(<AuditChainPanel onRepaired={onRepaired} />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /repair chain/i }));
    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'chain broken after database restore' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText(/chain intact/i)).toBeInTheDocument());
    expect(onRepaired).toHaveBeenCalled();
  });

  it('surfaces a repair rejection in the dialog without closing it', async () => {
    verifyChain.mockResolvedValue({ data: BROKEN });
    repairChain.mockRejectedValue({ userMessage: 'authorization must equal…' });
    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /repair chain/i }));
    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'chain broken after database restore' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('authorization must equal')
    );
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument();
  });

  it('never lets a failed verification look like a passed one', async () => {
    verifyChain.mockRejectedValue(new Error('boom'));
    render(<AuditChainPanel />);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByText(/chain intact/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
