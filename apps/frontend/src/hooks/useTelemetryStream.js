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
 *   // data.get(entity)               -> latest `telemetry`/`telemetry.host` message
 *   // data.get(`readiness:${entity}`) -> latest `capability.readiness` message
 *
 * `entity` is `msg.entity_id` for hardware channels and `agent:<id>` for the
 * agent channel.  Keys are namespaced by message kind, never shared: a
 * `telemetry:agent:{id}` channel carries several unrelated message types and
 * a shared slot would let one overwrite another.  **Any new message type
 * added to this channel gets its own `<kind>:<entity>` key** — that is the
 * rule slice 3's probe statuses and slice 4's discovery statuses follow.
 *
 * Consumers that *index* `data` are unaffected when a new kind appears;
 * consumers that *iterate* it must filter on the key prefix.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import mitt from 'mitt';
import { useAuth } from '../context/AuthContext.jsx';

export const telemetryEmitter = mitt();

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

export function getTelemetryWsUrl(locationLike = globalThis.location) {
  const proto = locationLike.protocol === 'https:' ? 'wss' : 'ws';
  const host = locationLike.host;
  return `${proto}://${host}/api/v1/telemetry/stream`;
}

export function useTelemetryStream({ entityIds = [], entities = [] } = {}) {
  const { user, token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [data, setData] = useState(() => new Map());

  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef(null);
  const intentionalRef = useRef(false);
  const handshakeCompleteRef = useRef(false);
  const subscriptions = entities.length > 0 ? entities : entityIds;
  const entityIdsRef = useRef(subscriptions);
  entityIdsRef.current = subscriptions;

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

    const ws = new WebSocket(getTelemetryWsUrl());
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
        sendSubscriptions(ws, entityIdsRef.current);
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

      const key = msg.entity_id ?? (msg.agent_id != null ? `agent:${msg.agent_id}` : null);
      if (key == null) return;

      if (msg.type === 'telemetry' || msg.type === 'telemetry.host') {
        setData((prev) => {
          const next = new Map(prev);
          next.set(key, msg);
          return next;
        });
        telemetryEmitter.emit(`telemetry:${key}`, msg);
        telemetryEmitter.emit('telemetry:any', msg);
        return;
      }

      // Task 18: `capability.readiness` is broadcast on the same
      // telemetry:agent:{id} channel as the samples but is a *different*
      // shape, so it gets its own namespaced slot. Storing it under the bare
      // `key` would overwrite the latest sample and blank AgentDetailPage's
      // metric cards, which read `update.payload` from that slot.
      if (msg.type === 'capability.readiness') {
        setData((prev) => {
          const next = new Map(prev);
          next.set(`readiness:${key}`, msg);
          return next;
        });
        telemetryEmitter.emit(`readiness:${key}`, msg);
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

  // Re-subscribe when entityIds change
  useEffect(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN && subscriptions.length > 0) {
      ws.send(JSON.stringify({ subscribe: subscriptions }));
    }
  }, [JSON.stringify(subscriptions)]); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, connected };
}
