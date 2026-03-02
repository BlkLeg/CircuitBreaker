import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ToastProvider } from '../../components/common/Toast';
import ScanAckModal from '../../components/discovery/ScanAckModal';

// client.jsx settingsApi is called by ScanAckModal — MSW handles it via handlers.js

function renderModal(onConfirm = vi.fn(), onCancel = vi.fn()) {
  return render(
    <ToastProvider>
      <ScanAckModal onConfirm={onConfirm} onCancel={onCancel} />
    </ToastProvider>
  );
}

describe('ScanAckModal', () => {
  it('renders modal with checkbox unchecked by default', () => {
    renderModal();
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).not.toBeChecked();
  });

  it('confirm button is disabled when checkbox is unchecked', () => {
    renderModal();
    const confirmBtn = screen.getByRole('button', { name: /i understand/i });
    expect(confirmBtn).toBeDisabled();
  });

  it('confirm button enables when checkbox is checked', () => {
    renderModal();
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
    const confirmBtn = screen.getByRole('button', { name: /i understand/i });
    expect(confirmBtn).not.toBeDisabled();
  });

  it('clicking the backdrop does not call onCancel', () => {
    const onCancel = vi.fn();
    renderModal(vi.fn(), onCancel);
    // The backdrop div has no onClick — clicking it should do nothing
    const backdrop = screen.getByRole('dialog').parentElement;
    fireEvent.click(backdrop);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancel button calls onCancel', () => {
    const onCancel = vi.fn();
    renderModal(vi.fn(), onCancel);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('confirm button calls PUT /settings and onConfirm on success', async () => {
    const onConfirm = vi.fn();
    renderModal(onConfirm);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /i understand/i }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledOnce());
  });

  it('shows dialog title "Before You Scan"', () => {
    renderModal();
    expect(screen.getByText(/before you scan/i)).toBeInTheDocument();
  });
});
