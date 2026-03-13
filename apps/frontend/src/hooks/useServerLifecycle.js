import { useState, useEffect, useRef, useCallback } from 'react';
import {
  HEALTH_POLL_INTERVAL_READY_MS,
  HEALTH_POLL_INTERVAL_STARTING_MS,
  HEALTH_POLL_INTERVAL_STOPPING_MS,
  HEALTH_POLL_INTERVAL_OFFLINE_MS,
  HEALTH_REQUEST_TIMEOUT_MS,
} from '../lib/constants.js';

const POLL_INTERVALS = {
  ready: HEALTH_POLL_INTERVAL_READY_MS,
  starting: HEALTH_POLL_INTERVAL_STARTING_MS,
  stopping: HEALTH_POLL_INTERVAL_STOPPING_MS,
  offline: HEALTH_POLL_INTERVAL_OFFLINE_MS,
};

function getPollInterval(state) {
  if (state === 'ready') return POLL_INTERVALS.ready;
  if (state === 'starting') return POLL_INTERVALS.starting;
  if (state === 'stopping') return POLL_INTERVALS.stopping;
  return POLL_INTERVALS.offline;
}

async function fetchHealth() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HEALTH_REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch('/api/v1/health', { signal: controller.signal });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null; // timeout, refused, or network error → offline
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Polls /api/v1/health with adaptive intervals based on server state.
 * Uses raw fetch (not axios) to avoid the axios retry/intercept layer.
 *
 * Returns:
 *   state          — "starting" | "ready" | "stopping" | "offline"
 *   previousState  — previous state value (null on first render)
 *   isReady        — true only when state === "ready"
 *   isTransitioning — true when starting or stopping
 *   checks         — { db, redis } from last health response, or null
 *   offlineSince   — timestamp (ms) when offline started, or null
 */
export function useServerLifecycle() {
  const [state, setState] = useState('starting');
  const [previousState, setPreviousState] = useState(null);
  const [checks, setChecks] = useState(null);
  const [offlineSince, setOfflineSince] = useState(null);

  const timerRef = useRef(null);
  const currentState = useRef('starting');

  const scheduleNext = useCallback((nextState) => {
    if (timerRef.current) clearTimeout(timerRef.current);

    timerRef.current = setTimeout(async () => {
      const health = await fetchHealth();
      const resolved = health?.state ?? 'offline';

      if (resolved !== currentState.current) {
        setPreviousState(currentState.current);
        currentState.current = resolved;
        setState(resolved);

        if (resolved === 'offline') {
          setOfflineSince(Date.now());
        } else {
          setOfflineSince(null);
        }
      }

      if (health?.checks) setChecks(health.checks);

      scheduleNext(resolved);
    }, getPollInterval(nextState));
  }, []);

  useEffect(() => {
    scheduleNext('starting');
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [scheduleNext]);

  return {
    state,
    previousState,
    isReady: state === 'ready',
    isTransitioning: state === 'starting' || state === 'stopping',
    checks,
    offlineSince,
  };
}
