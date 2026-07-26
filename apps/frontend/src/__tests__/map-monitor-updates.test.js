import { describe, expect, it } from 'vitest';
import { applyMonitorUpdates } from '../utils/mapDataUtils';

const rows = [
  {
    target_type: 'hardware',
    target_id: 1,
    monitor_id: 11,
    monitor_ids: [11],
    enabled: true,
    status: 'up',
    latency_ms: 4.2,
    uptime_pct_24h: 99.9,
    last_polled_at: '2026-07-26T00:00:00Z',
  },
  {
    target_type: 'service',
    target_id: 3,
    monitor_id: 13,
    monitor_ids: [13],
    enabled: false,
    status: 'down',
    latency_ms: null,
    uptime_pct_24h: 12,
    last_polled_at: null,
  },
  {
    target_type: 'external_node',
    target_id: 4,
    monitor_id: 14,
    monitor_ids: [14],
    enabled: true,
    status: 'pending',
    latency_ms: null,
    uptime_pct_24h: null,
    last_polled_at: null,
  },
];

const nodes = () => [
  { id: 'hw-1', _refId: 1, originalType: 'hardware', data: {} },
  { id: 'cu-2', _refId: 2, originalType: 'compute', data: {} },
  { id: 'svc-3', _refId: 3, originalType: 'service', data: {} },
  { id: 'ext-4', _refId: 4, originalType: 'external', data: {} },
  { id: 'net-5', _refId: 5, originalType: 'network', data: {} },
];

describe('applyMonitorUpdates', () => {
  it('folds rollups onto each monitorable node type', () => {
    const updated = applyMonitorUpdates(nodes(), rows);
    const byId = Object.fromEntries(updated.map((n) => [n.id, n.data]));

    expect(byId['hw-1']).toMatchObject({
      monitor_id: 11,
      monitor_status: 'up',
      monitor_enabled: true,
      monitor_latency_ms: 4.2,
      monitor_last_checked_at: '2026-07-26T00:00:00Z',
    });
    expect(byId['svc-3']).toMatchObject({ monitor_status: 'down', monitor_enabled: false });
    expect(byId['ext-4']).toMatchObject({ monitor_id: 14, monitor_status: 'pending' });
  });

  it('leaves unmonitored and non-monitorable nodes untouched', () => {
    const input = nodes();
    const updated = applyMonitorUpdates(input, rows);
    // cu-2 has no rollup row, net-5 cannot be monitored at all.
    expect(updated.find((n) => n.id === 'cu-2')).toBe(input[1]);
    expect(updated.find((n) => n.id === 'net-5')).toBe(input[4]);
  });

  it('clears a stale badge when monitoring is removed elsewhere', () => {
    const input = [
      {
        id: 'hw-1',
        _refId: 1,
        originalType: 'hardware',
        data: { monitor_id: 11, monitor_status: 'up' },
      },
    ];
    const [node] = applyMonitorUpdates(input, []);
    expect(node.data.monitor_id).toBeNull();
    expect(node.data.monitor_status).toBeNull();
  });
});
