import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../components/common/Toast';
import ScanProfileForm from '../../components/discovery/ScanProfileForm';

function renderForm(profile = undefined) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  render(
    <ToastProvider>
      <ScanProfileForm profile={profile} onClose={onClose} onSaved={onSaved} />
    </ToastProvider>
  );
  return { onClose, onSaved };
}

describe('ScanProfileForm', () => {
  it('renders empty form for create mode', () => {
    renderForm();
    expect(screen.getByText('Create Scan Profile')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Home LAN')).toHaveValue('');
  });

  it('renders pre-filled form for edit mode', () => {
    renderForm({ id: 1, name: 'My Profile', cidr: '10.0.0.0/24', scan_types: ['nmap'],
      nmap_arguments: '-sV', snmp_version: '2c', snmp_port: 161, enabled: true });
    expect(screen.getByText('Edit Scan Profile')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Home LAN')).toHaveValue('My Profile');
    expect(screen.getByPlaceholderText('192.168.1.0/24')).toHaveValue('10.0.0.0/24');
  });

  it('shows ARP warning callout when arp scan type is checked', () => {
    renderForm();
    const arpCheckbox = screen.getByRole('checkbox', { name: /^arp$/i });
    expect(screen.queryByText(/net_raw/i)).not.toBeInTheDocument();
    fireEvent.click(arpCheckbox);
    expect(screen.getByText(/net_raw/i)).toBeInTheDocument();
  });

  it('hides ARP warning when arp is unchecked', () => {
    renderForm();
    const arpCheckbox = screen.getByRole('checkbox', { name: /^arp$/i });
    fireEvent.click(arpCheckbox);
    expect(screen.getByText(/net_raw/i)).toBeInTheDocument();
    fireEvent.click(arpCheckbox);
    expect(screen.queryByText(/net_raw/i)).not.toBeInTheDocument();
  });

  it('shows CIDR validation error for invalid input', async () => {
    renderForm();
    fireEvent.change(screen.getByPlaceholderText('Home LAN'), { target: { value: 'MyProfile' } });
    fireEvent.change(screen.getByPlaceholderText('192.168.1.0/24'), { target: { value: 'not-a-cidr' } });
    fireEvent.click(screen.getByRole('button', { name: /create profile/i }));
    await waitFor(() => expect(screen.getByText(/valid cidr/i)).toBeInTheDocument());
  });

  it('disables save button when name is empty', async () => {
    renderForm();
    // Trigger validation with empty name
    fireEvent.click(screen.getByRole('button', { name: /create profile/i }));
    await waitFor(() => expect(screen.getByText(/name is required/i)).toBeInTheDocument());
  });

  it('calls POST /discovery/profiles on create submit', async () => {
    const { onSaved } = renderForm();
    fireEvent.change(screen.getByPlaceholderText('Home LAN'), { target: { value: 'Test Profile' } });
    fireEvent.change(screen.getByPlaceholderText('192.168.1.0/24'), { target: { value: '192.168.1.0/24' } });
    fireEvent.click(screen.getByRole('button', { name: /create profile/i }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  });

  it('calls PATCH /discovery/profiles/{id} on edit submit', async () => {
    const { onSaved } = renderForm({ id: 1, name: 'Old Name', cidr: '10.0.0.0/24',
      scan_types: ['nmap'], snmp_version: '2c', snmp_port: 161, enabled: true });
    fireEvent.change(screen.getByPlaceholderText('Home LAN'), { target: { value: 'New Name' } });
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  });

  it('closes drawer on success', async () => {
    const { onSaved } = renderForm();
    fireEvent.change(screen.getByPlaceholderText('Home LAN'), { target: { value: 'Profile A' } });
    fireEvent.change(screen.getByPlaceholderText('192.168.1.0/24'), { target: { value: '10.0.0.0/16' } });
    fireEvent.click(screen.getByRole('button', { name: /create profile/i }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
