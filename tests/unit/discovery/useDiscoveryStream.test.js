/**
 * useDiscoveryStream tests
 *
 * Uses a lightweight hand-rolled WebSocket mock so no real network is needed.
 * vi.stubGlobal is required because jsdom makes globalThis.WebSocket read-only.
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── WebSocket mock ────────────────────────────────────────────────
class MockWS {
  constructor(url) {
    this.url = url;
    this.readyState = MockWS.CONNECTING;
    this.sent = [];
    MockWS._instances.push(this);
  }
  send(data)  { this.sent.push(data); }
  close(code) { this.readyState = MockWS.CLOSED; this.onclose?.({ code: code ?? 1000 }); }
  _open()     { this.readyState = MockWS.OPEN; this.onopen?.({}); }
  _recv(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
}
MockWS.CONNECTING = 0;
MockWS.OPEN       = 1;
MockWS.CLOSING    = 2;
MockWS.CLOSED     = 3;
MockWS._instances = [];

const TOKEN_KEY   = 'cb_token';
const TOKEN_VALUE = 'test-jwt-token';

let mod;

beforeEach(async () => {
  MockWS._instances = [];
  vi.stubGlobal('WebSocket', MockWS);
  vi.stubEnv('VITE_TOKEN_STORAGE_KEY', TOKEN_KEY);
  localStorage.setItem(TOKEN_KEY, TOKEN_VALUE);
  vi.useFakeTimers();
  vi.resetModules();
  mod = await import('../../hooks/useDiscoveryStream.js');
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
});

async function setup() {
  const { result, unmount } = renderHook(() => mod.useDiscoveryStream());
  await act(async () => { await Promise.resolve(); });
  const ws = MockWS._instances[0];
  return { result, unmount, ws };
}

// ─────────────────────────────────────────────────────────────────

describe('useDiscoveryStream', () => {
  it('sends JWT as first message on connect', async () => {
    const { ws } = await setup();
    act(() => ws?._open());
    expect(ws?.sent[0]).toBe(TOKEN_VALUE);
  });

  it('sets connected=true on {"status":"connected"} message', async () => {
    const { result, ws } = await setup();
    act(() => ws?._open());
    act(() => ws?._recv({ status: 'connected' }));
    expect(result.current.connected).toBe(true);
  });

  it('sets connected=false on unauthorized and does not reconnect on 1008', async () => {
    const { result, ws } = await setup();
    act(() => ws?._open());
    act(() => ws?._recv({ error: 'unauthorized' }));
    act(() => ws?.close(1008));
    expect(result.current.connected).toBe(false);
    const countBefore = MockWS._instances.length;
    act(() => vi.advanceTimersByTime(35_000));
    expect(MockWS._instances.length).toBe(countBefore);
  });

  it('reconnects with backoff on unexpected close', async () => {
    const { ws } = await setup();
    act(() => ws?._open());
    act(() => ws?.close(1006));
    act(() => vi.advanceTimersByTime(3_000));
    expect(MockWS._instances.length).toBeGreaterThanOrEqual(2);
  });

  it('dispatches job:update event on job_update message', async () => {
    const listener = vi.fn();
    mod.discoveryEmitter.on('job:update', listener);
    const { ws } = await setup();
    act(() => ws?._open());
    act(() => ws?._recv({ status: 'connected' }));
    act(() => ws?._recv({ type: 'job_update', job: { id: 1, status: 'running' } }));
    expect(listener).toHaveBeenCalledWith({ id: 1, status: 'running' });
    mod.discoveryEmitter.off('job:update', listener);
  });

  it('dispatches result:added event and increments pendingCount', async () => {
    const listener = vi.fn();
    mod.discoveryEmitter.on('result:added', listener);
    const { result, ws } = await setup();
    act(() => ws?._open());
    act(() => ws?._recv({ status: 'connected' }));
    const before = result.current.pendingCount;
    act(() => ws?._recv({ type: 'result_added', result: { id: 5, ip_address: '10.0.0.5' } }));
    expect(listener).toHaveBeenCalledWith({ id: 5, ip_address: '10.0.0.5' });
    expect(result.current.pendingCount).toBe(before + 1);
    mod.discoveryEmitter.off('result:added', listener);
  });

  it('ignores ping messages — connected and count unchanged', async () => {
    const { result, ws } = await setup();
    act(() => ws?._open());
    act(() => ws?._recv({ status: 'connected' }));
    const before = result.current.pendingCount;
    act(() => ws?._recv({ type: 'ping' }));
    expect(result.current.pendingCount).toBe(before);
    expect(result.current.connected).toBe(true);
  });

  it('reconnects on tab visibilitychange when disconnected', async () => {
    const { ws } = await setup();
    act(() => ws?._open());
    act(() => ws?.close(1006));
    const countAfterClose = MockWS._instances.length;
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    act(() => vi.advanceTimersByTime(200));
    expect(MockWS._instances.length).toBeGreaterThan(countAfterClose);
  });
});
