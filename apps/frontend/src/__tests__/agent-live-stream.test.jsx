import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useAgentLive } from '../hooks/useAgentLive.js';

// A stable object reference for `user`, matching real AuthContext where the
// value comes from useState (stable across re-renders unless it truly
// changes) — a fresh literal here would churn useAgentLive's `connect`
// useCallback identity on every render and thrash the socket.
const mockUser = { id: 1 };
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser, token: 'a-real-bearer-token-value' }),
}));

class MockWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = WebSocket.CONNECTING;
    this.sent = [];
    this.listeners = new Map();
    MockWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close() {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code: 1000 });
  }
  addEventListener(event, callback) {
    const callbacks = this.listeners.get(event) || [];
    callbacks.push(callback);
    this.listeners.set(event, callbacks);
  }
  open() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
    (this.listeners.get('open') || []).forEach((cb) => cb());
    this.listeners.set('open', []);
  }
  emit(data) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe('useAgentLive', () => {
  let originalWebSocket;

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket;
    MockWebSocket.instances = [];
    globalThis.WebSocket = MockWebSocket;
    globalThis.WebSocket.OPEN = 1;
    globalThis.WebSocket.CONNECTING = 0;
    globalThis.WebSocket.CLOSED = 3;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
  });

  it('sends the bearer token on open and marks connected on ack', async () => {
    const { result } = renderHook(() => useAgentLive());
    const ws = MockWebSocket.instances[0];

    act(() => ws.open());
    expect(ws.sent).toEqual(['a-real-bearer-token-value']);

    act(() => ws.emit({ status: 'connected' }));
    await waitFor(() => expect(result.current.connected).toBe(true));
  });

  it('folds an agent_id event into statuses', async () => {
    const { result } = renderHook(() => useAgentLive());
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.emit({ status: 'connected' }));

    act(() => ws.emit({ agent_id: 7, event_type: 'connected', detail: null }));

    await waitFor(() => {
      expect(result.current.statuses.get(7)?.event_type).toBe('connected');
    });
  });

  it('hard-stops on unauthorized without scheduling a reconnect', async () => {
    const { result } = renderHook(() => useAgentLive());
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());

    act(() => ws.emit({ error: 'unauthorized' }));

    await waitFor(() => expect(result.current.connected).toBe(false));
    expect(MockWebSocket.instances.length).toBe(1); // no reconnect attempt was made
  });
});
