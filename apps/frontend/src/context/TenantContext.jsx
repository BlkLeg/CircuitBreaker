import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { tenantsApi } from '../api/client';
import { useAuth } from './AuthContext';
import logger from '../utils/logger';

const TenantContext = createContext();

export function TenantProvider({ children }) {
  const { isAuthenticated } = useAuth();
  const [tenants, setTenants] = useState([]);
  const [activeTenantId, setActiveTenantId] = useState(
    localStorage.getItem('cb_active_tenant_id') || null
  );
  const [loading, setLoading] = useState(false);

  const fetchTenants = useCallback(async () => {
    setLoading(true);
    try {
      const res = await tenantsApi.list();
      setTenants(res.data);

      // If no active tenant or active tenant not in the list, pick the first one
      if (res.data.length > 0) {
        const ids = res.data.map((t) => String(t.id));
        if (!activeTenantId || !ids.includes(String(activeTenantId))) {
          const firstId = String(res.data[0].id);
          setActiveTenantId(firstId);
          localStorage.setItem('cb_active_tenant_id', firstId);
        }
      } else {
        setActiveTenantId(null);
        localStorage.removeItem('cb_active_tenant_id');
      }
    } catch (err) {
      logger.error('Failed to fetch tenants:', err);
    } finally {
      setLoading(false);
    }
  }, [activeTenantId]);

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchTenants();
  }, [isAuthenticated]); // Fetch once auth is established

  const switchTenant = (id) => {
    const stringId = String(id);
    setActiveTenantId(stringId);
    localStorage.setItem('cb_active_tenant_id', stringId);
    // Reload the page to ensure all contexts/APIs reset with the new X-Tenant-ID header
    window.location.reload();
  };

  const activeTenant = tenants.find((t) => String(t.id) === String(activeTenantId));

  const value = {
    tenants,
    activeTenant,
    activeTenantId,
    switchTenant,
    loading,
    refreshTenants: fetchTenants,
  };

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
