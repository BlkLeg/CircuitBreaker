import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TenantsPage from '../pages/TenantsPage.jsx';

// Mock api client
vi.mock('../api/client', () => ({
  tenantsApi: {
    list: vi.fn(),
    getMembers: vi.fn(),
    addMember: vi.fn(),
    removeMember: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  adminUsersApi: {
    listUsers: vi.fn(),
  },
}));

import { tenantsApi, adminUsersApi } from '../api/client';

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

// Mock sub-components
vi.mock('../components/EntityTable', () => ({
  default: ({ data, onEdit, onDelete, rowActions }) => (
    <div data-testid="entity-table">
      {data.map((item) => (
        <div key={item.id} data-testid={`tenant-${item.id}`}>
          <span>{item.name}</span>
          <button onClick={() => onEdit?.(item)}>Edit</button>
          <button onClick={() => onDelete?.(item.id)}>Delete</button>
          {rowActions?.map((action) => (
            <button key={action.label} onClick={() => action.onClick(item)}>
              {action.label}
            </button>
          ))}
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
        <button onClick={() => onSubmit({ name: 'New Tenant' })}>Submit</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    ) : null,
}));

vi.mock('../components/common/Drawer', () => ({
  default: ({ isOpen, title, children, onClose }) =>
    isOpen ? (
      <div data-testid="drawer">
        <h3>{title}</h3>
        {children}
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

describe('TenantsPage', () => {
  const mockTenants = [
    { id: 1, name: 'Main Lab', slug: 'main', created_at: '2025-01-01T00:00:00Z' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    tenantsApi.list.mockResolvedValue({ data: mockTenants });
  });

  it('renders tenants list', async () => {
    render(<TenantsPage />);
    await waitFor(() => expect(tenantsApi.list).toHaveBeenCalled());
    expect(screen.getByText('Main Lab')).toBeDefined();
  });

  it('opens add tenant modal', async () => {
    render(<TenantsPage />);
    fireEvent.click(screen.getByText(/Add Tenant/));
    expect(screen.getByTestId('form-modal')).toBeDefined();
  });

  it('opens member management drawer', async () => {
    tenantsApi.getMembers.mockResolvedValue({ data: [] });
    adminUsersApi.listUsers.mockResolvedValue({ data: [] });

    render(<TenantsPage />);
    await waitFor(() => screen.getByText('Main Lab'));

    fireEvent.click(screen.getByText('Members'));
    expect(screen.getByTestId('drawer')).toBeDefined();
    expect(screen.getByText(/Members: Main Lab/)).toBeDefined();
  });
});
