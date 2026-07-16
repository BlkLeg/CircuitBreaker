import { useEffect, useState } from 'react';
import { getDiscoveryReadiness } from '../api/discovery';

// Module-level cache so multiple hook instances share one fetch
const _cache = { data: null, ts: 0 };
const TTL_MS = 30_000;

/**
 * Returns discovery readiness state including helper installation status and per-capability health.
 *
 * Shape:
 *   { helper_installed: boolean, capabilities: [...] }
 *
 * Returns null while loading.
 */
export function useDiscoveryReadiness() {
  const [readiness, setReadiness] = useState(_cache.data);
  const [loading, setLoading] = useState(!_cache.data);

  useEffect(() => {
    if (_cache.data && Date.now() - _cache.ts < TTL_MS) {
      setReadiness(_cache.data);
      setLoading(false);
      return;
    }
    getDiscoveryReadiness()
      .then((res) => {
        _cache.data = res.data;
        _cache.ts = Date.now();
        setReadiness(res.data);
      })
      .catch(() => {
        // Backend unavailable — return safe fallback shape
        const fallback = {
          helper_installed: false,
          capabilities: [],
        };
        setReadiness(fallback);
      })
      .finally(() => setLoading(false));
  }, []);

  return { readiness, loading };
}
