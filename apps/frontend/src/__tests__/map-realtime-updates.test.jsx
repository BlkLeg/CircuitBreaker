import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  telemetryApi: { get: vi.fn() },
}));

vi.mock('../api/monitor', () => ({
  getTargetSummary: vi.fn().mockResolvedValue({ data: [] }),
}));

vi.mock('../api/discovery', () => ({
  getPendingResults: vi.fn().mockResolvedValue({ data: { total: 0 } }),
}));

vi.mock('../hooks/useDiscoveryStream', () => ({
  discoveryEmitter: { on: vi.fn(), off: vi.fn() },
}));

vi.mock('../hooks/useTelemetryStream', () => ({
  telemetryEmitter: { on: vi.fn(), off: vi.fn() },
}));

import { telemetryApi } from '../api/client';
import { getTargetSummary } from '../api/monitor';
import { useMapRealTimeUpdates } from '../hooks/useMapRealTimeUpdates';

function makeNodesRef() {
  return {
    current: [
      { id: 'hw-1', _refId: 101, originalType: 'hardware', data: { telemetry_status: 'unknown' } },
    ],
  };
}

describe('useMapRealTimeUpdates telemetry fallback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not run HTTP polling while websocket telemetry is connected', async () => {
    telemetryApi.get.mockResolvedValue({ status: 'healthy', data: { cpu_pct: 10 } });
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef: makeNodesRef(),
        unmountedRef: { current: false },
        telemetryConnected: true,
      })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });

    expect(telemetryApi.get).not.toHaveBeenCalled();
  });

  it('stops polling nodes that return unconfigured status', async () => {
    telemetryApi.get.mockResolvedValue({ status: 'unconfigured', data: {} });
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef: makeNodesRef(),
        unmountedRef: { current: false },
        telemetryConnected: false,
      })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_000);
    });

    expect(telemetryApi.get).toHaveBeenCalledTimes(1);
  });
});

describe('useMapRealTimeUpdates monitor polling', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls the rollup for every monitorable target type and folds it onto nodes', async () => {
    getTargetSummary.mockImplementation((targetType) =>
      Promise.resolve({
        data:
          targetType === 'compute_unit'
            ? [
                {
                  target_type: 'compute_unit',
                  target_id: 202,
                  monitor_id: 9,
                  monitor_ids: [9],
                  enabled: true,
                  status: 'down',
                  latency_ms: null,
                  uptime_pct_24h: 80,
                  last_polled_at: null,
                },
              ]
            : [],
      })
    );
    const nodesRef = {
      current: [
        { id: 'hw-1', _refId: 101, originalType: 'hardware', data: {} },
        { id: 'cu-202', _refId: 202, originalType: 'compute', data: {} },
      ],
    };
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef,
        unmountedRef: { current: false },
        telemetryConnected: true,
      })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(getTargetSummary.mock.calls.map((c) => c[0])).toEqual([
      'hardware',
      'compute_unit',
      'service',
      'external_node',
    ]);

    const updated = setNodes.mock.calls.at(-1)[0](nodesRef.current);
    expect(updated.find((n) => n.id === 'cu-202').data).toMatchObject({
      monitor_id: 9,
      monitor_status: 'down',
      monitor_enabled: true,
      monitor_uptime_pct_24h: 80,
    });
    expect(updated.find((n) => n.id === 'hw-1').data.monitor_status).toBeUndefined();
  });
});
