import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  telemetryApi: { get: vi.fn() },
}));

vi.mock('../api/monitor', () => ({
  listMonitors: vi.fn().mockResolvedValue({ data: [] }),
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
