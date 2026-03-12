import { useEffect, useState } from 'react';
import { telemetryApi } from '../api/client';
import { listMonitors } from '../api/monitor';
import { discoveryEmitter } from './useDiscoveryStream';
import { telemetryEmitter } from './useTelemetryStream';
import { getPendingResults } from '../api/discovery';
import { applyTelemetryUpdate, applyMonitorUpdates } from '../utils/mapDataUtils';

/**
 * Manages real-time updates for the topology map.
 *
 * When Redis-backed telemetry streaming is available (via `useTelemetryStream`),
 * live telemetry pushes arrive through the `telemetryEmitter` and are applied
 * immediately to nodes — eliminating the 60 s polling interval.
 *
 * Falls back to interval polling when the telemetry WebSocket is not connected.
 *
 * @param {{ setNodes: Function, nodesRef: object, unmountedRef?: { current: boolean }, telemetryConnected?: boolean }} params
 * @returns {{ pendingDiscoveries: number, setPendingDiscoveries: Function }}
 */
export function useMapRealTimeUpdates({
  setNodes,
  nodesRef,
  unmountedRef,
  telemetryConnected = false,
}) {
  const [pendingDiscoveries, setPendingDiscoveries] = useState(0);

  // Pending discoveries badge
  useEffect(() => {
    getPendingResults({ limit: 1 })
      .then((r) => {
        if (!unmountedRef?.current) setPendingDiscoveries(r.data?.total ?? 0);
      })
      .catch((err) => {
        console.warn('Pending discoveries fetch failed:', err);
      });
    const onAdded = () => {
      if (!unmountedRef?.current) setPendingDiscoveries((c) => c + 1);
    };
    discoveryEmitter.on('result:added', onAdded);
    return () => discoveryEmitter.off('result:added', onAdded);
  }, [unmountedRef]);

  // Real-time telemetry via Redis push (replaces 60 s polling when connected)
  useEffect(() => {
    if (!telemetryConnected) return;

    const onTelemetry = (msg) => {
      if (unmountedRef?.current || !msg?.entity_id) return;
      const nodeId = nodesRef.current.find(
        (n) => n.originalType === 'hardware' && n._refId === msg.entity_id
      )?.id;
      if (nodeId) {
        setNodes(
          applyTelemetryUpdate(nodesRef.current, nodeId, {
            status: msg.status,
            data: msg.data ?? msg,
            last_polled: msg.last_polled ?? null,
          })
        );
      }
    };
    telemetryEmitter.on('telemetry:any', onTelemetry);
    return () => telemetryEmitter.off('telemetry:any', onTelemetry);
  }, [setNodes, nodesRef, unmountedRef, telemetryConnected]);

  // Fallback: telemetry polling with exponential backoff (only when WS telemetry is NOT connected)
  useEffect(() => {
    if (telemetryConnected) return;

    const BASE_DELAY = 30_000;
    const MAX_DELAY = 300_000;
    const LOOP_DELAY = 5_000;
    const PAUSE_AFTER_ERRORS = 3;
    const PAUSE_WINDOW = 5 * 60 * 1000;

    // Node-level state
    const nextPollAt = {};
    const backoffByNode = {};
    const errorCounts = {};
    const pausedUntil = {};
    const unconfiguredNodes = new Set();

    let timer = null;

    const doPoll = async () => {
      if (unmountedRef?.current) return;
      const now = Date.now();
      const liveHwNodes = nodesRef.current.filter(
        (n) =>
          n.originalType === 'hardware' &&
          Number.isInteger(n._refId) &&
          !unconfiguredNodes.has(n.id)
      );

      const dueNodes = liveHwNodes.filter((node) => {
        if ((pausedUntil[node.id] ?? 0) > now) return false;
        if ((nextPollAt[node.id] ?? 0) > now) return false;
        return true;
      });

      await Promise.allSettled(
        dueNodes.map(async (n) => {
          try {
            const res = await telemetryApi.get(n._refId);
            if (unmountedRef?.current) return;

            if (res?.status === 'unconfigured') {
              unconfiguredNodes.add(n.id);
              return;
            }

            errorCounts[n.id] = 0;
            backoffByNode[n.id] = BASE_DELAY;
            nextPollAt[n.id] = Date.now() + BASE_DELAY;
            setNodes(applyTelemetryUpdate(nodesRef.current, n.id, res));
          } catch (err) {
            const status = err?.statusCode || err?.response?.status;
            const currentBackoff = backoffByNode[n.id] ?? BASE_DELAY;
            const nextBackoff = Math.min(Math.round(currentBackoff * 1.5), MAX_DELAY);
            backoffByNode[n.id] = nextBackoff;
            nextPollAt[n.id] = Date.now() + nextBackoff;
            errorCounts[n.id] = (errorCounts[n.id] ?? 0) + 1;

            if (errorCounts[n.id] >= PAUSE_AFTER_ERRORS) {
              pausedUntil[n.id] = Date.now() + PAUSE_WINDOW;
            }

            if (status >= 500 && !unmountedRef?.current) {
              setNodes((prev) =>
                prev.map((node) =>
                  node.id === n.id
                    ? { ...node, data: { ...node.data, telemetry_status: 'offline' } }
                    : node
                )
              );
            }
            console.warn('Telemetry polling failed for node', n.id, err);
          }
        })
      );

      timer = setTimeout(doPoll, LOOP_DELAY);
    };

    timer = setTimeout(doPoll, LOOP_DELAY);
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [setNodes, nodesRef, unmountedRef, telemetryConnected]);

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
      } catch (err) {
        console.warn('Monitor polling failed:', err);
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [setNodes, nodesRef, unmountedRef]);

  return { pendingDiscoveries, setPendingDiscoveries };
}
