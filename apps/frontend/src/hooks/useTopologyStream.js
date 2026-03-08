/**
 * useTopologyStream()
 *
 * Maintains a single global WebSocket connection to
 * WS /api/v1/topology/stream for live topology map / rack updates.
 *
 * Designed to be called once at the MapPage level (or app root) so the
 * connection persists while the map is open.
 *
 * Auth protocol (identical to useDiscoveryStream):
 *   1. Connect to WS endpoint
 *   2. Send the JWT token as the first text message (raw string)
 *   3. Wait for {"status": "connected"} confirmation
 *   4. Begin receiving events
 *
 * Server → client message types:
 *   {"type": "node_moved",          "layout_name": str, "layout_data": str}
 *   {"type": "cable_added",         "source_id": str, "target_id": str, "connection_type": str}
 *   {"type": "cable_removed",       "source_id": str, "target_id": str, "connection_id": int}
 *   {"type": "node_status_changed", "node_id": str, "node_type": str, "status": str}
 *   {"type": "ping",                "ts": str}
 *
 * Client → server messages:
 *   {"type": "ping"}
 *
 * The module-level `topologyEmitter` is a mitt event bus.  Components
 * subscribe to it directly rather than re-rendering through React state,
 * keeping topology updates off the React reconciler hot path.
 *
 * Reconnection:
 *   - Exponential backoff: 2 s base, ×1.5, max 30 s
 *   - Hard stop on auth failure (1008 / "unauthorized" / "auth_timeout")
 *   - 60 s delay on connection_limit_exceeded
 *   - Reconnects on tab visibility change to visible
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import mitt from 'mitt';

export const topologyEmitter = mitt();

const TOKEN_KEY = import.meta.env.VITE_TOKEN_STORAGE_KEY ?? 'cb_token';

const BACKOFF_BASE = 2000;
const BACKOFF_MAX = 30000;
const BACKOFF_MULTIPLIER = 1.5;
const CAP_RETRY_DELAY = 60000;

const HARD_STOP_ERRORS = new Set(['unauthorized', 'auth_timeout']);

function getWsUrl() {
  const proto = globalThis.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = globalThis.location.host;
  return `${proto}://${host}/api/v1/topology/stream`;
}

export function useTopologyStream() {
  const [connected, setConnected] = useState(false);

  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef(null);
  const intentionalRef = useRef(false);

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    clearRetry();

    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      // No token — reconnect will be attempted on visibility change or next call
      return;
    }

    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(token);
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      if (msg.status === 'connected') {
        setConnected(true);
        attemptRef.current = 0;
        topologyEmitter.emit('ws:connected');
        return;
      }

      if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
        setConnected(false);
        intentionalRef.current = true;
        ws.close();
        return;
      }

      if (msg.error === 'connection_limit_exceeded') {
        setConnected(false);
        intentionalRef.current = false;
        ws.close();
        retryTimerRef.current = setTimeout(() => {
          attemptRef.current = 0;
          connect();
        }, CAP_RETRY_DELAY);
        return;
      }

      if (msg.type === 'ping') {
        try {
          ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          // socket may have closed
        }
        return;
      }

      if (msg.type === 'pong') {
        topologyEmitter.emit('ws:pong', { ts: msg.ts });
        return;
      }

      // Domain events — route to topologyEmitter
      const processEvent = (eventData) => {
        switch (eventData.type) {
          case 'node_moved':
            topologyEmitter.emit('topology:node_moved', {
              layout_name: eventData.layout_name,
              layout_data: eventData.layout_data,
            });
            break;
          case 'cable_added':
            topologyEmitter.emit('topology:cable_added', {
              source_id: eventData.source_id,
              target_id: eventData.target_id,
              connection_type: eventData.connection_type,
              bandwidth_mbps: eventData.bandwidth_mbps,
            });
            break;
          case 'cable_removed':
            topologyEmitter.emit('topology:cable_removed', {
              source_id: eventData.source_id,
              target_id: eventData.target_id,
              connection_id: eventData.connection_id,
            });
            break;
          case 'node_status_changed':
            topologyEmitter.emit('topology:node_status_changed', {
              node_id: eventData.node_id,
              node_type: eventData.node_type,
              status: eventData.status,
            });
            break;
          default:
            break;
        }
      };

      if (msg.type === 'batch') {
        msg.events.forEach(processEvent);
      } else {
        processEvent(msg);
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      wsRef.current = null;
      topologyEmitter.emit('ws:disconnected');

      if (event.code === 1008 || intentionalRef.current) return;
      if (retryTimerRef.current) return;

      const attempt = attemptRef.current;
      const delay = Math.min(BACKOFF_BASE * Math.pow(BACKOFF_MULTIPLIER, attempt), BACKOFF_MAX);
      attemptRef.current = attempt + 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [clearRetry]);

  useEffect(() => {
    connect();

    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !intentionalRef.current) {
        const ws = wsRef.current;
        const isActive =
          ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING);
        if (!isActive) {
          attemptRef.current = 0;
          connect();
        }
      }
    };

    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      clearRetry();
      intentionalRef.current = true;
      wsRef.current?.close();
    };
  }, [connect, clearRetry]);

  return { connected };
}
