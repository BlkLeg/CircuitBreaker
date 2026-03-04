/**
 * useDiscoveryStream()
 *
 * Establishes and maintains a single global WebSocket connection to
 * WS /api/v1/discovery/stream. Designed to be called once at the app
 * root level (App.jsx) so the connection persists across page navigation.
 *
 * Auth protocol:
 *   1. Connect to WS endpoint
 *   2. Immediately send the JWT token as the first text message (raw string)
 *   3. Wait for {"status": "connected"} confirmation
 *   4. Begin receiving events
 *
 * Client → server messages:
 *   {"type": "ping"}  — application-level keep-alive ping
 *
 * Server → client messages:
 *   {"type": "pong"}  — response to client ping
 *   {"type": "ping"}  — server-initiated keep-alive (no response needed, but
 *                        we send one anyway so both sides detect stale links)
 *
 * Reconnection:
 *   - On unexpected close: exponential backoff starting at 2s, max 30s
 *   - On auth failure (code 1008, error "unauthorized"): do NOT reconnect
 *   - On auth timeout (error "auth_timeout"): do NOT reconnect
 *   - On connection_limit_exceeded: do NOT reconnect immediately; wait 60s
 *   - On tab visibility change to visible: reconnect if disconnected
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import mitt from 'mitt';
import { getDiscoveryStatus } from '../api/discovery.js';

// Module-level emitter — survives React re-renders and component unmounts
export const discoveryEmitter = mitt();

const TOKEN_KEY = import.meta.env.VITE_TOKEN_STORAGE_KEY ?? 'cb_token';

const BACKOFF_BASE       = 2000;   // 2 seconds
const BACKOFF_MAX        = 30000;  // 30 seconds
const BACKOFF_MULTIPLIER = 1.5;
const CAP_RETRY_DELAY    = 60000;  // 60 seconds — wait longer when the cap is hit

// Errors that should not trigger an immediate reconnect loop.
const HARD_STOP_ERRORS = new Set(['unauthorized', 'auth_timeout']);

function getWsUrl() {
  const proto = globalThis.location.protocol === 'https:' ? 'wss' : 'ws';
  const host  = globalThis.location.host;
  return `${proto}://${host}/api/v1/discovery/stream`;
}

export function useDiscoveryStream() {
  const [connected, setConnected]       = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  const wsRef             = useRef(null);
  const attemptRef        = useRef(0);
  const retryTimerRef     = useRef(null);
  const intentionalRef    = useRef(false);  // true when we closed on purpose (auth fail)

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    clearRetry();

    // Don't open a second socket if one is already open/connecting
    if (wsRef.current &&
        (wsRef.current.readyState === WebSocket.OPEN ||
         wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      // No token — wait for auth; will reconnect on visibility change
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

      // ── Auth / connection handshake ──────────────────────────────────
      if (msg.status === 'connected') {
        setConnected(true);
        attemptRef.current = 0;
        return;
      }

      // Hard-stop errors — token is invalid or timed out: do NOT retry.
      if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
        setConnected(false);
        intentionalRef.current = true;
        ws.close();
        return;
      }

      // Connection cap hit — back off for longer before retrying.
      if (msg.error === 'connection_limit_exceeded') {
        setConnected(false);
        intentionalRef.current = false;  // allow retry after delay
        ws.close();
        retryTimerRef.current = setTimeout(() => {
          attemptRef.current = 0;
          connect();
        }, CAP_RETRY_DELAY);
        return;
      }

      // ── Keep-alive ───────────────────────────────────────────────────
      // Server sends {"type":"ping"} every 30 s; respond with a pong so
      // both ends can detect stale connections.
      if (msg.type === 'ping') {
        try {
          ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          // socket may have closed between the message and the send
        }
        return;
      }

      // Server pong in response to our ping — no-op, connection is alive.
      if (msg.type === 'pong') {
        discoveryEmitter.emit('ws:pong', { ts: msg.ts });
        return;
      }

      // ── Domain events ────────────────────────────────────────────────
      switch (msg.type) {
        case 'job_update':
          discoveryEmitter.emit('job:update', msg.job);
          break;
        case 'job_progress':
          discoveryEmitter.emit('job:progress', {
            job_id: msg.job_id,
            phase: msg.phase,
            message: msg.message,
            percent: msg.percent,
            processed: msg.processed,
            total: msg.total,
          });
          break;
        case 'result_added':
          discoveryEmitter.emit('result:added', msg.result);
          setPendingCount((c) => c + 1);
          break;
        default:
          break;
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      wsRef.current = null;

      // Auth failure / intentional close — hard stop
      if (event.code === 1008 || intentionalRef.current) {
        return;
      }

      // cap retry already scheduled above — don't double-schedule
      if (retryTimerRef.current) return;

      // Exponential backoff reconnect
      const attempt = attemptRef.current;
      const delay   = Math.min(
        BACKOFF_BASE * Math.pow(BACKOFF_MULTIPLIER, attempt),
        BACKOFF_MAX
      );
      attemptRef.current = attempt + 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose fires after onerror — reconnect logic lives there
      ws.close();
    };
  }, [clearRetry]);

  // Mount: connect and set up visibility listener
  useEffect(() => {
    connect();

    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !intentionalRef.current) {
        const ws = wsRef.current;
        const isActive = ws &&
          (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING);
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

  // Keep pendingCount in sync with the status endpoint on mount
  useEffect(() => {
    getDiscoveryStatus()
      .then((res) => {
        if (typeof res.data?.pending_results === 'number') {
          setPendingCount(res.data.pending_results);
        }
      })
      .catch(() => {});
  }, []);

  // Badge refresh: re-fetch count whenever something emits 'badge:refresh'
  useEffect(() => {
    const onBadgeRefresh = () => {
      getDiscoveryStatus()
        .then((res) => {
          if (typeof res.data?.pending_results === 'number') {
            setPendingCount(res.data.pending_results);
          }
        })
        .catch(() => {});
    };
    discoveryEmitter.on('badge:refresh', onBadgeRefresh);
    return () => discoveryEmitter.off('badge:refresh', onBadgeRefresh);
  }, []);

  return { connected, pendingCount, setPendingCount };
}
