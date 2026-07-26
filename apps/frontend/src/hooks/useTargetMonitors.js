/* eslint-disable security/detect-object-injection -- keys are entity ids from our API */
/**
 * useTargetMonitors()
 *
 * Monitor state for an inventory page, keyed by entity id. Loads the per-target
 * rollup from GET /monitors/target-summary, keeps it live off the shared
 * monitors WebSocket, and exposes the enable / pause / resume / check-now
 * actions the list pages and detail panels drive.
 *
 * Usage:
 *   const monitors = useTargetMonitors('compute_unit', items.map((i) => i.id));
 *   monitors.byId[row.id]  // { monitor_id, status, enabled, uptime_pct_24h, ... }
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createTargetMonitor,
  getTargetSummary,
  pauseTargetMonitor,
  resumeTargetMonitor,
  runTargetCheck,
} from '../api/monitor';
import { useMonitorStream } from './useMonitorStream';

const REFRESH_MS = 60000;

export function useTargetMonitors(targetType, ids = []) {
  const [byId, setById] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Ids arrive as a fresh array each render; key the effect off the contents.
  const idKey = ids.join(',');
  const hasIds = ids.length > 0;

  const refresh = useCallback(async () => {
    if (!targetType) return;
    try {
      const { data } = await getTargetSummary(targetType);
      setById(Object.fromEntries(data.map((row) => [row.target_id, row])));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [targetType]);

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!hasIds) {
      setLoading(false);
      return undefined;
    }
    refreshRef.current();
    const t = setInterval(() => refreshRef.current(), REFRESH_MS); // safety net under the WS push
    return () => clearInterval(t);
  }, [targetType, idKey, hasIds]);

  // Live push: subscribe to every monitor backing the targets on this page.
  const monitorIds = useMemo(
    () => Object.values(byId).flatMap((row) => row.monitor_ids || []),
    [byId]
  );
  const { statuses } = useMonitorStream({ monitorIds });

  // Fold live events onto the rollup — a target is down if any of its checks is.
  const live = useMemo(() => {
    if (statuses.size === 0) return byId;
    const next = {};
    for (const [targetId, row] of Object.entries(byId)) {
      const pushed = (row.monitor_ids || [])
        .map((mid) => statuses.get(mid)?.status)
        .filter(Boolean);
      if (pushed.length === 0) {
        next[targetId] = row;
        continue;
      }
      const status = pushed.includes('down') ? 'down' : pushed[0];
      next[targetId] = { ...row, status };
    }
    return next;
  }, [byId, statuses]);

  const act = useCallback(
    async (fn, targetId) => {
      const res = await fn(targetType, targetId);
      await refreshRef.current();
      return res;
    },
    [targetType]
  );

  const enable = useCallback(
    (targetId, body) => act((t, id) => createTargetMonitor(t, id, body), targetId),
    [act]
  );
  const pause = useCallback((targetId) => act(pauseTargetMonitor, targetId), [act]);
  const resume = useCallback((targetId) => act(resumeTargetMonitor, targetId), [act]);
  const checkNow = useCallback((targetId) => act(runTargetCheck, targetId), [act]);

  return { byId: live, loading, error, refresh, enable, pause, resume, checkNow };
}

export default useTargetMonitors;
