import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { TenantProvider, useTenant } from '../context/TenantContext';

const TestComponent = () => {
  const { activeTenantId, tenants, switchTenant, loading } = useTenant();
  return (
    <div>
      <div data-testid="active-id">{activeTenantId ?? 'none'}</div>
      <div data-testid="tenant-count">{tenants.length}</div>
      <div data-testid="loading">{loading ? 'yes' : 'no'}</div>
      <button onClick={() => switchTenant('2')}>Switch</button>
    </div>
  );
};

describe('TenantContext single-tenant compatibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('exposes no active tenant and does not fetch tenant data', () => {
    render(
      <TenantProvider>
        <TestComponent />
      </TenantProvider>
    );

    expect(screen.getByTestId('active-id')).toHaveTextContent('none');
    expect(screen.getByTestId('tenant-count')).toHaveTextContent('0');
    expect(screen.getByTestId('loading')).toHaveTextContent('no');
  });

  it('clears stale active tenant storage on mount', async () => {
    localStorage.setItem('cb_active_tenant_id', '2');

    render(
      <TenantProvider>
        <TestComponent />
      </TenantProvider>
    );

    await waitFor(() => expect(localStorage.getItem('cb_active_tenant_id')).toBeNull());
    expect(screen.getByTestId('active-id')).toHaveTextContent('none');
  });

  it('does not activate a tenant or reload when switchTenant is called', () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { reload });

    render(
      <TenantProvider>
        <TestComponent />
      </TenantProvider>
    );

    fireEvent.click(screen.getByText('Switch'));

    expect(localStorage.getItem('cb_active_tenant_id')).toBeNull();
    expect(screen.getByTestId('active-id')).toHaveTextContent('none');
    expect(reload).not.toHaveBeenCalled();
  });
});
