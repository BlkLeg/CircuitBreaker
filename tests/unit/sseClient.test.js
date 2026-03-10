/**
 * Tests for sseClient.js — singleton SSE manager.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock EventSource before importing sseClient
class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  constructor(url) {
    this.url = url;
    this.readyState = MockEventSource.CONNECTING;
    this._handlers = {};
    MockEventSource._instances.push(this);
  }

  addEventListener(type, fn) {
    this._handlers[type] = fn;
  }

  removeEventListener(type) {
    delete this._handlers[type];
  }

  close() {
    this.readyState = MockEventSource.CLOSED;
  }

  _triggerOpen() {
    this.readyState = MockEventSource.OPEN;
    if (this.onopen) this.onopen();
  }

  _triggerError() {
    this.readyState = MockEventSource.CLOSED;
    if (this.onerror) this.onerror(new Event('error'));
  }

  _triggerEvent(type, data) {
    const fn = this._handlers[type];
    if (fn) fn(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}
MockEventSource._instances = [];

globalThis.EventSource = MockEventSource;

// Import after setting up mock
const { sseEmitter, connectSSE, disconnectSSE, isSSEConnected } = await import('../lib/sseClient.js');

describe('sseClient', () => {
  beforeEach(() => {
    MockEventSource._instances = [];
    disconnectSSE();
    vi.useFakeTimers();
  });

  afterEach(() => {
    disconnectSSE();
    vi.useRealTimers();
  });

  it('connectSSE creates an EventSource', () => {
    connectSSE();
    expect(MockEventSource._instances).toHaveLength(1);
  });

  it('emits sse:status connected=true on open', () => {
    const statuses = [];
    const handler = (s) => statuses.push(s);
    sseEmitter.on('sse:status', handler);

    connectSSE();
    const es = MockEventSource._instances[0];
    es._triggerOpen();

    expect(statuses).toContainEqual(expect.objectContaining({ connected: true }));
    sseEmitter.off('sse:status', handler);
  });

  it('emits sse:status connected=false on error', () => {
    const statuses = [];
    const handler = (s) => statuses.push(s);
    sseEmitter.on('sse:status', handler);

    connectSSE();
    const es = MockEventSource._instances[0];
    es._triggerError();

    expect(statuses.some((s) => s.connected === false)).toBe(true);
    sseEmitter.off('sse:status', handler);
  });

  it('reconnects with backoff after error', () => {
    connectSSE();
    const es = MockEventSource._instances[0];
    es._triggerError();

    // After backoff delay, a new EventSource should be created
    vi.advanceTimersByTime(3000);
    expect(MockEventSource._instances).toHaveLength(2);
  });

  it('disconnectSSE stops reconnect and marks disconnected', () => {
    connectSSE();
    const es = MockEventSource._instances[0];
    es._triggerError();

    disconnectSSE();
    vi.advanceTimersByTime(10000);

    // No new instances created after intentional disconnect
    expect(MockEventSource._instances).toHaveLength(1);
    expect(isSSEConnected()).toBe(false);
  });

  it('emits typed events from the event stream', () => {
    const received = [];
    const handler = (d) => received.push(d);
    sseEmitter.on('notification', handler);

    connectSSE();
    const es = MockEventSource._instances[0];
    es._triggerOpen();
    es._triggerEvent('notification', { action: 'hardware_created', entity_id: 5 });

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({ entity_id: 5 });

    sseEmitter.off('notification', handler);
  });

  it('does not create duplicate connections on multiple connectSSE calls', () => {
    connectSSE();
    const es = MockEventSource._instances[0];
    es.readyState = MockEventSource.OPEN;

    connectSSE(); // second call — should be no-op
    expect(MockEventSource._instances).toHaveLength(1);
  });
});
