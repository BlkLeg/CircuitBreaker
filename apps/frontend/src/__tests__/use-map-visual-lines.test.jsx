import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useMapVisualLines } from '../hooks/useMapVisualLines';

function makeArgs(overrides = {}) {
  let visualLinesState = [
    { id: 'v1', lineType: 'ethernet', startFlow: { x: 0, y: 0 }, endFlow: { x: 1, y: 1 } },
  ];
  const setVisualLines = vi.fn((updater) => {
    visualLinesState = typeof updater === 'function' ? updater(visualLinesState) : updater;
  });
  const setSelectedVisualLineId = vi.fn();
  const args = {
    lineDrawMode: null,
    setLineDrawMode: vi.fn(),
    setLineDrawDraft: vi.fn(),
    lineDrawDraftRef: { current: null },
    linePointerMoveRef: { current: null },
    linePointerUpRef: { current: null },
    flowContainerRef: { current: null },
    screenToFlow: vi.fn(() => ({ x: 0, y: 0 })),
    setVisualLines,
    selectedVisualLineId: 'v1',
    setSelectedVisualLineId,
    dirtyRef: { current: false },
    ...overrides,
  };
  return { args, getVisualLines: () => visualLinesState, setSelectedVisualLineId, setVisualLines };
}

describe('useMapVisualLines', () => {
  it('updates lineType and marks dirty', () => {
    const { args, getVisualLines } = makeArgs();
    const { result } = renderHook(() => useMapVisualLines(args));

    act(() => {
      result.current.updateVisualLineType('v1', 'wireless');
    });

    expect(getVisualLines()[0].lineType).toBe('wireless');
    expect(args.dirtyRef.current).toBe(true);
  });

  it('deletes selected line and clears selection', () => {
    const { args, getVisualLines, setSelectedVisualLineId } = makeArgs();
    const { result } = renderHook(() => useMapVisualLines(args));

    act(() => {
      result.current.deleteVisualLine('v1');
    });

    expect(getVisualLines()).toEqual([]);
    expect(setSelectedVisualLineId).toHaveBeenCalledWith(null);
    expect(args.dirtyRef.current).toBe(true);
  });
});
