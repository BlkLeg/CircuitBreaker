/**
 * Adding a Proxmox cluster with a required field left empty.
 *
 * Save used to be disabled until name, URL and token were all filled, with
 * nothing saying which was missing — and the name's placeholder ("Main
 * Cluster") read like a value already typed in. The form looked complete and
 * the button did nothing. Save now stays enabled and says what is missing.
 */
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ProxmoxIntegrationSection from '../components/proxmox/ProxmoxIntegrationSection';
import { proxmoxApi } from '../api/client';

vi.mock('../api/client', () => ({
  proxmoxApi: {
    list: vi.fn(),
    status: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    test: vi.fn(),
    discover: vi.fn(),
  },
}));

async function openAddForm() {
  render(<ProxmoxIntegrationSection />);
  await waitFor(() => expect(proxmoxApi.list).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button', { name: '+ Add Cluster' }));
  return {
    name: screen.getByLabelText('Name'),
    url: screen.getByLabelText('URL'),
    token: screen.getByLabelText('API Token'),
    save: screen.getByRole('button', { name: 'Save' }),
  };
}

describe('ProxmoxIntegrationSection add form', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    proxmoxApi.list.mockResolvedValue({ data: [] });
    proxmoxApi.create.mockResolvedValue({ data: { id: 1 } });
  });

  it('keeps Save enabled and marks a missing name instead of doing nothing', async () => {
    const { name, url, token, save } = await openAddForm();
    fireEvent.change(url, { target: { value: 'https://pve.local:8006' } });
    fireEvent.change(token, { target: { value: 'root@pam!cb=abc' } });

    expect(save).toBeEnabled();
    fireEvent.click(save);

    expect(await screen.findByText('Name missing')).toBeInTheDocument();
    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(proxmoxApi.create).not.toHaveBeenCalled();
  });

  it('reads the name placeholder as an example, not a value', async () => {
    const { name } = await openAddForm();
    expect(name).toHaveValue('');
    expect(name).toHaveAttribute('placeholder', 'e.g. Main Cluster');
  });

  it('treats a whitespace-only name as missing', async () => {
    const { name, url, token, save } = await openAddForm();
    fireEvent.change(name, { target: { value: '   ' } });
    fireEvent.change(url, { target: { value: 'https://pve.local:8006' } });
    fireEvent.change(token, { target: { value: 'root@pam!cb=abc' } });
    fireEvent.click(save);

    expect(await screen.findByText('Name missing')).toBeInTheDocument();
    expect(proxmoxApi.create).not.toHaveBeenCalled();
  });

  it('marks every missing required field at once', async () => {
    const { save } = await openAddForm();
    fireEvent.click(save);

    expect(await screen.findByText('Name missing')).toBeInTheDocument();
    expect(screen.getByText('URL missing')).toBeInTheDocument();
    expect(screen.getByText('API token missing')).toBeInTheDocument();
  });

  it('clears a field error as soon as the user types in that field', async () => {
    const { name, save } = await openAddForm();
    fireEvent.click(save);
    expect(await screen.findByText('Name missing')).toBeInTheDocument();

    fireEvent.change(name, { target: { value: 'Homelab' } });

    expect(screen.queryByText('Name missing')).not.toBeInTheDocument();
    expect(name).not.toHaveAttribute('aria-invalid');
    expect(screen.getByText('URL missing')).toBeInTheDocument();
  });

  it('saves once every required field is filled', async () => {
    const { name, url, token, save } = await openAddForm();
    fireEvent.change(name, { target: { value: 'Homelab' } });
    fireEvent.change(url, { target: { value: 'pve.local:8006' } });
    fireEvent.change(token, { target: { value: 'root@pam!cb=abc' } });
    fireEvent.click(save);

    await waitFor(() => expect(proxmoxApi.create).toHaveBeenCalledTimes(1));
    expect(proxmoxApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Homelab', config_url: 'https://pve.local:8006' })
    );
    expect(screen.queryByText(/missing$/)).not.toBeInTheDocument();
  });
});
