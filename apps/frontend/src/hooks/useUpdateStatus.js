import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../api/client.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { isAdmin } from '../utils/rbac';

const REFRESH_MS = 60 * 60 * 1000;

/**
 * The cached update verdict. Admin-only: the endpoint is admin-scoped, so a
 * viewer must not call it and take a 403 on every page load.
 */
export function useUpdateStatus() {
  const { user } = useAuth();
  const allowed = isAdmin(user);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(allowed);

  const load = useCallback(async () => {
    if (!allowed) return;
    try {
      const resp = await adminApi.updateStatus();
      setStatus(resp?.data ?? null);
    } catch {
      setStatus(null); // an unreachable endpoint is not an update claim
    } finally {
      setLoading(false);
    }
  }, [allowed]);

  useEffect(() => {
    if (!allowed) {
      setStatus(null);
      setLoading(false);
      return undefined;
    }
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [allowed, load]);

  return { status, loading };
}

export default useUpdateStatus;
