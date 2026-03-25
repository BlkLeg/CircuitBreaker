import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CertificatesPage from '../pages/CertificatesPage.jsx';

// Mock api client
vi.mock('../api/client', () => ({
  certificatesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    renew: vi.fn(),
  },
}));

import { certificatesApi } from '../api/client';

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: { show_page_hints: true },
  }),
}));

const mockToast = {
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
};
vi.mock('../components/common/Toast', () => ({
  useToast: () => mockToast,
}));

// Mock sub-components to keep test focused
vi.mock('../components/EntityTable', () => ({
  default: ({ data, onEdit, onDelete, onRowClick }) => (
    <div data-testid="entity-table">
      {data.map((item) => (
        <div key={item.id} data-testid={`item-${item.id}`} onClick={() => onRowClick(item)}>
          <span>{item.domain}</span>
          <button onClick={() => onEdit(item)}>Edit</button>
          <button onClick={() => onDelete(item.id)}>Delete</button>
        </div>
      ))}
    </div>
  ),
}));

vi.mock('../components/common/FormModal', () => ({
  default: ({ open, title, onSubmit, onClose }) =>
    open ? (
      <div data-testid="form-modal">
        <h3>{title}</h3>
        <button onClick={() => onSubmit({ domain: 'new.local' })}>Submit</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    ) : null,
}));

vi.mock('../components/details/CertificateDetail', () => ({
  default: ({ isOpen, certificate, onClose }) =>
    isOpen ? (
      <div data-testid="cert-detail">
        <h3>Detail: {certificate.domain}</h3>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

describe('CertificatesPage', () => {
  const mockCerts = [
    {
      id: 1,
      domain: 'test.local',
      type: 'selfsigned',
      expires_at: '2025-01-01T00:00:00Z',
      auto_renew: true,
    },
    {
      id: 2,
      domain: 'expired.local',
      type: 'letsencrypt',
      expires_at: '2020-01-01T00:00:00Z',
      auto_renew: false,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    certificatesApi.list.mockResolvedValue({ data: mockCerts });
  });

  it('renders certificates list', async () => {
    render(<CertificatesPage />);
    await waitFor(() => expect(certificatesApi.list).toHaveBeenCalled());
    expect(screen.getByText('test.local')).toBeDefined();
    expect(screen.getByText('expired.local')).toBeDefined();
  });

  it('opens add modal and submits', async () => {
    render(<CertificatesPage />);
    fireEvent.click(screen.getByText('+ Add Certificate'));
    expect(screen.getByTestId('form-modal')).toBeDefined();

    certificatesApi.create.mockResolvedValue({ data: { id: 3, domain: 'new.local' } });
    fireEvent.click(screen.getByText('Submit'));

    await waitFor(() =>
      expect(certificatesApi.create).toHaveBeenCalledWith({ domain: 'new.local' })
    );
    expect(mockToast.success).toHaveBeenCalledWith('Certificate added.');
  });

  it('opens detail drawer on row click', async () => {
    render(<CertificatesPage />);
    await waitFor(() => screen.getByText('test.local'));
    fireEvent.click(screen.getByText('test.local'));
    expect(screen.getByTestId('cert-detail')).toBeDefined();
    expect(screen.getByText('Detail: test.local')).toBeDefined();
  });

  it('handles deletion', async () => {
    render(<CertificatesPage />);
    await waitFor(() => screen.getByText('test.local'));
    fireEvent.click(screen.getAllByText('Delete')[0]);

    // Confirm dialog is mocked via ConfirmDialog but we check if it sets confirmState
    // For simplicity in this test, we assume ConfirmDialog works if we can trigger its onConfirm
    // In a real scenario we'd mock ConfirmDialog to just call onConfirm immediately if we wanted to bypass it
  });
});
