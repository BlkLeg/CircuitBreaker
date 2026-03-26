import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { TenantProvider, useTenant } from '../context/TenantContext';
import { tenantsApi } from '../api/client';

// Mock tenantsApi
vi.mock('../api/client', () => ({
  tenantsApi: {
    list: vi.fn(),
  },
}));

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

const TestComponent = () => {
  const { activeTenantId, tenants, switchTenant } = useTenant();
  return (
    <div>
      <div data-testid="active-id">{activeTenantId}</div>
      <div data-testid="tenant-count">{tenants.length}</div>
      <button onClick={() => switchTenant('2')}>Switch</button>
    </div>
  );
};

describe('TenantContext', () => {
  const mockTenants = [
    { id: 1, name: 'Default' },
    { id: 2, name: 'Other' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    // Mock window.location.reload
    vi.stubGlobal('location', { reload: vi.fn() });
  });

  it('fetches tenants and sets default', async () => {
    tenantsApi.list.mockResolvedValue({ data: mockTenants });

    render(
      <TenantProvider>
        <TestComponent />
      </TenantProvider>
    );

    await waitFor(() => expect(screen.getByTestId('tenant-count').textContent).toBe('2'));
    expect(screen.getByTestId('active-id').textContent).toBe('1');
    expect(localStorage.getItem('cb_active_tenant_id')).toBe('1');
  });

  it('switches tenant and reloads', async () => {
    tenantsApi.list.mockResolvedValue({ data: mockTenants });

    render(
      <TenantProvider>
        <TestComponent />
      </TenantProvider>
    );

    await waitFor(() => screen.getByText('Switch'));
    act(() => {
      screen.getByText('Switch').click();
    });

    expect(localStorage.getItem('cb_active_tenant_id')).toBe('2');
    expect(window.location.reload).toHaveBeenCalled();
  });
});
