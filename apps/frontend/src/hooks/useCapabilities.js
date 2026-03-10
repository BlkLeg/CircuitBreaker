import { useEffect, useState } from 'react';
import { capabilitiesApi } from '../api/client.jsx';

// Module-level cache so multiple hook instances share one fetch
const _cache = { data: null, ts: 0 };
const TTL_MS = 30_000;

/**
 * Returns capability flags for optional backend subsystems.
 *
 * Shape:
 *   { nats, realtime, cve, listener, docker, auth }
 *
 * Each subsystem object always has an `available` boolean.
 * Returns null while loading.
 */
export function useCapabilities() {
  const [caps, setCaps] = useState(_cache.data);
  const [loading, setLoading] = useState(!_cache.data);

  useEffect(() => {
    if (_cache.data && Date.now() - _cache.ts < TTL_MS) {
      setCaps(_cache.data);
      setLoading(false);
      return;
    }
    capabilitiesApi
      .get()
      .then((res) => {
        _cache.data = res.data;
        _cache.ts = Date.now();
        setCaps(res.data);
      })
      .catch(() => {
        // Backend unavailable — treat all as unavailable rather than crashing
        const fallback = {
          nats: { available: false },
          realtime: { available: false, transport: 'auto' },
          cve: { available: false, last_sync: null },
          listener: { available: false, mdns: false, ssdp: false },
          docker: { available: false, discovery_enabled: false },
          auth: { enabled: false },
        };
        setCaps(fallback);
      })
      .finally(() => setLoading(false));
  }, []);

  return { caps, loading };
}
