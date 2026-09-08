/**
 * The canonical map document: what the map *is*, as opposed to what the editor
 * is currently doing to it.
 *
 * Nodes, edges, edge overrides, boundaries, labels and visual lines are the
 * durable, high-frequency state; the mirroring refs exist because pointer
 * handlers and async callbacks need the latest value without re-subscribing.
 * Keeping the refs beside the state they mirror is the point — they drifted
 * apart when they lived in a 3,000-line component.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useMapDocument } from '../hooks/useMapDocument';

describe('useMapDocument', () => {
  it('starts as an empty, clean document', () => {
    const { result } = renderHook(() => useMapDocument());

    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.boundaries).toEqual([]);
    expect(result.current.mapLabels).toEqual([]);
    expect(result.current.visualLines).toEqual([]);
    expect(result.current.edgeOverrides).toEqual({});
    expect(result.current.dirtyRef.current).toBe(false);
  });

  it('mirrors nodes into nodesRef', async () => {
    const { result } = renderHook(() => useMapDocument());

    act(() => result.current.setNodes([{ id: 'a' }]));

    await waitFor(() => expect(result.current.nodesRef.current).toEqual([{ id: 'a' }]));
  });

  it('mirrors edge overrides, labels and visual lines into their refs', async () => {
    const { result } = renderHook(() => useMapDocument());

    act(() => {
      result.current.setEdgeOverrides({ 'e-1': { sourceSide: 'left' } });
      result.current.setMapLabels([{ id: 'l-1' }]);
      result.current.setVisualLines([{ id: 'v-1' }]);
    });

    await waitFor(() => {
      expect(result.current.edgeOverridesRef.current).toEqual({ 'e-1': { sourceSide: 'left' } });
      expect(result.current.mapLabelsRef.current).toEqual([{ id: 'l-1' }]);
      expect(result.current.visualLinesRef.current).toEqual([{ id: 'v-1' }]);
    });
  });

  it('keeps ref identities stable across renders', () => {
    const { result, rerender } = renderHook(() => useMapDocument());
    const before = result.current.nodesRef;

    act(() => result.current.setNodes([{ id: 'a' }]));
    rerender();

    expect(result.current.nodesRef).toBe(before);
  });

  it('holds boundaries and edges independently of nodes', () => {
    const { result } = renderHook(() => useMapDocument());

    act(() => {
      result.current.setBoundaries([{ id: 'b-1' }]);
      result.current.setEdges([{ id: 'e-1', source: 'a', target: 'b' }]);
    });

    expect(result.current.boundaries).toEqual([{ id: 'b-1' }]);
    expect(result.current.edges).toHaveLength(1);
    expect(result.current.nodes).toEqual([]);
  });
});
