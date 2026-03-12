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
        setNodes(applyTelemetryUpdate(nodesRef.current, nodeId, { data: msg.data ?? msg }));
      }
    };
    telemetryEmitter.on('telemetry:any', onTelemetry);
    return () => telemetryEmitter.off('telemetry:any', onTelemetry);
  }, [setNodes, nodesRef, unmountedRef, telemetryConnected]);

  // Fallback: telemetry polling with exponential backoff (only when WS telemetry is NOT connected)
  useEffect(() => {
    if (telemetryConnected) return;

    // Per-node error tracking: nodeId → { count, pausedUntil }
    const errorCounters = {};
    // Nodes that returned "unconfigured" — skip permanently
    const unconfiguredNodes = new Set();
    let pollInterval = 60_000;
    let timer = null;

    const doPoll = () => {
      if (unmountedRef?.current) return;
      const now = Date.now();
      const liveHwNodes = nodesRef.current.filter(
        (n) =>
          n.originalType === 'hardware' &&
          n.data.telemetry_status &&
          n.data.telemetry_status !== 'unknown' &&
          !unconfiguredNodes.has(n.id)
      );
      let hadErrors = false;
      liveHwNodes.forEach(async (n) => {
        // Skip nodes paused due to consecutive failures (5-minute cooldown)
        const counter = errorCounters[n.id];
        if (counter && counter.count >= 3 && now < counter.pausedUntil) return;

        try {
          const res = await telemetryApi.get(n._refId);
          if (unmountedRef?.current) return;

          // Skip unconfigured nodes permanently
          if (res?.status === 'unconfigured') {
            unconfiguredNodes.add(n.id);
            return;
          }

          // Success — reset error counter
          delete errorCounters[n.id];
          setNodes(applyTelemetryUpdate(nodesRef.current, n.id, res));
        } catch (err) {
          hadErrors = true;
          const status = err?.statusCode || err?.response?.status;
          if (!errorCounters[n.id]) errorCounters[n.id] = { count: 0, pausedUntil: 0 };
          errorCounters[n.id].count += 1;

          // After 3 consecutive failures, pause polling this node for 5 minutes
          if (errorCounters[n.id].count >= 3) {
            errorCounters[n.id].pausedUntil = now + 5 * 60 * 1000;
          }

          // On 500/503 — mark node as telemetry_unavailable
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
      });

      // Exponential backoff on errors: increase interval up to 30s cap
      if (hadErrors) {
        pollInterval = Math.min(pollInterval * 1.5, 30_000);
      } else {
        pollInterval = 60_000; // Reset to normal on success
      }
      timer = setTimeout(doPoll, pollInterval);
    };

    timer = setTimeout(doPoll, pollInterval);
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
