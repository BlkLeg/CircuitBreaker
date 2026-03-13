import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMapNodeDragSnap } from '../hooks/useMapNodeDragSnap';

const mockSnapEdgesToNearestHandles = vi.fn((_movedNodeIds, _nodes, edges) => edges);

vi.mock('../utils/mapHandleHelpers', async () => {
  const actual = await vi.importActual('../utils/mapHandleHelpers');
  return {
    ...actual,
    snapEdgesToNearestHandles: (...args) => mockSnapEdgesToNearestHandles(...args),
  };
});

function makeNode(id, x, y) {
  return { id, position: { x, y }, positionAbsolute: { x, y }, width: 140, height: 140 };
}

function makeArgs(overrides = {}) {
  let edgesState = [
    { id: 'e-1', source: 'a', target: 'b', sourceHandle: 's-right', targetHandle: 't-left' },
    { id: 'e-2', source: 'a', target: 'c', sourceHandle: 's-bottom', targetHandle: 't-top' },
  ];

  const setEdges = vi.fn((updater) => {
    edgesState = typeof updater === 'function' ? updater(edgesState) : updater;
    return edgesState;
  });

  const args = {
    setEdges,
    dirtyRef: { current: false },
    edgeOverridesRef: { current: {} },
    nodesRef: { current: [makeNode('a', 0, 0), makeNode('b', 220, 0), makeNode('c', 0, 220)] },
    ...overrides,
  };

  return {
    args,
    setEdges,
    getEdges: () => edgesState,
  };
}

describe('useMapNodeDragSnap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSnapEdgesToNearestHandles.mockImplementation((_movedNodeIds, _nodes, edges) => edges);
  });

  it('does not snap edges on zero-delta drag stop', () => {
    const { args } = makeArgs();
    const { result } = renderHook(() => useMapNodeDragSnap(args));
    const stationary = makeNode('a', 0, 0);

    act(() => {
      result.current.handleNodeDragStart({}, stationary, [stationary]);
      result.current.handleNodeDragStop({}, stationary, [stationary]);
    });

    expect(mockSnapEdgesToNearestHandles).not.toHaveBeenCalled();
    expect(args.dirtyRef.current).toBe(false);
  });

  it('restores snapshot when snapping result loses edges', () => {
    const { args, getEdges } = makeArgs();
    const { result } = renderHook(() => useMapNodeDragSnap(args));
    const startNode = makeNode('a', 0, 0);
    const movedNode = makeNode('a', 120, 60);

    mockSnapEdgesToNearestHandles.mockImplementationOnce((_movedNodeIds, _nodes, edges) => [
      edges[0],
    ]);

    act(() => {
      result.current.handleNodeDragStart({}, startNode, [startNode]);
      result.current.handleNodeDragStop({}, movedNode, [movedNode]);
    });

    expect(mockSnapEdgesToNearestHandles).toHaveBeenCalledTimes(1);
    expect(getEdges()).toHaveLength(2);
    expect(getEdges().map((edge) => edge.id)).toEqual(['e-1', 'e-2']);
    expect(args.dirtyRef.current).toBe(true);
  });
});
