import { describe, expect, it, vi } from 'vitest';
import { getConnectedHandleIds, snapEdgesToNearestHandles } from '../utils/mapHandleHelpers';

function mockNode(id, x, y) {
  return { id, position: { x, y }, width: 140, height: 140 };
}

function mockEdge(sourceHandle = 's-top', targetHandle = 't-top') {
  return {
    id: 'e-1',
    source: 'a',
    target: 'b',
    sourceHandle,
    targetHandle,
    data: {},
  };
}

describe('mapHandleHelpers', () => {
  it('snaps to right/left handles for side-by-side nodes', () => {
    const nodes = [mockNode('a', 0, 0), mockNode('b', 220, 0)];
    const edges = [mockEdge('s-top', 't-top')];

    const result = snapEdgesToNearestHandles(['a'], nodes, edges, {});

    expect(result[0].sourceHandle).toBe('s-right');
    expect(result[0].targetHandle).toBe('t-left');
    expect(result[0].sourceHandleId).toBe('s-right');
    expect(result[0].targetHandleId).toBe('t-left');
  });

  it('does not mutate original edges', () => {
    const nodes = [mockNode('a', 0, 0), mockNode('b', 220, 0)];
    const edges = [mockEdge('s-top', 't-top')];
    const original = JSON.stringify(edges);

    const result = snapEdgesToNearestHandles(['a'], nodes, edges, {});

    expect(JSON.stringify(edges)).toBe(original);
    expect(result[0]).not.toBe(edges[0]);
  });

  it('preserves edge identity and count for extreme movement', () => {
    const nodes = [mockNode('a', 9999, 9999), mockNode('b', 20, 20), mockNode('c', -4000, 2000)];
    const edges = [
      {
        id: 'e-1',
        source: 'a',
        target: 'b',
        sourceHandle: 's-top',
        targetHandle: 't-bottom',
        data: {},
      },
      {
        id: 'e-2',
        source: 'c',
        target: 'a',
        sourceHandle: 's-left',
        targetHandle: 't-right',
        data: {},
      },
      {
        id: 'e-3',
        source: 'b',
        target: 'c',
        sourceHandle: 's-right',
        targetHandle: 't-left',
        data: {},
      },
    ];

    const result = snapEdgesToNearestHandles(['a'], nodes, edges, {});

    expect(result).toHaveLength(edges.length);
    expect(result.map((edge) => edge.id)).toEqual(edges.map((edge) => edge.id));
    expect(result.map((edge) => [edge.source, edge.target])).toEqual(
      edges.map((edge) => [edge.source, edge.target])
    );
  });

  it('falls back to original edge when snapping throws', () => {
    const explodingNode = { id: 'a', position: { x: 0, y: 0 } };
    Object.defineProperty(explodingNode, 'width', {
      get() {
        throw new Error('boom');
      },
    });
    const nodes = [explodingNode, mockNode('b', 220, 0)];
    const edges = [mockEdge('s-top', 't-top')];
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const result = snapEdgesToNearestHandles(['a'], nodes, edges, {});

    expect(result).toEqual(edges);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('returns connected source and target handle ids for a node', () => {
    const edges = [
      {
        id: 'e-1',
        source: 'node-1',
        target: 'node-2',
        sourceHandle: 's-right',
        targetHandle: 't-left',
      },
      {
        id: 'e-2',
        source: 'node-3',
        target: 'node-1',
        sourceHandle: 's-bottom',
        targetHandle: 't-top-left',
      },
    ];

    const connected = getConnectedHandleIds('node-1', edges);

    expect(connected).toEqual(new Set(['right', 'top-left']));
  });

  it('resolves connected handles from sourceHandleId/targetHandleId fallback fields', () => {
    const edges = [
      {
        id: 'e-1',
        source: 'node-1',
        target: 'node-2',
        sourceHandle: null,
        targetHandle: null,
        sourceHandleId: 's-left',
        targetHandleId: 't-top',
      },
      {
        id: 'e-2',
        source: 'node-3',
        target: 'node-1',
        sourceHandle: null,
        targetHandle: null,
        sourceHandleId: 's-bottom',
        targetHandleId: 't-top-right',
      },
    ];

    const connected = getConnectedHandleIds('node-1', edges);

    expect(connected).toEqual(new Set(['left', 'top-right']));
  });
});
