import { useEffect, useState } from 'react';
import { telemetryApi } from '../api/client';
import { listMonitors } from '../api/monitor';
import { discoveryEmitter } from './useDiscoveryStream';
import { getPendingResults } from '../api/discovery';
import { applyTelemetryUpdate, applyMonitorUpdates } from '../utils/mapDataUtils';

/**
 * Manages real-time updates for the topology map:
 *  - telemetry polling (every 60 s)
 *  - monitor status polling (every 60 s)
 *  - discovery result badge via discoveryEmitter
 *
 * @param {{ setNodes: Function, nodesRef: object, unmountedRef?: { current: boolean } }} params
 * @returns {{ pendingDiscoveries: number, setPendingDiscoveries: Function }}
 */
export function useMapRealTimeUpdates({ setNodes, nodesRef, unmountedRef }) {
  const [pendingDiscoveries, setPendingDiscoveries] = useState(0);

  // Pending discoveries badge
  useEffect(() => {
    getPendingResults({ limit: 1 })
      .then((r) => {
        if (!unmountedRef?.current) setPendingDiscoveries(r.data?.total ?? 0);
      })
      .catch(() => {});
    const onAdded = () => {
      if (!unmountedRef?.current) setPendingDiscoveries((c) => c + 1);
    };
    discoveryEmitter.on('result:added', onAdded);
    return () => discoveryEmitter.off('result:added', onAdded);
  }, [unmountedRef]);

  // Telemetry polling — refresh every 60 s for hardware nodes with active telemetry
  useEffect(() => {
    const interval = setInterval(() => {
      if (unmountedRef?.current) return;
      const liveHwNodes = nodesRef.current.filter(
        (n) =>
          n.originalType === 'hardware' &&
          n.data.telemetry_status &&
          n.data.telemetry_status !== 'unknown'
      );
      liveHwNodes.forEach(async (n) => {
        try {
          const res = await telemetryApi.get(n._refId);
          if (!unmountedRef?.current) {
            setNodes(applyTelemetryUpdate(nodesRef.current, n.id, res));
          }
        } catch {
          /* silent — connection may be unavailable */
        }
      });
    }, 60_000);
    return () => clearInterval(interval);
  }, [setNodes, nodesRef, unmountedRef]);

  // Monitor polling — refresh every 60 s so node latency badges and sidebar stay live
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        if (unmountedRef?.current) return;
        const res = await listMonitors();
        if (unmountedRef?.current) return;
        const monitors = Array.isArray(res?.data) ? res.data : Array.isArray(res) ? res : [];
        setNodes((prev) =>
          applyMonitorUpdates(nodesRef.current.length ? nodesRef.current : prev, monitors)
        );
      } catch {
        /* silent */
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [setNodes, nodesRef, unmountedRef]);

  return { pendingDiscoveries, setPendingDiscoveries };
}
