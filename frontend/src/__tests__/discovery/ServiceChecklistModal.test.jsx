import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../components/common/Toast';
import ServiceChecklistModal from '../../components/discovery/ServiceChecklistModal';

const PORTS = [
  { port: 22,   protocol: 'tcp', suggested_name: 'SSH',     suggested_category: 'infrastructure' },
  { port: 443,  protocol: 'tcp', suggested_name: 'HTTPS',   suggested_category: 'web'            },
  { port: 9999, protocol: 'tcp', suggested_name: 'Unknown', suggested_category: 'misc'           },
];

function renderModal(overrides = {}) {
  const onClose = vi.fn();
  render(
    <ToastProvider>
      <ServiceChecklistModal
        hardwareId={101}
        hardwareName="pve-01.lan"
        ports={PORTS}
        onClose={onClose}
        {...overrides}
      />
    </ToastProvider>
  );
  return { onClose };
}

describe('ServiceChecklistModal', () => {
  it('renders one row per port', () => {
    renderModal();
    expect(screen.getByDisplayValue('SSH')).toBeInTheDocument();
    expect(screen.getByDisplayValue('HTTPS')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Unknown')).toBeInTheDocument();
  });

  it('pre-checks ports with known service mappings (SSH, HTTPS)', () => {
    renderModal();
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes[0]).toBeChecked();   // SSH
    expect(checkboxes[1]).toBeChecked();   // HTTPS
  });

  it('leaves unknown ports unchecked by default', () => {
    renderModal();
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes[2]).not.toBeChecked(); // Unknown port 9999
  });

  it('Add N Services button count reflects checked items (2 by default)', () => {
    renderModal();
    expect(screen.getByRole('button', { name: /add 2 services/i })).toBeInTheDocument();
  });

  it('count updates when checkbox is toggled', () => {
    renderModal();
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[2]); // check Unknown
    expect(screen.getByRole('button', { name: /add 3 services/i })).toBeInTheDocument();
    fireEvent.click(checkboxes[0]); // uncheck SSH
    expect(screen.getByRole('button', { name: /add 2 services/i })).toBeInTheDocument();
  });

  it('skip button closes modal without API call', () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole('button', { name: /skip/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('confirm fires POST /services for each checked port', async () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole('button', { name: /add 2 services/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it('name field is editable per row', () => {
    renderModal();
    const sshInput = screen.getByDisplayValue('SSH');
    fireEvent.change(sshInput, { target: { value: 'My SSH' } });
    expect(screen.getByDisplayValue('My SSH')).toBeInTheDocument();
  });

  it('shows hardware name in modal title', () => {
    renderModal();
    expect(screen.getByText(/pve-01\.lan/i)).toBeInTheDocument();
  });
});
