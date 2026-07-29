/**
 * useAgentLive()
 *
 * WS /api/v1/agents/stream — real-time agent presence push (connected,
 * disconnected, approved, rejected, revoked). Auth protocol identical to
 * useMonitorStream: cookie-mode sessions authenticate via the cookie the
 * browser attaches automatically; bearer-token sessions send the token as
 * the first text message after connecting.
 *
 * Usage:
 *   const { statuses, connected } = useAgentLive();
 *   // statuses is Map<agentId, { event_type, detail, ts }>
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext.jsx';

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

export function getAgentsWsUrl(locationLike = globalThis.location) {
  const proto = locationLike.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${locationLike.host}/api/v1/agents/stream`;
}

export function useAgentLive() {
  const { user, token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [statuses, setStatuses] = useState(() => new Map());

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
    intentionalRef.current = false;

    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    if (!user && !token) return;

    const ws = new WebSocket(getAgentsWsUrl());
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

      if (msg.agent_id != null && msg.event_type) {
        setStatuses((prev) => {
          const next = new Map(prev);
          next.set(msg.agent_id, {
            event_type: msg.event_type,
            detail: msg.detail,
            ts: Date.now(),
          });
          return next;
        });
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
      if (wsRef.current === ws && ws.readyState !== WebSocket.CLOSED) {
        closeSocketSafely(ws);
      }
    };
  }, [clearRetry, user, token]);

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
      closeSocketSafely(wsRef.current);
    };
  }, [connect, clearRetry]);

  return { statuses, connected };
}
