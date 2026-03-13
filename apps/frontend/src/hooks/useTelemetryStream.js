/**
 * useTelemetryStream()
 *
 * Establishes a WebSocket to WS /api/v1/telemetry/stream for real-time
 * telemetry push via Redis pub/sub.  Clients send subscribe/unsubscribe
 * messages to control which entity channels they receive.
 *
 * Auth protocol is identical to useDiscoveryStream (JWT as first message).
 *
 * Falls back to no-op when Redis is unavailable on the backend — the WS
 * stays open but receives no events; callers should keep interval-based
 * polling as a safety net.
 *
 * Usage:
 *   const { data, connected } = useTelemetryStream({ entityIds: [5, 12] });
 *   // data is Map<entityId, latestTelemetryPayload>
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import mitt from 'mitt';
import { useAuth } from '../context/AuthContext.jsx';

export const telemetryEmitter = mitt();

const BACKOFF_BASE = 2000;
const BACKOFF_MAX = 30000;
const BACKOFF_MULTIPLIER = 1.5;

const HARD_STOP_ERRORS = new Set(['unauthorized', 'auth_timeout']);

export function getTelemetryWsUrl(locationLike = globalThis.location) {
  const proto = locationLike.protocol === 'https:' ? 'wss' : 'ws';
  const host = locationLike.host;
  return `${proto}://${host}/api/v1/telemetry/stream`;
}

export function useTelemetryStream({ entityIds = [] } = {}) {
  const { user, token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [data, setData] = useState(() => new Map());

  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef(null);
  const intentionalRef = useRef(false);
  const entityIdsRef = useRef(entityIds);
  entityIdsRef.current = entityIds;

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const sendSubscriptions = useCallback((ws, ids) => {
    if (ws?.readyState === WebSocket.OPEN && ids.length > 0) {
      ws.send(JSON.stringify({ subscribe: ids }));
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

    if (!user && !token) return;

    const ws = new WebSocket(getTelemetryWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      if (token && token !== 'cookie' && token.length > 10) {
        ws.send(token);
      }
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
        sendSubscriptions(ws, entityIdsRef.current);
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
        ws.close();
        retryTimerRef.current = setTimeout(() => {
          attemptRef.current = 0;
          connect();
        }, 60000);
        return;
      }

      if (msg.type === 'ping') {
        try {
          ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          /* socket may have closed */
        }
        return;
      }

      if (msg.type === 'pong') return;

      if (msg.type === 'telemetry' && msg.entity_id != null) {
        setData((prev) => {
          const next = new Map(prev);
          next.set(msg.entity_id, msg);
          return next;
        });
        telemetryEmitter.emit(`telemetry:${msg.entity_id}`, msg);
        telemetryEmitter.emit('telemetry:any', msg);
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      wsRef.current = null;

      if (event.code === 1008 || intentionalRef.current) return;
      if (retryTimerRef.current) return;

      const attempt = attemptRef.current;
      const baseDelay = Math.min(BACKOFF_BASE * Math.pow(BACKOFF_MULTIPLIER, attempt), BACKOFF_MAX);
      const delay = baseDelay * (0.5 + Math.random() * 0.5);
      attemptRef.current = attempt + 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => ws.close();
  }, [clearRetry, user, token, sendSubscriptions]);

  // Connect on mount, reconnect on visibility change
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

  // Re-subscribe when entityIds change
  useEffect(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN && entityIds.length > 0) {
      ws.send(JSON.stringify({ subscribe: entityIds }));
    }
  }, [entityIds.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, connected };
}
