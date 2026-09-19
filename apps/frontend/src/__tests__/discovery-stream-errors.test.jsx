import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// A stable object reference for `user` — a fresh literal on every render
// would churn useDiscoveryStream's `connect` useCallback identity (it
// depends on [clearRetry, user, token]) and thrash the socket between
// renders, the same trap noted in agent-live-stream.test.jsx.
const mockUser = { id: 1 };
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser, token: 'test-token-value-12345' }),
}));

vi.mock('../api/discovery.js', () => ({
  getDiscoveryStatus: vi.fn().mockResolvedValue({ data: { pending_results: 0, active_jobs: [] } }),
}));

import { useDiscoveryStream } from '../hooks/useDiscoveryStream.js';

const socketInstances = [];

// MockWebSocket models real browser close()/onclose semantics: calling
// close() moves readyState to CLOSING *synchronously* and returns; onclose
// is delivered *asynchronously*, as its own later task — never inline
// inside close(). (See MDN/WHATWG: close() only *starts* the closing
// handshake.)
//
// That ordering is load-bearing for useDiscoveryStream's connection_limit_exceeded
// handling: onmessage calls closeSocketSafely(ws) and *then*, on the very
// next line, assigns retryTimerRef.current = setTimeout(..., 60000). If
// onclose fired synchronously inside close() (as a naive mock would do), it
// would run *before* that assignment, see retryTimerRef.current still null,
// and schedule the ordinary ~2s backoff on top of the 60s one — inverting
// the intended behavior. Firing onclose asynchronously via setTimeout(0)
// reproduces the real ordering under vi.useFakeTimers(): the assignment
// always happens first, and onclose (once ticked) sees the ref already set.
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.send = vi.fn();
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.listeners = new Map();
    this.close = vi.fn(() => {
      if (this.readyState === MockWebSocket.CLOSING || this.readyState === MockWebSocket.CLOSED) {
        return;
      }
      this.readyState = MockWebSocket.CLOSING;
      setTimeout(() => {
        this.readyState = MockWebSocket.CLOSED;
        this.onclose?.({ code: 1000 });
      }, 0);
    });
    socketInstances.push(this);
  }

  addEventListener(event, callback) {
    const callbacks = this.listeners.get(event) || [];
    callbacks.push(callback);
    this.listeners.set(event, callbacks);
  }

  emitOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
    const callbacks = this.listeners.get('open') || [];
    callbacks.forEach((callback) => callback());
    this.listeners.set('open', []);
  }

  emitMessage(data) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  // Simulates the server/network dropping the connection out from under us
  // — a close event arriving that our own code did not initiate via
  // close(). Delivered directly (not through the async close() path above)
  // because this models the close *event itself* arriving, not a call to
  // close() that we're waiting on.
  triggerServerClose(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

describe('useDiscoveryStream error paths', () => {
  beforeEach(() => {
    socketInstances.length = 0;
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  describe('hard-stop errors never reconnect', () => {
    it.each(['unauthorized', 'auth_timeout'])(
      'closes intentionally on "%s" and never opens a new socket, even 120s later',
      async (errorCode) => {
        renderHook(() => useDiscoveryStream());
        const ws = socketInstances[0];

        act(() => ws.emitOpen());
        act(() => ws.emitMessage({ error: errorCode }));

        // The hard-stop path must close the socket itself.
        expect(ws.close).toHaveBeenCalledTimes(1);

        // Let the (asynchronous, browser-accurate) onclose actually run.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(1);
        });

        // Advance well past BACKOFF_MAX (30s) and CAP_RETRY_DELAY (60s) —
        // if a reconnect were ever going to be scheduled, it would have
        // fired by now.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(120_000);
        });

        expect(socketInstances.length).toBe(1); // no reconnect was ever scheduled
      }
    );

    it('control: an ordinary close with no prior error DOES reconnect', async () => {
      renderHook(() => useDiscoveryStream());
      const ws = socketInstances[0];

      act(() => ws.emitOpen());
      // No error message at all — just an unexpected drop of the socket.
      act(() => ws.triggerServerClose(1000));

      // Ordinary backoff is BACKOFF_BASE (2000ms) with 50-100% jitter, so
      // slightly over 2000ms is guaranteed to have fired it.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_001);
      });

      expect(socketInstances.length).toBe(2); // a reconnect socket was opened
    });
  });

  it('backs off ~60s (not the ordinary ~2s) after connection_limit_exceeded', async () => {
    renderHook(() => useDiscoveryStream());
    const ws = socketInstances[0];

    act(() => ws.emitOpen());
    act(() => ws.emitMessage({ error: 'connection_limit_exceeded' }));

    expect(ws.close).toHaveBeenCalledTimes(1);

    // Flush the (asynchronous) onclose triggered by that close() call.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    // Still well short of the 60s cap-retry delay.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(socketInstances.length).toBe(1);

    // Cross the 60s boundary (jitter-free, unlike the ordinary backoff).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(socketInstances.length).toBe(2);
  });

  describe('onerror defensively closes the socket', () => {
    it('closes immediately when the socket is OPEN', () => {
      renderHook(() => useDiscoveryStream());
      const ws = socketInstances[0];

      act(() => ws.emitOpen());
      act(() => ws.onerror());

      expect(ws.close).toHaveBeenCalledTimes(1);
    });

    it('defers close until open when the socket is still CONNECTING', () => {
      renderHook(() => useDiscoveryStream());
      const ws = socketInstances[0];

      expect(ws.readyState).toBe(MockWebSocket.CONNECTING);
      act(() => ws.onerror());

      expect(ws.close).not.toHaveBeenCalled();

      act(() => ws.emitOpen());

      expect(ws.close).toHaveBeenCalledTimes(1);
    });
  });
});
