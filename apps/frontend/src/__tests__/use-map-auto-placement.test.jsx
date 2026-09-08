/**
 * Auto-placement coordinator.
 *
 * New nodes arrive at (0,0) marked `_needsAutoPlace`; the drain effect asks the
 * server where to put each one. The behaviour worth pinning is the bookkeeping
 * around that call: the optimistic mark that stops a concurrent fetch queueing
 * a second placement, the circuit breaker that stops a failing backend looping
 * forever, and saving exactly once per completed batch.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useMapAutoPlacement } from '../features/map/hooks/useMapAutoPlacement';
import { graphApi } from '../api/client';

vi.mock('../api/client', () => ({ graphApi: { placeNode: vi.fn() } }));

function makeArgs(over = {}) {
  return {
    envFilter: null,
    setNodes: vi.fn(),
    autoPlacedIdsRef: { current: new Set() },
    placingNodesRef: { current: new Set() },
    pendingPlacementCountRef: { current: 0 },
    batchPlacedCountRef: { current: 0 },
    saveLayoutRef: { current: vi.fn().mockResolvedValue(undefined) },
    fitView: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  graphApi.placeNode.mockResolvedValue({ data: { x: 10, y: 20 } });
});

describe('useMapAutoPlacement', () => {
  it('marks the node placed before awaiting the server', async () => {
    const args = makeArgs();
    let resolve;
    graphApi.placeNode.mockImplementation(
      () => new Promise((r) => (resolve = () => r({ data: { x: 1, y: 2 } })))
    );
    const { result } = renderHook(() => useMapAutoPlacement(args));

    let pending;
    act(() => {
      pending = result.current.autoPlaceNew('n1');
    });

    // Optimistic: a fetchData landing mid-flight must not re-queue this node.
    expect(args.autoPlacedIdsRef.current.has('n1')).toBe(true);
    await act(async () => {
      resolve();
      await pending;
    });
  });

  it('positions the node from the server response', async () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapAutoPlacement(args));

    await act(async () => {
      await result.current.autoPlaceNew('n1');
    });

    const updater = args.setNodes.mock.calls.at(-1)[0];
    const out = updater([{ id: 'n1', position: { x: 0, y: 0 }, _needsAutoPlace: true }]);
    expect(out[0]._needsAutoPlace).toBe(false);
  });

  it('unmarks the node and still positions it when placement fails', async () => {
    graphApi.placeNode.mockRejectedValue(new Error('unreachable'));
    const args = makeArgs();
    const { result } = renderHook(() => useMapAutoPlacement(args));

    await act(async () => {
      await result.current.autoPlaceNew('n1');
    });

    // Circuit breaker: clearing the flag with a fallback position is what stops
    // the drain effect re-triggering forever against a down backend.
    expect(args.autoPlacedIdsRef.current.has('n1')).toBe(false);
    expect(args.setNodes).toHaveBeenCalled();
  });

  it('saves once for a batch, not once per node', async () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapAutoPlacement(args));

    await act(async () => {
      await Promise.all([
        result.current.autoPlaceNew('n1'),
        result.current.autoPlaceNew('n2'),
        result.current.autoPlaceNew('n3'),
      ]);
    });

    await waitFor(() => expect(args.saveLayoutRef.current).toHaveBeenCalledTimes(1));
    expect(args.toast.success).toHaveBeenCalledTimes(1);
    expect(args.toast.success).toHaveBeenCalledWith(
      '3 nodes auto-placed',
      expect.objectContaining({ toastId: 'auto-place-batch' })
    );
  });

  it('uses the singular message for a single node', async () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapAutoPlacement(args));

    await act(async () => {
      await result.current.autoPlaceNew('n1');
    });

    await waitFor(() =>
      expect(args.toast.success).toHaveBeenCalledWith('Node auto-placed', expect.anything())
    );
  });

  it('does not save when every placement in the batch failed', async () => {
    graphApi.placeNode.mockRejectedValue(new Error('unreachable'));
    const args = makeArgs();
    const { result } = renderHook(() => useMapAutoPlacement(args));

    await act(async () => {
      await result.current.autoPlaceNew('n1');
    });

    expect(args.saveLayoutRef.current).not.toHaveBeenCalled();
    expect(args.toast.success).not.toHaveBeenCalled();
  });
});
