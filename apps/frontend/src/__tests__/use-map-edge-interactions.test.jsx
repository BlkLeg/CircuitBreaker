/* eslint-disable security/detect-object-injection -- test helper mutates keyed fixture object */
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useMapEdgeInteractions } from '../hooks/useMapEdgeInteractions';

function makeArgs(overrides = {}) {
  return {
    setEdges: vi.fn(),
    setEdgeMenu: vi.fn(),
    setEdgeOverrides: vi.fn(),
    edgeOverridesRef: { current: {} },
    nodesRef: { current: [] },
    dirtyRef: { current: false },
    screenToFlowPosition: vi.fn((pos) => pos),
    normalizeConnectionType: vi.fn((value) => value),
    omitKey: vi.fn((obj, key) => {
      const next = { ...obj };
      delete next[key];
      return next;
    }),
    applyEdgeSidesForEdge: vi.fn((_nodes, edge) => edge),
    nodeCenterInFlow: vi.fn(() => ({ x: 0, y: 0 })),
    graphApi: {
      updateEdgeType: vi.fn(),
      topology: vi.fn().mockResolvedValue({ data: { edges: [] } }),
    },
    isUpdatableEdgeId: vi.fn(() => true),
    clampPickerPosition: vi.fn((x, y) => ({ x, y })),
    lastPointerRef: { current: { x: 42, y: 24 } },
    setPendingConnection: vi.fn(),
    pendingConnection: null,
    createLinkByNodeIds: vi.fn(),
    unlinkByEdge: vi.fn(),
    fetchData: vi.fn(),
    toast: { warn: vi.fn(), info: vi.fn(), error: vi.fn() },
    ...overrides,
  };
}

describe('useMapEdgeInteractions', () => {
  it('opens connection picker on connect', () => {
    const args = makeArgs();
    const { result } = renderHook(() => useMapEdgeInteractions(args));

    act(() => {
      result.current.handleConnect({ source: 'hw-1', target: 'hw-2' });
    });

    expect(args.setPendingConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: 'new',
        connection: { source: 'hw-1', target: 'hw-2' },
        x: 42,
        y: 24,
      })
    );
  });

  it('normalizes and persists edge type changes', async () => {
    const args = makeArgs({
      normalizeConnectionType: vi.fn(() => 'wg'),
    });
    const { result } = renderHook(() => useMapEdgeInteractions(args));

    await act(async () => {
      await result.current.handleEdgeConnectionTypeChange('e-dep-1', 'wireguard');
    });

    expect(args.setEdges).toHaveBeenCalled();
    expect(args.setEdgeMenu).toHaveBeenCalled();
    expect(args.graphApi.updateEdgeType).toHaveBeenCalledWith('e-dep-1', 'wg');
  });
});
