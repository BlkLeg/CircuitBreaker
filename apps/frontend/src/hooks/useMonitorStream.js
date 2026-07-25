/**
 * useMonitorStream()
 *
 * Establishes a WebSocket to WS /api/v1/monitors/stream for real-time monitor
 * status push via Redis pub/sub.  Clients send subscribe/unsubscribe messages
 * to control which monitor channels they receive.
 *
 * Auth protocol is identical to useTelemetryStream (JWT as first message).
 *
 * Falls back to no-op when Redis is unavailable on the backend — the WS stays
 * open but receives no events; callers should keep interval-based polling as a
 * safety net.
 *
 * Usage:
 *   const { statuses, connected } = useMonitorStream({ monitorIds: [5, 12] });
 *   // statuses is Map<monitorId, { status, msg, ts }>
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import mitt from 'mitt';
import { useAuth } from '../context/AuthContext.jsx';

export const monitorStatusEmitter = mitt();

const BACKOFF_BASE = 2000;
const BACKOFF_MAX = 30000;
const BACKOFF_MULTIPLIER = 1.5;

const HARD_STOP_ERRORS = new Set(['unauthorized', 'auth_timeout']);

function closeSocketSafely(socket) {
  if (!socket) return;
  if (socket.readyState === WebSocket.CONNECTING) {
    socket.addEventListener(
      'open',
      () => {
        try {
          socket.close();
        } catch {
          // Ignore late-close failures during teardown.
        }
      },
      { once: true }
    );
    return;
  }
  if (socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
}

export function getMonitorsWsUrl(locationLike = globalThis.location) {
  const proto = locationLike.protocol === 'https:' ? 'wss' : 'ws';
  const host = locationLike.host;
  return `${proto}://${host}/api/v1/monitors/stream`;
}

export function useMonitorStream({ monitorIds = [] } = {}) {
  const { user, token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [statuses, setStatuses] = useState(() => new Map());

  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef(null);
  const intentionalRef = useRef(false);
  const handshakeCompleteRef = useRef(false);
  const monitorIdsRef = useRef(monitorIds);
  monitorIdsRef.current = monitorIds;

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
    intentionalRef.current = false;

    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    if (!user && !token) return;

    const ws = new WebSocket(getMonitorsWsUrl());
    wsRef.current = ws;
    handshakeCompleteRef.current = false;

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
        handshakeCompleteRef.current = true;
        sendSubscriptions(ws, monitorIdsRef.current);
        return;
      }

      if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
        setConnected(false);
        intentionalRef.current = true;
        closeSocketSafely(ws);
        return;
      }

      if (msg.error === 'connection_limit_exceeded') {
        setConnected(false);
        intentionalRef.current = false;
        closeSocketSafely(ws);
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

      if (msg.type === 'monitor_status' && msg.monitor_id != null) {
        setStatuses((prev) => {
          const next = new Map(prev);
          next.set(msg.monitor_id, msg);
          return next;
        });
        monitorStatusEmitter.emit(`monitor:${msg.monitor_id}`, msg);
        monitorStatusEmitter.emit('monitor:any', msg);
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

    ws.onerror = () => {
      // Defensive: explicitly ensure onclose fires even if browser doesn't trigger it.
      // This covers pre-handshake errors where the close chain may be unreliable.
      if (wsRef.current === ws && ws.readyState !== WebSocket.CLOSED) {
        closeSocketSafely(ws);
      }
    };
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
      handshakeCompleteRef.current = false;
      closeSocketSafely(wsRef.current);
    };
  }, [connect, clearRetry]);

  // Re-subscribe when monitorIds change
  useEffect(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN && monitorIds.length > 0) {
      ws.send(JSON.stringify({ subscribe: monitorIds }));
    }
  }, [monitorIds.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  return { statuses, connected };
}
