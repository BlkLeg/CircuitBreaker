import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: { id: 1 },
    token: 'test-token-value-12345',
  }),
}));

vi.mock('../api/discovery.js', () => ({
  getDiscoveryStatus: vi.fn().mockResolvedValue({ data: { pending_results: 0, active_jobs: [] } }),
}));

import { useTopologyStream } from '../hooks/useTopologyStream';
import { useTelemetryStream } from '../hooks/useTelemetryStream';
import { useDiscoveryStream } from '../hooks/useDiscoveryStream';

const socketInstances = [];

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.close = vi.fn(() => {
      this.readyState = MockWebSocket.CLOSED;
      this.onclose?.({ code: 1000 });
    });
    this.send = vi.fn();
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.listeners = new Map();
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
}

function assertSafeCloseOnUnmount(useHook) {
  const { unmount } = renderHook(() => useHook());
  expect(socketInstances.length).toBeGreaterThan(0);

  const socket = socketInstances[socketInstances.length - 1];
  expect(socket.readyState).toBe(MockWebSocket.CONNECTING);

  unmount();

  expect(socket.close).not.toHaveBeenCalled();

  socket.emitOpen();
  expect(socket.close).toHaveBeenCalledTimes(1);
}

describe('stream hooks safe close behavior', () => {
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

  it('defers close until open in topology stream cleanup', () => {
    assertSafeCloseOnUnmount(useTopologyStream);
  });

  it('defers close until open in telemetry stream cleanup', () => {
    assertSafeCloseOnUnmount(() => useTelemetryStream({ entityIds: [] }));
  });

  it('defers close until open in discovery stream cleanup', () => {
    assertSafeCloseOnUnmount(useDiscoveryStream);
  });
});
