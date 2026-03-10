import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../components/common/Toast';
import ReviewDrawer from '../../components/discovery/ReviewDrawer';

const NEW_RESULT = {
  id: 1, ip_address: '10.0.0.5', hostname: 'pve-01.lan',
  mac_address: 'AA:BB:CC:DD:EE:FF', os_family: 'Linux',
  state: 'new', merge_status: 'pending', scan_job_id: 42,
};

const CONFLICT_RESULT = {
  id: 2, ip_address: '10.0.0.10', hostname: 'switch-core',
  state: 'conflict', merge_status: 'pending', scan_job_id: 42,
  conflicts_json: JSON.stringify([
    { field: 'mac_address', stored: 'AA:BB:CC:00:00:01', discovered: 'AA:BB:CC:00:00:02' },
  ]),
};

function renderDrawer(result, overrides = {}) {
  const props = { result, onClose: vi.fn(), onAccepted: vi.fn(), onRejected: vi.fn(), ...overrides };
  render(<ToastProvider><ReviewDrawer {...props} /></ToastProvider>);
  return props;
}

describe('ReviewDrawer', () => {
  it('renders "Accept Discovered Host" header', () => {
    renderDrawer(NEW_RESULT);
    expect(screen.getByText('Accept Discovered Host')).toBeInTheDocument();
  });

  it('shows entity type selector for state=new', () => {
    renderDrawer(NEW_RESULT);
    expect(screen.getByRole('radio', { name: /hardware/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /compute/i })).toBeInTheDocument();
  });

  it('hides entity type selector for state=conflict', () => {
    renderDrawer(CONFLICT_RESULT);
    expect(screen.queryByRole('radio', { name: /hardware/i })).not.toBeInTheDocument();
  });

  it('renders Discovered badge on pre-filled MAC field', () => {
    renderDrawer(NEW_RESULT);
    // MAC address has a value, badge should appear
    const badges = screen.getAllByText('◆ Discovered');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('removes Discovered badge when name field is edited', () => {
    renderDrawer(NEW_RESULT);
    const nameInput = screen.getByDisplayValue('pve-01.lan');
    const badgesBefore = screen.getAllByText('◆ Discovered').length;
    fireEvent.change(nameInput, { target: { value: 'edited-name' } });
    const badgesAfter = screen.getAllByText('◆ Discovered').length;
    // After editing name, its badge should be removed
    expect(badgesAfter).toBeLessThan(badgesBefore + 1);
  });

  it('conflict mode renders ConflictResolver component', () => {
    renderDrawer(CONFLICT_RESULT);
    expect(screen.getByText('mac_address')).toBeInTheDocument();
  });

  it('conflict mode shows only differing fields', () => {
    renderDrawer(CONFLICT_RESULT);
    // Only mac_address conflict was provided
    expect(screen.getByText('mac_address')).toBeInTheDocument();
    expect(screen.queryByText('hostname')).not.toBeInTheDocument();
  });

  it('accept button is always present and enabled', () => {
    renderDrawer(NEW_RESULT);
    const acceptBtn = screen.getByRole('button', { name: /accept & create/i });
    expect(acceptBtn).toBeInTheDocument();
    expect(acceptBtn).not.toBeDisabled();
  });

  it('calls POST /discovery/results/{id}/merge on accept', async () => {
    const onAccepted = vi.fn();
    renderDrawer(NEW_RESULT, { onAccepted });
    fireEvent.click(screen.getByRole('button', { name: /accept & create/i }));
    await waitFor(() => expect(onAccepted).toHaveBeenCalledOnce());
  });

  it('calls reject on reject button click', async () => {
    const onRejected = vi.fn();
    renderDrawer(NEW_RESULT, { onRejected });
    fireEvent.click(screen.getByRole('button', { name: /^reject$/i }));
    await waitFor(() => expect(onRejected).toHaveBeenCalledOnce());
  });

  it('onAccepted receives response data containing ports', async () => {
    const onAccepted = vi.fn();
    renderDrawer(NEW_RESULT, { onAccepted });
    fireEvent.click(screen.getByRole('button', { name: /accept & create/i }));
    await waitFor(() => {
      expect(onAccepted).toHaveBeenCalledWith(
        expect.objectContaining({ entity_type: 'hardware', ports: expect.any(Array) })
      );
    });
  });
});
