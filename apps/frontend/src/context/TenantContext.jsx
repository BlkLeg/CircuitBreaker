import React, { createContext, useContext, useEffect, useMemo, useCallback } from 'react';
import PropTypes from 'prop-types';

const TenantContext = createContext();
const LEGACY_ACTIVE_TENANT_KEY = 'cb_active_tenant_id';

export function TenantProvider({ children }) {
  useEffect(() => {
    localStorage.removeItem(LEGACY_ACTIVE_TENANT_KEY);
  }, []);

  const switchTenant = useCallback(() => false, []);
  const refreshTenants = useCallback(async () => [], []);

  const value = useMemo(
    () => ({
      tenants: [],
      activeTenant: null,
      activeTenantId: null,
      switchTenant,
      loading: false,
      refreshTenants,
    }),
    [refreshTenants, switchTenant]
  );

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

TenantProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export function useTenant() {
  const context = useContext(TenantContext);
  if (!context) {
    throw new Error('useTenant must be used within a TenantProvider');
  }
  return context;
}
