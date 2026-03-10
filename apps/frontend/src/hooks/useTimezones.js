import { useState, useEffect } from 'react';
import { timezonesApi } from '../api/client.jsx';

// Module-level cache — shared across all component instances.
let _cache = null;
let _pending = null;

/**
 * Fetches GET /api/v1/timezones once per session and caches the result.
 * Returns { timezones: string[], loading: bool, error: string | null }
 */
export function useTimezones() {
  const [state, setState] = useState({
    timezones: _cache ?? [],
    loading: _cache === null,
    error: null,
  });

  useEffect(() => {
    if (_cache !== null) {
      setState({ timezones: _cache, loading: false, error: null });
      return;
    }

    if (!_pending) {
      _pending = timezonesApi
        .list()
        .then((res) => {
          _cache = res.data?.timezones ?? [];
          _pending = null;
          return _cache;
        })
        .catch((err) => {
          _pending = null;
          throw err;
        });
    }

    let cancelled = false;
    _pending
      .then((tzList) => {
        if (!cancelled) setState({ timezones: tzList, loading: false, error: null });
      })
      .catch((err) => {
        if (!cancelled)
          setState({
            timezones: [],
            loading: false,
            error: err.message ?? 'Failed to load timezones',
          });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
