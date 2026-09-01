import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  telemetryApi: { get: vi.fn(), getBatch: vi.fn() },
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

function makeHwNode(refId) {
  return {
    id: `hw-${refId}`,
    _refId: refId,
    originalType: 'hardware',
    data: { telemetry_status: 'unknown' },
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
    telemetryApi.getBatch.mockResolvedValue({ 101: { status: 'healthy', data: { cpu_pct: 10 } } });
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

    expect(telemetryApi.getBatch).not.toHaveBeenCalled();
  });

  it('stops polling nodes that return unconfigured status', async () => {
    telemetryApi.getBatch.mockResolvedValue({ 101: { status: 'unconfigured', data: {} } });
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

    expect(telemetryApi.getBatch).toHaveBeenCalledTimes(1);
  });

  it('issues ONE batched request for 12 due nodes on the first tick, not 12', async () => {
    const nodesRef = { current: Array.from({ length: 12 }, (_, i) => makeHwNode(100 + i)) };
    telemetryApi.getBatch.mockResolvedValue(
      Object.fromEntries(
        nodesRef.current.map((n) => [n._refId, { status: 'healthy', data: { cpu_pct: 5 } }])
      )
    );
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef,
        unmountedRef: { current: false },
        telemetryConnected: false,
      })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(telemetryApi.getBatch).toHaveBeenCalledTimes(1);
    expect(telemetryApi.getBatch).toHaveBeenCalledWith(nodesRef.current.map((n) => n._refId));
  });

  it('chunks a due set larger than the batch cap into multiple requests', async () => {
    const nodesRef = { current: Array.from({ length: 120 }, (_, i) => makeHwNode(1000 + i)) };
    telemetryApi.getBatch.mockResolvedValue({});
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef,
        unmountedRef: { current: false },
        telemetryConnected: false,
      })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    // 120 nodes at a 50-id cap => 3 chunks (50, 50, 20).
    expect(telemetryApi.getBatch).toHaveBeenCalledTimes(3);
    const chunkSizes = telemetryApi.getBatch.mock.calls.map((c) => c[0].length);
    expect(chunkSizes).toEqual([50, 50, 20]);
  });

  it('backs off every node in a failed batch, and pauses each after 3 consecutive failures', async () => {
    const nodesRef = { current: [makeHwNode(201), makeHwNode(202)] };
    telemetryApi.getBatch.mockRejectedValue(Object.assign(new Error('boom'), { statusCode: 502 }));
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef,
        unmountedRef: { current: false },
        telemetryConnected: false,
      })
    );

    // Ticks are every 5s; BASE_DELAY backoff after 1 failure is 30s scaled by
    // 1.5, so advancing well past 3 failed cycles is enough to accumulate 3
    // consecutive failures per node without the 5-minute pause suppressing
    // further batch calls first.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000); // failure 1 (backoff ~45s)
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50_000); // failure 2 (backoff ~67.5s)
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(70_000); // failure 3 -> pause
    });

    expect(telemetryApi.getBatch).toHaveBeenCalledTimes(3);
    telemetryApi.getBatch.mockClear();

    // Both nodes should now be paused for 5 minutes — no further calls even
    // after their backoff would otherwise have elapsed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(telemetryApi.getBatch).not.toHaveBeenCalled();

    // status >= 500 marks both nodes offline in the UI, same as the pre-batch
    // per-node error path did.
    const offlineCalls = setNodes.mock.calls.filter(([updater]) => typeof updater === 'function');
    expect(offlineCalls.length).toBeGreaterThan(0);
  });

  it('reschedules a node omitted from a successful batch response without incrementing its errors', async () => {
    const nodesRef = { current: [makeHwNode(301), makeHwNode(302)] };
    // 301 comes back, 302 is omitted (not authorized / not found / etc.).
    telemetryApi.getBatch.mockResolvedValue({
      301: { status: 'healthy', data: { cpu_pct: 1 } },
    });
    const setNodes = vi.fn();

    renderHook(() =>
      useMapRealTimeUpdates({
        setNodes,
        nodesRef,
        unmountedRef: { current: false },
        telemetryConnected: false,
      })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(telemetryApi.getBatch).toHaveBeenCalledTimes(1);

    // Both nodes are rescheduled at BASE_DELAY (30s), not paused or backed
    // off — the omitted node (302) took no error, so at t=35s both are due
    // again on the next 5s tick, producing a second call requesting both ids.
    telemetryApi.getBatch.mockResolvedValue({});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(telemetryApi.getBatch).toHaveBeenCalledTimes(2);
    const secondCallIds = telemetryApi.getBatch.mock.calls[1][0];
    expect(secondCallIds.sort()).toEqual([301, 302]);
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
