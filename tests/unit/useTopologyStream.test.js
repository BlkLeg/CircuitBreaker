/**
 * Tests for useTopologyStream.js — topology WebSocket hook.
 *
 * Tests the topologyEmitter event bus and hook behavior. WebSocket integration
 * is covered by E2E or manual verification since mocking the browser WebSocket
 * in Vitest is fragile (module load order, global stubbing).
 */
import { describe, it, expect, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const { useTopologyStream, topologyEmitter } = await import('../hooks/useTopologyStream.js');

describe('useTopologyStream', () => {
  afterEach(() => {
    topologyEmitter.all.clear();
  });

  it('returns connected state (initially false)', () => {
    const { result } = renderHook(() => useTopologyStream());
    expect(typeof result.current.connected).toBe('boolean');
    expect(result.current.connected).toBe(false);
  });

  it('topologyEmitter emits topology:node_moved', () => {
    const received = [];
    const handler = (d) => received.push(d);
    topologyEmitter.on('topology:node_moved', handler);

    topologyEmitter.emit('topology:node_moved', {
      layout_name: 'default',
      layout_data: '{}',
    });

    expect(received).toHaveLength(1);
    expect(received[0].layout_name).toBe('default');

    topologyEmitter.off('topology:node_moved', handler);
  });

  it('topologyEmitter emits topology:cable_added', () => {
    const received = [];
    const handler = (d) => received.push(d);
    topologyEmitter.on('topology:cable_added', handler);

    topologyEmitter.emit('topology:cable_added', {
      source_id: 'hw-1',
      target_id: 'hw-2',
      connection_type: 'ethernet',
    });

    expect(received).toHaveLength(1);
    expect(received[0].source_id).toBe('hw-1');

    topologyEmitter.off('topology:cable_added', handler);
  });

  it('topologyEmitter emits topology:cable_removed', () => {
    const received = [];
    const handler = (d) => received.push(d);
    topologyEmitter.on('topology:cable_removed', handler);

    topologyEmitter.emit('topology:cable_removed', {
      source_id: 'hw-1',
      target_id: 'hw-2',
      connection_id: 7,
    });

    expect(received[0].connection_id).toBe(7);

    topologyEmitter.off('topology:cable_removed', handler);
  });

  it('topologyEmitter emits topology:node_status_changed', () => {
    const received = [];
    const handler = (d) => received.push(d);
    topologyEmitter.on('topology:node_status_changed', handler);

    topologyEmitter.emit('topology:node_status_changed', {
      node_id: 'hw-1',
      node_type: 'hardware',
      status: 'online',
    });

    expect(received).toHaveLength(1);
    expect(received[0].status).toBe('online');

    topologyEmitter.off('topology:node_status_changed', handler);
  });
});
