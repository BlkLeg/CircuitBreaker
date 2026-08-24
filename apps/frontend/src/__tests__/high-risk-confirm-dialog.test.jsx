import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import HighRiskConfirmDialog from '../components/common/HighRiskConfirmDialog.jsx';

const baseProps = {
  open: true,
  title: 'Rotate the agent server key',
  body: 'This starts a 7-day overlap.',
  confirmPhrase: 'ROTATE',
  reason: null,
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

beforeEach(() => vi.clearAllMocks());

describe('HighRiskConfirmDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<HighRiskConfirmDialog {...baseProps} open={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('disables confirm until the phrase is typed exactly', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    const confirm = screen.getByRole('button', { name: /^confirm$/i });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    expect(confirm).toBeEnabled();
  });

  it('rejects a near-miss phrase, including wrong case', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    const input = screen.getByLabelText(/type rotate to confirm/i);

    fireEvent.change(input, { target: { value: 'rotate' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(input, { target: { value: 'ROTATE ' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();
  });

  it('requires the reason to meet its minimum length when one is configured', () => {
    render(
      <HighRiskConfirmDialog
        {...baseProps}
        confirmPhrase="REPAIR_AUDIT_CHAIN"
        reason={{ required: true, minLength: 12, label: 'Reason' }}
      />
    );
    fireEvent.change(screen.getByLabelText(/type repair_audit_chain to confirm/i), {
      target: { value: 'REPAIR_AUDIT_CHAIN' },
    });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'too short' } });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Reason'), {
      target: { value: 'chain broken after restore' },
    });
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeEnabled();
  });

  it('passes the reason to onConfirm', () => {
    render(
      <HighRiskConfirmDialog
        {...baseProps}
        reason={{ required: true, minLength: 12, label: 'Reason' }}
      />
    );
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.change(screen.getByLabelText('Reason'), {
      target: { value: 'planned quarterly rotation' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    expect(baseProps.onConfirm).toHaveBeenCalledWith({ reason: 'planned quarterly rotation' });
  });

  it('passes an empty reason when none is configured', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(baseProps.onConfirm).toHaveBeenCalledWith({ reason: '' });
  });

  it('surfaces a server error without closing', () => {
    render(<HighRiskConfirmDialog {...baseProps} error="A rotation is already active" />);
    expect(screen.getByRole('alert')).toHaveTextContent('A rotation is already active');
  });

  it('disables both buttons while busy', () => {
    render(<HighRiskConfirmDialog {...baseProps} busy />);
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  it('cancels on the cancel button', () => {
    render(<HighRiskConfirmDialog {...baseProps} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(baseProps.onCancel).toHaveBeenCalled();
  });

  it('clears typed input when reopened', () => {
    const { rerender } = render(<HighRiskConfirmDialog {...baseProps} />);
    fireEvent.change(screen.getByLabelText(/type rotate to confirm/i), {
      target: { value: 'ROTATE' },
    });
    rerender(<HighRiskConfirmDialog {...baseProps} open={false} />);
    rerender(<HighRiskConfirmDialog {...baseProps} open />);

    expect(screen.getByLabelText(/type rotate to confirm/i)).toHaveValue('');
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled();
  });
});
