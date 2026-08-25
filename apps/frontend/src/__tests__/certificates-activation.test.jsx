import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const certs = [
  { id: 1, domain: 'a.example.com', type: 'selfsigned', auto_renew: true, is_active: false },
  { id: 2, domain: 'b.example.com', type: 'letsencrypt', auto_renew: true, is_active: true },
];

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
    certificatesApi: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      renew: vi.fn(),
      activate: vi.fn(),
    },
  };
});

const mockToast = { success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { show_page_hints: false }, reloadSettings: vi.fn() }),
}));

// Render the real columns + action cell, stub the rest of the table.
vi.mock('../components/EntityTable', () => ({
  default: ({ columns, data, renderMonitorAction }) =>
    React.createElement(
      'table',
      null,
      React.createElement(
        'thead',
        null,
        React.createElement(
          'tr',
          null,
          columns.map((col) => React.createElement('th', { key: col.key }, col.label))
        )
      ),
      React.createElement(
        'tbody',
        null,
        data.map((row) =>
          React.createElement(
            'tr',
            { key: row.id },
            columns.map((col) =>
              React.createElement(
                'td',
                { key: col.key },
                typeof col.render === 'function' ? col.render(row[col.key], row) : row[col.key]
              )
            ),
            React.createElement('td', { key: 'actions' }, renderMonitorAction?.(row))
          )
        )
      )
    ),
}));

vi.mock('../components/SearchBox', () => ({ default: () => null }));
vi.mock('../components/common/FormModal', () => ({ default: () => null }));
vi.mock('../components/common/ConfirmDialog', () => ({ default: () => null }));
vi.mock('../components/details/CertificateDetail', () => ({ default: () => null }));

import { certificatesApi } from '../api/client';
import CertificatesPage from '../pages/CertificatesPage.jsx';

describe('CertificatesPage activation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    certificatesApi.list.mockResolvedValue({ data: certs });
  });

  it('shows which certificate is served, and offers Activate only on the others', async () => {
    render(<CertificatesPage />);

    await waitFor(() => expect(screen.getByRole('columnheader', { name: 'Active' })).toBeTruthy());
    expect(screen.getAllByText('SERVED')).toHaveLength(1);
    // b.example.com is already served, so only a.example.com can be activated.
    expect(screen.getAllByRole('button', { name: 'Activate' })).toHaveLength(1);
  });

  it('reports a reloaded activation as success', async () => {
    certificatesApi.activate.mockResolvedValue({
      data: { written: true, reloaded: true, detail: 'nginx reloaded via supervisorctl' },
    });
    render(<CertificatesPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Activate' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }));

    await waitFor(() => expect(certificatesApi.activate).toHaveBeenCalledWith(1));
    await waitFor(() => expect(mockToast.success).toHaveBeenCalled());
    expect(mockToast.warn).not.toHaveBeenCalled();
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('reports "written but not reloaded" as a warning quoting the detail verbatim', async () => {
    certificatesApi.activate.mockResolvedValue({
      data: { written: true, reloaded: false, detail: 'no TLS server was found to reload' },
    });
    render(<CertificatesPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Activate' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }));

    // Not success — the operator is still being served the old certificate.
    await waitFor(() =>
      expect(mockToast.warn).toHaveBeenCalledWith('no TLS server was found to reload')
    );
    expect(mockToast.success).not.toHaveBeenCalled();
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('reports a failed request as an error', async () => {
    certificatesApi.activate.mockRejectedValue(new Error('403 Forbidden'));
    render(<CertificatesPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Activate' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith('403 Forbidden'));
    expect(mockToast.success).not.toHaveBeenCalled();
    expect(mockToast.warn).not.toHaveBeenCalled();
  });
});
