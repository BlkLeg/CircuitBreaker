import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Stable reference: a fresh object literal per render would churn the
// `connect` useCallback identity and thrash the socket (see
// agent-live-stream.test.jsx for the same note).
const mockUser = { id: 1 };
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser, token: 'a-real-bearer-token-value' }),
}));

import { useTelemetryStream, telemetryEmitter } from '../hooks/useTelemetryStream.js';

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

const HOST_SAMPLE = {
  type: 'telemetry.host',
  agent_id: 7,
  collected_at: '2026-08-06T10:00:00Z',
  payload: { summary: { cpu_pct: 12.5 }, status: 'ok' },
};

const READINESS = {
  type: 'capability.readiness',
  agent_id: 7,
  readiness: [
    {
      collector: 'host.core',
      state: 'degraded',
      reason: '/proc/stat unreadable',
      remediation: 'check agent permissions',
    },
  ],
};

function handshake(ws) {
  act(() => ws.open());
  act(() => ws.emit({ status: 'connected' }));
}

describe('useTelemetryStream', () => {
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
    telemetryEmitter.all.clear();
  });

  it('stores capability.readiness under a namespaced key without clobbering the latest sample', async () => {
    const { result } = renderHook(() =>
      useTelemetryStream({ entities: [{ entity_type: 'agent', entity_id: 7 }] })
    );
    const ws = MockWebSocket.instances[0];
    handshake(ws);

    const seen = [];
    telemetryEmitter.on('readiness:agent:7', (msg) => seen.push(msg));

    act(() => ws.emit(HOST_SAMPLE));
    await waitFor(() => expect(result.current.data.get('agent:7')).toBeTruthy());

    act(() => ws.emit(READINESS));
    await waitFor(() => expect(result.current.data.get('readiness:agent:7')).toBeTruthy());

    // The sample slot is untouched — AgentDetailPage reads `update.payload`
    // from it, so sharing the slot would blank the metric cards.
    expect(result.current.data.get('agent:7').payload).toEqual(HOST_SAMPLE.payload);
    expect(result.current.data.get('readiness:agent:7').readiness).toEqual(READINESS.readiness);
    expect(seen).toEqual([READINESS]);
  });

  it('does not emit readiness on the sample topic', async () => {
    const { result } = renderHook(() =>
      useTelemetryStream({ entities: [{ entity_type: 'agent', entity_id: 7 }] })
    );
    const ws = MockWebSocket.instances[0];
    handshake(ws);

    const samples = [];
    telemetryEmitter.on('telemetry:agent:7', (msg) => samples.push(msg));

    act(() => ws.emit(READINESS));
    await waitFor(() => expect(result.current.data.get('readiness:agent:7')).toBeTruthy());
    expect(samples).toEqual([]);
  });

  // ── Non-regression: the shared Hardware/map callers ───────────────────────

  it('subscribes with bare integers for entityIds callers', async () => {
    renderHook(() => useTelemetryStream({ entityIds: [5] }));
    const ws = MockWebSocket.instances[0];
    handshake(ws);

    await waitFor(() => expect(ws.sent).toContain(JSON.stringify({ subscribe: [5] })));
  });

  it('subscribes with the typed form for entities callers', async () => {
    renderHook(() => useTelemetryStream({ entities: [{ entity_type: 'agent', entity_id: 3 }] }));
    const ws = MockWebSocket.instances[0];
    handshake(ws);

    await waitFor(() =>
      expect(ws.sent).toContain(
        JSON.stringify({ subscribe: [{ entity_type: 'agent', entity_id: 3 }] })
      )
    );
  });

  it('still stores a plain telemetry message keyed by entity_id', async () => {
    const { result } = renderHook(() => useTelemetryStream({ entityIds: [5] }));
    const ws = MockWebSocket.instances[0];
    handshake(ws);

    const msg = { type: 'telemetry', entity_id: 5, payload: { cpu_pct: 3 } };
    act(() => ws.emit(msg));

    await waitFor(() => expect(result.current.data.get(5)).toEqual(msg));
  });
});
