/**
 * The map's timer hook hands back schedulers that effects depend on.
 *
 * MapWorkspace passes its callbacks inline, so they are new on every render.
 * When each scheduler was memoized on its callback it changed identity every
 * render too, and the cloud-view effect — which depends on one and calls
 * setNodes — re-ran on every render and fed a render loop. The loop kept the
 * node-details panel re-selecting itself after its close button was clicked.
 */
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useMapPolling } from '../features/map/hooks/useMapPolling';

const SCHEDULERS = [
  'scheduleTelemetrySidebar',
  'cancelTelemetrySidebar',
  'scheduleTagDebounce',
  'scheduleCloudViewFit',
  'scheduleResizeFit',
  'scheduleResizeObserverLayout',
];

function inlineCallbacks() {
  return {
    onTelemetrySidebarShow: vi.fn(),
    onTagDebounced: vi.fn(),
    onCloudViewFit: vi.fn(),
    onResizeFit: vi.fn(),
    onResizeObserverLayout: vi.fn(),
  };
}

describe('useMapPolling', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('keeps every scheduler stable when the callbacks are new each render', () => {
    const { result, rerender } = renderHook((callbacks) => useMapPolling(callbacks), {
      initialProps: inlineCallbacks(),
    });
    const first = { ...result.current };

    rerender(inlineCallbacks());

    const after = new Map(Object.entries(result.current));
    for (const [name, scheduler] of Object.entries(first)) {
      expect(after.get(name), name).toBe(scheduler);
    }
    expect([...after.keys()].sort()).toEqual([...SCHEDULERS].sort());
  });

  it('fires the latest callback, not the one current when it was scheduled', () => {
    const stale = inlineCallbacks();
    const latest = inlineCallbacks();
    const { result, rerender } = renderHook((callbacks) => useMapPolling(callbacks), {
      initialProps: stale,
    });

    result.current.scheduleCloudViewFit();
    rerender(latest);
    vi.advanceTimersByTime(100);

    expect(stale.onCloudViewFit).not.toHaveBeenCalled();
    expect(latest.onCloudViewFit).toHaveBeenCalledTimes(1);
  });

  it('still debounces: a reschedule replaces the pending timer', () => {
    const callbacks = inlineCallbacks();
    const { result } = renderHook(() => useMapPolling(callbacks));

    result.current.scheduleTagDebounce('a');
    vi.advanceTimersByTime(200);
    result.current.scheduleTagDebounce('ab');
    vi.advanceTimersByTime(300);

    expect(callbacks.onTagDebounced).toHaveBeenCalledTimes(1);
    expect(callbacks.onTagDebounced).toHaveBeenCalledWith('ab');
  });
});
