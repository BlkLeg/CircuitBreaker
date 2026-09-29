import { useRef, useEffect, useCallback } from 'react';

/**
 * useMapPolling
 *
 * Consolidates all timer refs owned by MapPage into one place.
 * Every timer is cleared on unmount via the single useEffect cleanup.
 *
 * The returned schedulers keep a stable identity for the life of the map, so
 * callers may pass inline callbacks. Memoizing a scheduler on its callback made
 * it change on every render; MapWorkspace's cloud-view effect depends on one
 * and calls setNodes, so that fed a render loop that never settled.
 *
 * @param {object} callbacks
 * @param {(node: object, pos: {x,y}) => void} callbacks.onTelemetrySidebarShow
 * @param {(value: string) => void}             callbacks.onTagDebounced
 * @param {() => void}                          callbacks.onCloudViewFit
 * @param {() => void}                          callbacks.onResizeFit
 * @param {() => void}                          callbacks.onResizeObserverLayout
 */
export function useMapPolling({
  onTelemetrySidebarShow,
  onTagDebounced,
  onCloudViewFit,
  onResizeFit,
  onResizeObserverLayout,
} = {}) {
  // ── Internal timer refs ────────────────────────────────────────────────────
  const telemetrySidebarTimerRef = useRef(null);
  const tagDebounceRef = useRef(null);
  const cloudViewFitRef = useRef(null);
  const resizeFitRef = useRef(null);
  const resizeObserverRef = useRef(null);

  // Latest callbacks, read when a timer fires rather than captured when it is scheduled.
  const callbacksRef = useRef({});
  callbacksRef.current = {
    onTelemetrySidebarShow,
    onTagDebounced,
    onCloudViewFit,
    onResizeFit,
    onResizeObserverLayout,
  };

  // ── Global unmount cleanup ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      clearTimeout(telemetrySidebarTimerRef.current);
      clearTimeout(tagDebounceRef.current);
      clearTimeout(cloudViewFitRef.current);
      clearTimeout(resizeFitRef.current);
      clearTimeout(resizeObserverRef.current);
    };
  }, []);

  // ── Telemetry-sidebar hover delay (400 ms) ─────────────────────────────────
  const scheduleTelemetrySidebar = useCallback((node, pos) => {
    clearTimeout(telemetrySidebarTimerRef.current);
    telemetrySidebarTimerRef.current = setTimeout(() => {
      callbacksRef.current.onTelemetrySidebarShow?.(node, pos);
    }, 400);
  }, []);

  const cancelTelemetrySidebar = useCallback(() => {
    clearTimeout(telemetrySidebarTimerRef.current);
    telemetrySidebarTimerRef.current = null;
  }, []);

  // ── Tag-filter debounce (300 ms) ───────────────────────────────────────────
  const scheduleTagDebounce = useCallback((value) => {
    clearTimeout(tagDebounceRef.current);
    tagDebounceRef.current = setTimeout(() => {
      callbacksRef.current.onTagDebounced?.(value);
    }, 300);
  }, []);

  // ── Cloud-view toggle → fit viewport (100 ms) ─────────────────────────────
  const scheduleCloudViewFit = useCallback(() => {
    clearTimeout(cloudViewFitRef.current);
    cloudViewFitRef.current = setTimeout(() => {
      callbacksRef.current.onCloudViewFit?.();
    }, 100);
  }, []);

  // ── Window-resize debounce → refit (300 ms) ───────────────────────────────
  const scheduleResizeFit = useCallback(() => {
    clearTimeout(resizeFitRef.current);
    resizeFitRef.current = setTimeout(() => {
      callbacksRef.current.onResizeFit?.();
    }, 300);
  }, []);

  // ── ResizeObserver → re-apply layout (200 ms) ─────────────────────────────
  const scheduleResizeObserverLayout = useCallback(() => {
    clearTimeout(resizeObserverRef.current);
    resizeObserverRef.current = setTimeout(() => {
      callbacksRef.current.onResizeObserverLayout?.();
    }, 200);
  }, []);

  return {
    scheduleTelemetrySidebar,
    cancelTelemetrySidebar,
    scheduleTagDebounce,
    scheduleCloudViewFit,
    scheduleResizeFit,
    scheduleResizeObserverLayout,
  };
}
