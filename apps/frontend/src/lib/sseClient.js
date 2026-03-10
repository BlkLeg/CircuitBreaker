/**
 * sseClient — singleton Server-Sent Events manager.
 *
 * Provides a shared EventSource connection to GET /api/v1/events/stream
 * with automatic reconnection using exponential backoff.  Multiple React
 * components subscribe to specific event types via the module-level emitter.
 *
 * Usage:
 *   import { sseEmitter, connectSSE, disconnectSSE } from '../lib/sseClient';
 *   sseEmitter.on('notification', handler);
 *   sseEmitter.on('alert', handler);
 *   sseEmitter.on('discovery', handler);
 *   sseEmitter.on('sse:status', ({ connected, transport }) => { ... });
 *
 * The SSE connection is started once when the app mounts (App.jsx calls
 * connectSSE()) and is torn down on unmount.
 */

import mitt from 'mitt';

export const sseEmitter = mitt();

const SSE_URL = '/api/v1/events/stream';
const BACKOFF_BASE = 2000;
const BACKOFF_MAX = 30000;
const BACKOFF_MULTIPLIER = 1.5;

let _es = null;
let _attempt = 0;
let _retryTimer = null;
let _intentionalClose = false;
let _connected = false;

// Module-scope reference so removeEventListener can match the exact same function.
function _onVisibility() {
  if (document.visibilityState === 'visible' && !_intentionalClose) {
    if (!_es || _es.readyState === EventSource.CLOSED) {
      _attempt = 0;
      _connect();
    }
  }
}

function _clearRetry() {
  if (_retryTimer) {
    clearTimeout(_retryTimer);
    _retryTimer = null;
  }
}

function _setConnected(val, transport = 'unknown') {
  _connected = val;
  sseEmitter.emit('sse:status', { connected: val, transport });
}

function _connect() {
  _clearRetry();

  if (_es && (_es.readyState === EventSource.OPEN || _es.readyState === EventSource.CONNECTING)) {
    return;
  }

  const es = new EventSource(SSE_URL);
  _es = es;

  es.onopen = () => {
    _attempt = 0;
    _setConnected(true, 'sse');
  };

  // Named event types — mirrors the server "event: <type>" lines
  for (const eventType of ['notification', 'alert', 'discovery']) {
    es.addEventListener(eventType, (e) => {
      try {
        const data = JSON.parse(e.data);
        sseEmitter.emit(eventType, data);
      } catch {
        // Malformed JSON — ignore
      }
    });
  }

  es.onerror = () => {
    _setConnected(false);
    es.close();
    _es = null;

    if (_intentionalClose) return;
    if (_retryTimer) return;

    const baseDelay = Math.min(BACKOFF_BASE * Math.pow(BACKOFF_MULTIPLIER, _attempt), BACKOFF_MAX);
    const delay = baseDelay * (0.5 + Math.random() * 0.5); // Add jitter (50% to 100% of base)
    _attempt += 1;
    _retryTimer = setTimeout(_connect, delay);
  };
}

/**
 * Start the SSE connection. Call once at app root.
 * Safe to call multiple times — no-op if already connected.
 */
export function connectSSE() {
  _intentionalClose = false;
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', _onVisibility);
    document.addEventListener('visibilitychange', _onVisibility);
  }
  _connect();
}

/**
 * Tear down the SSE connection. Called on app unmount.
 */
export function disconnectSSE() {
  _intentionalClose = true;
  _clearRetry();
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', _onVisibility);
  }
  if (_es) {
    _es.close();
    _es = null;
  }
  _setConnected(false);
}

/** Returns current connection state for one-shot reads. */
export function isSSEConnected() {
  return _connected;
}
