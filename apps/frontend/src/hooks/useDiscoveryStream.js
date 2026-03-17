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
import { useAuth } from '../context/AuthContext.jsx';

// Module-level emitter — survives React re-renders and component unmounts
export const discoveryEmitter = mitt();

const BACKOFF_BASE = 2000; // 2 seconds
const BACKOFF_MAX = 30000; // 30 seconds
const BACKOFF_MULTIPLIER = 1.5;
const CAP_RETRY_DELAY = 60000; // 60 seconds — wait longer when the cap is hit

// Errors that should not trigger an immediate reconnect loop.
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

export function getDiscoveryWsUrl(locationLike = globalThis.location) {
  const proto = locationLike.protocol === 'https:' ? 'wss' : 'ws';
  const host = locationLike.host;
  return `${proto}://${host}/api/v1/discovery/stream`;
}

function syncPendingCount(res, setPendingCount, actionsPendingRef) {
  if (typeof res.data?.pending_results !== 'number') return;
  const serverCount = res.data.pending_results;
  setPendingCount((currentCount) => {
    if (Math.abs(currentCount - serverCount) > 0) {
      console.debug(`Badge sync: frontend=${currentCount}, backend=${serverCount}`);
      actionsPendingRef.current.clear();
    }
    return serverCount;
  });
}

function reconcileOnReconnect(setPendingCount) {
  getDiscoveryStatus()
    .then((res) => {
      if (typeof res.data?.pending_results === 'number') {
        setPendingCount(res.data.pending_results);
      }
      discoveryEmitter.emit('ws:reconnected', { activeJobs: res.data?.active_jobs ?? [] });
    })
    .catch((err) => {
      console.error('Discovery reconcile on reconnect failed:', err);
    });
}

export function useDiscoveryStream() {
  const { user, token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [wsStatus, setWsStatus] = useState('connecting');

  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef(null);
  const intentionalRef = useRef(false); // true when we closed on purpose (auth fail)
  const syncTimerRef = useRef(null); // periodic sync timer
  const actionsPendingRef = useRef(new Set()); // track pending actions for optimistic updates
  const reconnectedRef = useRef(false); // true after the first successful connect
  const handshakeCompleteRef = useRef(false); // true once status:connected is received

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const clearSyncTimer = useCallback(() => {
    if (syncTimerRef.current) {
      clearInterval(syncTimerRef.current);
      syncTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    clearRetry();

    // Don't open a second socket if one is already open/connecting
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    if (!user && !token) {
      return;
    }

    const ws = new WebSocket(getDiscoveryWsUrl());
    wsRef.current = ws;
    handshakeCompleteRef.current = false;

    ws.onopen = () => {
      setWsStatus('connecting');
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

      // ── Auth / connection handshake ──────────────────────────────────
      if (msg.status === 'connected') {
        setConnected(true);
        setWsStatus('connected');
        attemptRef.current = 0;
        handshakeCompleteRef.current = true;
        // On reconnect (not the initial connect), reconcile pending count and job state
        if (reconnectedRef.current) reconcileOnReconnect(setPendingCount);
        reconnectedRef.current = true;
        return;
      }

      // Hard-stop errors — token is invalid or timed out: do NOT retry.
      if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
        setConnected(false);
        intentionalRef.current = true;
        closeSocketSafely(ws);
        return;
      }

      // Connection cap hit — back off for longer before retrying.
      if (msg.error === 'connection_limit_exceeded') {
        setConnected(false);
        intentionalRef.current = false; // allow retry after delay
        closeSocketSafely(ws);
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
            eta_seconds: msg.eta_seconds,
          });
          break;
        case 'scan_log_entry':
          discoveryEmitter.emit('scan:log_entry', {
            job_id: msg.job_id,
            log_id: msg.log_id,
            timestamp: msg.timestamp,
            level: msg.level,
            phase: msg.phase,
            message: msg.message,
            details: msg.details,
          });
          break;
        case 'result_added':
          discoveryEmitter.emit('result:added', msg.result);
          setPendingCount((c) => c + 1);
          break;
        case 'result_processed':
          // Server-side event when results are accepted/rejected
          discoveryEmitter.emit('result:processed', {
            result_id: msg.result_id,
            action: msg.action,
            pending_count: msg.pending_count,
          });
          // Use server count for accuracy, clear any pending optimistic updates
          if (typeof msg.pending_count === 'number') {
            setPendingCount(msg.pending_count);
            actionsPendingRef.current.clear();
          }
          break;
        case 'proxmox_scan_started':
          discoveryEmitter.emit('proxmox:started', { integration_id: msg.integration_id });
          break;
        case 'proxmox_scan_progress':
          discoveryEmitter.emit('proxmox:progress', {
            integration_id: msg.integration_id,
            phase: msg.phase,
            message: msg.message,
            percent: msg.percent,
          });
          break;
        case 'proxmox_scan_completed':
          discoveryEmitter.emit('proxmox:completed', {
            integration_id: msg.integration_id,
            nodes: msg.nodes,
            vms: msg.vms,
            cts: msg.cts,
            storage: msg.storage,
          });
          break;
        case 'proxmox_scan_failed':
          discoveryEmitter.emit('proxmox:failed', {
            integration_id: msg.integration_id,
            error: msg.error,
          });
          break;
        default:
          break;
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      setWsStatus('disconnected');
      wsRef.current = null;

      // Auth failure / intentional close — hard stop
      if (event.code === 1008 || intentionalRef.current) {
        return;
      }

      // cap retry already scheduled above — don't double-schedule
      if (retryTimerRef.current) return;

      // Exponential backoff reconnect with jitter
      const attempt = attemptRef.current;
      const baseDelay = Math.min(BACKOFF_BASE * Math.pow(BACKOFF_MULTIPLIER, attempt), BACKOFF_MAX);
      const delay = baseDelay * (0.5 + Math.random() * 0.5); // Add jitter (50% to 100% of base)
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
  }, [clearRetry, user, token]);

  // Mount: connect and set up visibility listener
  useEffect(() => {
    connect();

    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !intentionalRef.current) {
        const ws = wsRef.current;
        const isActive =
          ws &&
          (ws.readyState === WebSocket.OPEN ||
            (ws.readyState === WebSocket.CONNECTING && handshakeCompleteRef.current));
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
      clearSyncTimer();
      intentionalRef.current = true;
      handshakeCompleteRef.current = false;
      closeSocketSafely(wsRef.current);
    };
  }, [connect, clearRetry, clearSyncTimer]);

  // Keep pendingCount in sync with the status endpoint on mount
  useEffect(() => {
    getDiscoveryStatus()
      .then((res) => {
        if (typeof res.data?.pending_results === 'number') {
          setPendingCount(res.data.pending_results);
        }
      })
      .catch((err) => {
        console.error('Discovery pending count sync failed:', err);
      });
  }, []);

  // Badge refresh: re-fetch count whenever something emits 'badge:refresh'
  useEffect(() => {
    const onBadgeRefresh = () => {
      getDiscoveryStatus()
        .then((res) => {
          if (typeof res.data?.pending_results === 'number') {
            setPendingCount(res.data.pending_results);
            actionsPendingRef.current.clear();
          }
        })
        .catch((err) => {
          console.error('Badge refresh failed:', err);
        });
    };

    // Optimistic badge decrement for immediate UI feedback
    const onBadgeDecrement = (data) => {
      const { count = 1, actionId } = data || {};
      if (actionId && actionsPendingRef.current.has(actionId)) {
        return; // Already processed optimistically
      }
      if (actionId) {
        actionsPendingRef.current.add(actionId);
      }
      setPendingCount((c) => Math.max(0, c - count));
    };

    // Badge increment for bulk rejections or errors
    const onBadgeIncrement = (data) => {
      const { count = 1 } = data || {};
      setPendingCount((c) => c + count);
    };

    discoveryEmitter.on('badge:refresh', onBadgeRefresh);
    discoveryEmitter.on('badge:decrement', onBadgeDecrement);
    discoveryEmitter.on('badge:increment', onBadgeIncrement);

    return () => {
      discoveryEmitter.off('badge:refresh', onBadgeRefresh);
      discoveryEmitter.off('badge:decrement', onBadgeDecrement);
      discoveryEmitter.off('badge:increment', onBadgeIncrement);
    };
  }, []);

  // Periodic sync with backend to catch missed events (every 30 seconds when connected)
  useEffect(() => {
    if (connected) {
      syncTimerRef.current = setInterval(() => {
        getDiscoveryStatus()
          .then((res) => syncPendingCount(res, setPendingCount, actionsPendingRef))
          .catch((err) => {
            console.warn('Background pending count sync failed:', err);
          });
      }, 30000); // 30 second sync interval
    } else {
      clearSyncTimer();
    }

    return clearSyncTimer;
  }, [connected, clearSyncTimer]);

  return { connected, pendingCount, setPendingCount, wsStatus };
}
